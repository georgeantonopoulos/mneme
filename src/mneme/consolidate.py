from __future__ import annotations

import json
import math
import re
import sqlite3
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .harness import DEFAULT_TIMEOUT_SECONDS, run_llm


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

RELATION_WEIGHTS = {
    "has_blocked": 3.0,
    "has_risk": 2.8,
    "mentions_decision": 2.6,
    "relates_to": 2.4,
    "part_of": 2.0,
    "mentions": 1.8,
    "links_to": 0.55,
    "contains_heading": 0.45,
}


@dataclass
class NodeStats:
    weighted_degree: float
    participation: float
    local_clustering: float
    hubness: float
    salience: float
    role: str


@dataclass
class LabelerConfig:
    provider: str | None = None
    model: str | None = None
    command: str | Sequence[str] | None = None
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    max_clusters: int = 25

    @property
    def enabled(self) -> bool:
        return bool(self.provider or self.command)


def _tokens(*values: str | None) -> set[str]:
    found: set[str] = set()
    for value in values:
        if not value:
            continue
        found.update(token.lower() for token in TOKEN_RE.findall(value))
    return found


def _label_command(config: LabelerConfig) -> str | Sequence[str] | None:
    if config.command is not None:
        return config.command
    if config.provider == "ollama":
        if not config.model:
            raise ValueError("--label-model is required when --label-provider=ollama")
        return ["ollama", "run", config.model, "--format", "json", "--hidethinking", "--think", "false", "--nowordwrap"]
    return None


def _json_from_text(text: str) -> dict:
    cleaned = ANSI_RE.sub("", text or "")
    cleaned = "".join(ch for ch in cleaned if ch in "\n\r\t" or ord(ch) >= 32).strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _cluster_label_prompt(cluster_id: str, size: int, summary: dict) -> str:
    members = summary.get("top_members") or []
    compact_members = [
        {
            "name": item.get("name"),
            "type": item.get("type"),
            "source_path": item.get("source_path"),
            "role": item.get("role"),
        }
        for item in members[:10]
    ]
    return (
        "You label a memory-graph cluster for retrieval. "
        "Return only JSON with keys: labels (2-6 short lowercase phrases), "
        "summary (one short sentence), intent (short phrase), ignore (boolean). "
        "Do not invent facts beyond the supplied members.\n\n"
        + json.dumps(
            {
                "cluster_id": cluster_id,
                "size": size,
                "role_counts": summary.get("role_counts", {}),
                "type_counts": summary.get("type_counts", {}),
                "top_members": compact_members,
            },
            ensure_ascii=False,
        )
    )


def _llm_label_cluster(cluster_id: str, size: int, labels: list[str], summary: dict, config: LabelerConfig) -> tuple[list[str], dict]:
    command = _label_command(config)
    result = run_llm(
        _cluster_label_prompt(cluster_id, size, summary),
        provider=config.provider or "custom",
        command=command,
        timeout=config.timeout,
    )
    parsed = _json_from_text(result.stdout)
    llm_labels = parsed.get("labels") if isinstance(parsed.get("labels"), list) else []
    clean_labels = []
    for label in llm_labels:
        text = str(label).strip().lower()
        if text and len(text) <= 80:
            clean_labels.append(text)
    if not clean_labels:
        clean_labels = labels
    label_meta = {
        "source": "llm" if result.ok and parsed else "procedural_fallback",
        "provider": config.provider or "custom",
        "model": config.model,
        "ok": result.ok,
        "exit_code": result.exit_code,
        "error": result.error,
        "stderr": result.stderr[:500],
        "stdout_excerpt": result.stdout[:500] if result.ok and not parsed else "",
        "summary": str(parsed.get("summary") or "")[:500] if parsed else "",
        "intent": str(parsed.get("intent") or "")[:160] if parsed else "",
        "ignore": bool(parsed.get("ignore")) if parsed else False,
    }
    return clean_labels[:6], label_meta


def _edge_weight(relation: str, status: str | None, confidence: float | None, strength: float | None) -> float:
    base = RELATION_WEIGHTS.get(relation, 1.2)
    if status != "active":
        base *= 0.35
    return base * max(0.05, float(confidence or 0.0)) * max(0.05, float(strength or 0.0))


def ensure_consolidation_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS consolidation_runs(
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            config_json TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_clusters(
            run_id TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            size INTEGER NOT NULL,
            label_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            PRIMARY KEY(run_id, cluster_id)
        );
        CREATE TABLE IF NOT EXISTS cluster_memberships(
            run_id TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            role TEXT NOT NULL,
            salience REAL NOT NULL,
            hubness REAL NOT NULL,
            participation REAL NOT NULL,
            local_clustering REAL NOT NULL,
            weighted_degree REAL NOT NULL,
            PRIMARY KEY(run_id, node_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cluster_memberships_cluster ON cluster_memberships(run_id, cluster_id);
        CREATE INDEX IF NOT EXISTS idx_cluster_memberships_node ON cluster_memberships(node_id);
        """
    )


def _latest_run_id(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT id FROM consolidation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _load_graph(conn: sqlite3.Connection):
    nodes = {
        row[0]: {"id": row[0], "type": row[1], "name": row[2], "source_path": row[3], "confidence": row[4] or 1.0}
        for row in conn.execute("SELECT id,type,name,source_path,confidence FROM nodes")
    }
    relation_categories = {
        row[0]: row[1] for row in conn.execute("SELECT id,category FROM relationship_types")
    }
    adjacency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    edge_relations: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for _edge_id, src, dst, relation, confidence, strength, status in conn.execute(
        "SELECT id,src_id,dst_id,relation,confidence,strength,status FROM edges WHERE COALESCE(status,'candidate') != 'killed'"
    ):
        if src not in nodes or dst not in nodes:
            continue
        weight = _edge_weight(relation, status, confidence, strength)
        category = relation_categories.get(relation)
        if category in {"reference", "structure", "extraction"}:
            weight *= 0.65
        adjacency[src][dst] += weight
        adjacency[dst][src] += weight
        key = tuple(sorted((src, dst)))
        edge_relations[key][relation] += 1
    return nodes, adjacency, edge_relations


def _label_propagation(nodes: dict, adjacency: dict[str, dict[str, float]], iterations: int) -> dict[str, str]:
    labels = {node_id: node_id for node_id in nodes}
    for _ in range(max(1, iterations)):
        changed = False
        for node_id in sorted(nodes):
            weights: dict[str, float] = defaultdict(float)
            for neighbor, weight in adjacency.get(node_id, {}).items():
                weights[labels[neighbor]] += weight
            if not weights:
                continue
            best = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[0][0]
            if labels[node_id] != best:
                labels[node_id] = best
                changed = True
        if not changed:
            break
    remap: dict[str, str] = {}
    for idx, label in enumerate(sorted(set(labels.values())), start=1):
        remap[label] = f"c{idx:04d}"
    return {node_id: remap[label] for node_id, label in labels.items()}


def _local_clustering(node_id: str, adjacency: dict[str, dict[str, float]]) -> float:
    neighbors = list(adjacency.get(node_id, {}))
    if len(neighbors) < 2:
        return 0.0
    neighbor_set = set(neighbors)
    links = 0
    possible = len(neighbors) * (len(neighbors) - 1) / 2
    for index, left in enumerate(neighbors):
        for right in neighbors[index + 1 :]:
            if right in adjacency.get(left, {}) and left in adjacency.get(right, {}):
                links += 1
    return links / possible if possible else 0.0


def _node_stats(nodes: dict, adjacency: dict[str, dict[str, float]], clusters: dict[str, str]) -> dict[str, NodeStats]:
    degrees = {node_id: sum(adjacency.get(node_id, {}).values()) for node_id in nodes}
    ordered_degrees = sorted(degrees.values())
    high_degree = ordered_degrees[int(len(ordered_degrees) * 0.80)] if ordered_degrees else 0.0
    stats: dict[str, NodeStats] = {}
    for node_id, node in nodes.items():
        by_cluster: dict[str, float] = defaultdict(float)
        for neighbor, weight in adjacency.get(node_id, {}).items():
            by_cluster[clusters.get(neighbor, clusters[node_id])] += weight
        degree = degrees[node_id]
        participation = 0.0
        if degree > 0:
            participation = 1.0 - sum((weight / degree) ** 2 for weight in by_cluster.values())
        clustering = _local_clustering(node_id, adjacency)
        hubness = math.log1p(degree) * (1.0 + participation) * (1.0 - min(0.85, clustering))
        evidence_boost = 0.8 if node["type"] in {"observation", "project", "person", "event", "finance"} else 0.0
        source_boost = 0.4 if node.get("source_path") else 0.0
        salience = math.log1p(degree) + evidence_boost + source_boost - (hubness * 0.35)
        role = "leaf"
        if degree >= high_degree and participation >= 0.45 and clustering <= 0.35:
            role = "hub"
        elif participation >= 0.35 and degree > 0:
            role = "bridge"
        elif salience >= 2.0 and role != "hub":
            role = "exemplar"
        elif node["type"] in {"note", "heading", "observation", "project", "person", "event", "finance"}:
            role = "content"
        stats[node_id] = NodeStats(degree, participation, clustering, hubness, salience, role)
    return stats


def consolidate_graph(db_path: Path, *, iterations: int = 12, min_cluster_size: int = 2, labeler: LabelerConfig | None = None) -> dict:
    labeler = labeler or LabelerConfig()
    with sqlite3.connect(db_path) as conn:
        ensure_consolidation_tables(conn)
        nodes, adjacency, edge_relations = _load_graph(conn)
        clusters = _label_propagation(nodes, adjacency, iterations)
        stats = _node_stats(nodes, adjacency, clusters)
        digest = hashlib.sha1(f"{len(nodes)}:{len(edge_relations)}:{iterations}:{min_cluster_size}".encode()).hexdigest()[:8]
        run_id = f"consolidate-{digest}"
        created_at = conn.execute("SELECT datetime('now')").fetchone()[0]
        conn.execute("DELETE FROM consolidation_runs WHERE id=?", (run_id,))
        conn.execute("DELETE FROM memory_clusters WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM cluster_memberships WHERE run_id=?", (run_id,))

        grouped: dict[str, list[str]] = defaultdict(list)
        for node_id, cluster_id in clusters.items():
            grouped[cluster_id].append(node_id)

        kept_clusters = {cid: ids for cid, ids in grouped.items() if len(ids) >= min_cluster_size}
        labelled = 0
        fallback_labels = 0
        for cluster_id, node_ids in kept_clusters.items():
            for node_id in node_ids:
                stat = stats[node_id]
                conn.execute(
                    """INSERT INTO cluster_memberships(run_id,cluster_id,node_id,role,salience,hubness,participation,local_clustering,weighted_degree)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (run_id, cluster_id, node_id, stat.role, stat.salience, stat.hubness, stat.participation, stat.local_clustering, stat.weighted_degree),
                )
            top_ids = sorted(node_ids, key=lambda nid: (-stats[nid].salience, stats[nid].hubness, nodes[nid]["name"]))[:5]
            label_tokens: Counter = Counter()
            for node_id in top_ids:
                label_tokens.update(_tokens(nodes[node_id]["name"], nodes[node_id].get("source_path")))
            labels = [token for token, _ in label_tokens.most_common(6)]
            role_counts = Counter(stats[node_id].role for node_id in node_ids)
            type_counts = Counter(nodes[node_id]["type"] for node_id in node_ids)
            summary = {
                "top_members": [
                    {
                        "id": node_id,
                        "name": nodes[node_id]["name"],
                        "type": nodes[node_id]["type"],
                        "source_path": nodes[node_id].get("source_path"),
                        "role": stats[node_id].role,
                        "salience": round(stats[node_id].salience, 3),
                        "hubness": round(stats[node_id].hubness, 3),
                    }
                    for node_id in top_ids
                ],
                "role_counts": dict(role_counts),
                "type_counts": dict(type_counts),
                "label_meta": {"source": "procedural"},
            }
            if labeler.enabled and labelled < max(0, labeler.max_clusters):
                labels, label_meta = _llm_label_cluster(cluster_id, len(node_ids), labels, summary, labeler)
                summary["label_meta"] = label_meta
                labelled += 1
                if label_meta["source"] != "llm":
                    fallback_labels += 1
            conn.execute(
                "INSERT INTO memory_clusters(run_id,cluster_id,size,label_json,summary_json) VALUES(?,?,?,?,?)",
                (run_id, cluster_id, len(node_ids), json.dumps(labels), json.dumps(summary, ensure_ascii=False)),
            )
        summary = {
            "nodes": len(nodes),
            "edges": len(edge_relations),
            "clusters": len(kept_clusters),
            "largest_cluster": max((len(ids) for ids in kept_clusters.values()), default=0),
            "roles": dict(Counter(stat.role for node_id, stat in stats.items() if clusters.get(node_id) in kept_clusters)),
            "labeling": {
                "source": "llm" if labeler.enabled else "procedural",
                "provider": labeler.provider,
                "model": labeler.model,
                "clusters_requested": min(len(kept_clusters), max(0, labeler.max_clusters)) if labeler.enabled else 0,
                "clusters_labelled": labelled,
                "fallback_labels": fallback_labels,
            },
        }
        conn.execute(
            "INSERT INTO consolidation_runs(id,created_at,config_json,summary_json) VALUES(?,?,?,?)",
            (
                run_id,
                created_at,
                json.dumps(
                    {
                        "iterations": iterations,
                        "min_cluster_size": min_cluster_size,
                        "labeler": {
                            "enabled": labeler.enabled,
                            "provider": labeler.provider,
                            "model": labeler.model,
                            "timeout": labeler.timeout,
                            "max_clusters": labeler.max_clusters,
                            "command": list(labeler.command) if isinstance(labeler.command, (list, tuple)) else labeler.command,
                        },
                    }
                ),
                json.dumps(summary),
            ),
        )
        conn.commit()
    return {"run_id": run_id, **summary}


def retrieval_cluster_matches(conn: sqlite3.Connection, prompt: str, *, limit: int = 5) -> dict:
    run_id = _latest_run_id(conn)
    if not run_id:
        return {"run_id": None, "clusters": [], "node_boosts": {}}
    query_tokens = _tokens(prompt)
    if not query_tokens:
        return {"run_id": run_id, "clusters": [], "node_boosts": {}}
    rows = conn.execute(
        """SELECT c.cluster_id,c.size,c.label_json,c.summary_json,m.node_id,m.role,m.salience,m.hubness,n.name,n.type,n.source_path
           FROM memory_clusters c
           JOIN cluster_memberships m ON m.run_id=c.run_id AND m.cluster_id=c.cluster_id
           JOIN nodes n ON n.id=m.node_id
           WHERE c.run_id=?""",
        (run_id,),
    ).fetchall()
    by_cluster: dict[str, dict] = {}
    for cluster_id, size, label_json, summary_json, node_id, role, salience, hubness, name, node_type, source_path in rows:
        labels = set(json.loads(label_json or "[]"))
        label_tokens = _tokens(*labels)
        label_overlap = query_tokens & label_tokens
        node_overlap = query_tokens & _tokens(name, source_path)
        overlap = label_overlap | node_overlap
        if not overlap:
            continue
        cluster = by_cluster.setdefault(
            cluster_id,
            {"cluster_id": cluster_id, "size": size, "labels": sorted(labels), "summary": json.loads(summary_json or "{}"), "score": 0.0, "matched_terms": set(), "label_terms": set(), "member_scores": [], "members": []},
        )
        role_bonus = 1.2 if role in {"exemplar", "content"} else 0.5 if role == "bridge" else -0.6 if role == "hub" else 0.0
        score = len(node_overlap) * 2.0 + float(salience or 0.0) + role_bonus - min(1.5, float(hubness or 0.0) * 0.12)
        cluster["matched_terms"].update(overlap)
        cluster["label_terms"].update(label_overlap)
        cluster["member_scores"].append(score)
        cluster["members"].append({"id": node_id, "name": name, "type": node_type, "source_path": source_path, "role": role, "score": round(score, 2)})
    for cluster in by_cluster.values():
        member_scores = sorted(cluster.pop("member_scores"), reverse=True)
        best_members = sum(member_scores[:3]) / max(1, min(3, len(member_scores)))
        label_bonus = len(cluster.get("label_terms") or []) * 5.0
        coverage_bonus = len(cluster.get("matched_terms") or []) * 1.5
        cluster["score"] = label_bonus + coverage_bonus + best_members
    clusters = sorted(by_cluster.values(), key=lambda item: (-item["score"], item["cluster_id"]))[:limit]
    node_boosts: dict[str, dict] = {}
    for cluster in clusters:
        cluster["score"] = round(cluster["score"], 2)
        cluster["matched_terms"] = sorted(cluster["matched_terms"])
        cluster.pop("label_terms", None)
        cluster["members"] = sorted(cluster["members"], key=lambda item: (-item["score"], item["name"]))[:8]
        for member in cluster["members"]:
            node_boosts[member["id"]] = {
                "run_id": run_id,
                "cluster_id": cluster["cluster_id"],
                "cluster_score": cluster["score"],
                "role": member["role"],
                "matched_terms": cluster["matched_terms"],
            }
    return {"run_id": run_id, "clusters": clusters, "node_boosts": node_boosts}
