from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from .consolidate import LabelerConfig, _json_from_text, _label_command, _tokens, ensure_consolidation_tables
from .harness import run_llm


BRAIN_TARGETS = ("cluster", "node", "synapse", "relationship")


def ensure_brain_tables(conn: sqlite3.Connection) -> None:
    ensure_consolidation_tables(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS brain_label_runs(
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source_consolidation_run_id TEXT,
            config_json TEXT NOT NULL,
            summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS brain_labels(
            run_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            label_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            PRIMARY KEY(run_id, target_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_labels_target ON brain_labels(target_type, target_id);
        """
    )


def _latest_consolidation_run_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT id FROM consolidation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _latest_brain_label_run_id(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT id FROM brain_label_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _clean_labels(values) -> list[str]:
    labels: list[str] = []
    if isinstance(values, list):
        for value in values:
            text = str(value).strip().lower()
            if text and len(text) <= 80 and text not in labels:
                labels.append(text)
    return labels[:8]


def _prompt(target: dict) -> str:
    return (
        "You label one memory-brain target for retrieval and traversal. "
        "Return only JSON with keys: labels (2-8 short lowercase phrases), "
        "summary (one short sentence), intent (short phrase), ignore (boolean). "
        "Do not invent facts beyond the supplied target.\n\n"
        + json.dumps(target, ensure_ascii=False)
    )


def _call_labeler(target: dict, fallback_labels: list[str], labeler: LabelerConfig) -> tuple[list[str], dict, dict]:
    if not labeler.enabled:
        return fallback_labels, {"summary": "", "intent": "", "ignore": False}, {"source": "procedural"}
    result = run_llm(
        _prompt(target),
        provider=labeler.provider or "custom",
        command=_label_command(labeler),
        timeout=labeler.timeout,
    )
    parsed = _json_from_text(result.stdout)
    labels = _clean_labels(parsed.get("labels")) or fallback_labels
    meta = {
        "summary": str(parsed.get("summary") or "")[:500] if parsed else "",
        "intent": str(parsed.get("intent") or "")[:160] if parsed else "",
        "ignore": bool(parsed.get("ignore")) if parsed else False,
    }
    provenance = {
        "source": "llm" if result.ok and parsed else "procedural_fallback",
        "provider": labeler.provider or "custom",
        "model": labeler.model,
        "ok": result.ok,
        "exit_code": result.exit_code,
        "error": result.error,
        "stderr": result.stderr[:500],
        "stdout_excerpt": result.stdout[:500] if result.ok and not parsed else "",
    }
    return labels, meta, provenance


def _cluster_targets(conn: sqlite3.Connection, consolidation_run_id: str, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT cluster_id,size,label_json,summary_json FROM memory_clusters WHERE run_id=? ORDER BY size DESC,cluster_id LIMIT ?",
        (consolidation_run_id, limit),
    ).fetchall()
    return [
        {
            "target_type": "cluster",
            "target_id": cluster_id,
            "fallback_labels": json.loads(label_json or "[]"),
            "payload": {
                "type": "cluster",
                "id": cluster_id,
                "size": size,
                "labels": json.loads(label_json or "[]"),
                "summary": json.loads(summary_json or "{}"),
            },
        }
        for cluster_id, size, label_json, summary_json in rows
    ]


def _node_targets(conn: sqlite3.Connection, consolidation_run_id: str | None, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT n.id,n.type,n.name,n.source_path,COALESCE(m.role,''),COALESCE(m.salience,0),COALESCE(m.hubness,0)
        FROM nodes n
        LEFT JOIN cluster_memberships m ON m.node_id=n.id AND (? IS NOT NULL AND m.run_id=?)
        ORDER BY COALESCE(m.salience,0) DESC,n.updated_at DESC,n.name
        LIMIT ?
        """,
        (consolidation_run_id, consolidation_run_id, limit),
    ).fetchall()
    return [
        {
            "target_type": "node",
            "target_id": node_id,
            "fallback_labels": list(_tokens(node_type, name, source_path))[:8],
            "payload": {
                "type": "node",
                "id": node_id,
                "node_type": node_type,
                "name": name,
                "source_path": source_path,
                "role": role,
                "salience": round(float(salience or 0), 3),
                "hubness": round(float(hubness or 0), 3),
            },
        }
        for node_id, node_type, name, source_path, role, salience, hubness in rows
    ]


def _synapse_targets(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.id,e.relation,e.status,e.strength,e.confidence,e.source_type,e.source_path,e.evidence_text,
               s.name,d.name
        FROM edges e
        JOIN nodes s ON s.id=e.src_id
        JOIN nodes d ON d.id=e.dst_id
        WHERE COALESCE(e.status,'candidate') != 'killed'
        ORDER BY e.status='active' DESC,e.strength DESC,e.confidence DESC,e.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "target_type": "synapse",
            "target_id": edge_id,
            "fallback_labels": list(_tokens(relation, src_name, dst_name, evidence))[:8],
            "payload": {
                "type": "synapse",
                "id": edge_id,
                "relation": relation,
                "status": status,
                "strength": strength,
                "confidence": confidence,
                "source_type": source_type,
                "source_path": source_path,
                "src": src_name,
                "dst": dst_name,
                "evidence": (evidence or "")[:500],
            },
        }
        for edge_id, relation, status, strength, confidence, source_type, source_path, evidence, src_name, dst_name in rows
    ]


def _relationship_targets(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT rt.id,rt.label,rt.category,rt.domain_type,rt.range_type,rt.description,rt.requires_validation,
               COUNT(e.id) AS uses
        FROM relationship_types rt
        LEFT JOIN edges e ON e.relation=rt.id
        GROUP BY rt.id
        ORDER BY uses DESC,rt.id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "target_type": "relationship",
            "target_id": rel_id,
            "fallback_labels": list(_tokens(rel_id, label, category))[:8],
            "payload": {
                "type": "relationship",
                "id": rel_id,
                "label": label,
                "category": category,
                "domain_type": domain_type,
                "range_type": range_type,
                "description": description,
                "requires_validation": bool(requires_validation),
                "uses": uses,
            },
        }
        for rel_id, label, category, domain_type, range_type, description, requires_validation, uses in rows
    ]


def label_brain(
    db_path: Path,
    *,
    labeler: LabelerConfig | None = None,
    targets: list[str] | None = None,
    max_clusters: int = 25,
    max_nodes: int = 50,
    max_synapses: int = 50,
    max_relationships: int = 25,
) -> dict:
    labeler = labeler or LabelerConfig()
    requested = targets or list(BRAIN_TARGETS)
    unknown = sorted(set(requested) - set(BRAIN_TARGETS))
    if unknown:
        raise ValueError(f"unknown brain label target(s): {', '.join(unknown)}")
    conn = sqlite3.connect(db_path)
    ensure_brain_tables(conn)
    consolidation_run_id = _latest_consolidation_run_id(conn)
    created_at = conn.execute("SELECT datetime('now')").fetchone()[0]
    run_id = f"brain-labels-{created_at.replace(':','').replace(' ','-')}"
    conn.execute("DELETE FROM brain_label_runs WHERE id=?", (run_id,))
    conn.execute("DELETE FROM brain_labels WHERE run_id=?", (run_id,))

    target_rows: list[dict] = []
    if "cluster" in requested and consolidation_run_id:
        target_rows.extend(_cluster_targets(conn, consolidation_run_id, max_clusters))
    if "node" in requested:
        target_rows.extend(_node_targets(conn, consolidation_run_id, max_nodes))
    if "synapse" in requested:
        target_rows.extend(_synapse_targets(conn, max_synapses))
    if "relationship" in requested:
        target_rows.extend(_relationship_targets(conn, max_relationships))

    counts: Counter = Counter()
    fallbacks = 0
    for target in target_rows:
        labels, summary, provenance = _call_labeler(target["payload"], target["fallback_labels"], labeler)
        if provenance["source"] != "llm":
            fallbacks += 1
        counts[target["target_type"]] += 1
        conn.execute(
            """INSERT INTO brain_labels(run_id,target_type,target_id,label_json,summary_json,provenance_json)
               VALUES(?,?,?,?,?,?)""",
            (
                run_id,
                target["target_type"],
                target["target_id"],
                json.dumps(labels, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(provenance, ensure_ascii=False),
            ),
        )
    summary = {
        "targets": dict(counts),
        "total": sum(counts.values()),
        "fallback_labels": fallbacks,
        "source": "llm" if labeler.enabled else "procedural",
        "provider": labeler.provider,
        "model": labeler.model,
    }
    conn.execute(
        "INSERT INTO brain_label_runs(id,created_at,source_consolidation_run_id,config_json,summary_json) VALUES(?,?,?,?,?)",
        (
            run_id,
            created_at,
            consolidation_run_id,
            json.dumps(
                {
                    "targets": requested,
                    "max_clusters": max_clusters,
                    "max_nodes": max_nodes,
                    "max_synapses": max_synapses,
                    "max_relationships": max_relationships,
                    "labeler": {
                        "enabled": labeler.enabled,
                        "provider": labeler.provider,
                        "model": labeler.model,
                        "timeout": labeler.timeout,
                        "command": list(labeler.command) if isinstance(labeler.command, (list, tuple)) else labeler.command,
                    },
                },
                ensure_ascii=False,
            ),
            json.dumps(summary, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return {"run_id": run_id, "source_consolidation_run_id": consolidation_run_id, **summary}


def brain_label_matches(conn: sqlite3.Connection, prompt: str, *, limit: int = 12) -> dict:
    run_id = _latest_brain_label_run_id(conn)
    if not run_id:
        return {"run_id": None, "matches": [], "by_target": {}}
    query_tokens = _tokens(prompt)
    if not query_tokens:
        return {"run_id": run_id, "matches": [], "by_target": {}}
    matches: list[dict] = []
    for target_type, target_id, label_json, summary_json, provenance_json in conn.execute(
        "SELECT target_type,target_id,label_json,summary_json,provenance_json FROM brain_labels WHERE run_id=?",
        (run_id,),
    ):
        labels = json.loads(label_json or "[]")
        summary = json.loads(summary_json or "{}")
        provenance = json.loads(provenance_json or "{}")
        matched = sorted(query_tokens & (_tokens(*labels) | _tokens(summary.get("summary"), summary.get("intent"))))
        if not matched:
            continue
        score = len(matched) * (4.0 if provenance.get("source") == "llm" else 2.0)
        score += min(3.0, len(labels) * 0.2)
        matches.append(
            {
                "run_id": run_id,
                "target_type": target_type,
                "target_id": target_id,
                "labels": labels,
                "summary": summary,
                "provenance": provenance,
                "matched_terms": matched,
                "score": round(score, 2),
            }
        )
    matches.sort(key=lambda item: (-item["score"], item["target_type"], item["target_id"]))
    selected = matches[:limit]
    by_target = {(item["target_type"], item["target_id"]): item for item in selected}
    return {"run_id": run_id, "matches": selected, "by_target": by_target}


def brain_report(db_path: Path, *, limit: int = 20) -> dict:
    conn = sqlite3.connect(db_path)
    ensure_brain_tables(conn)
    run_id = _latest_brain_label_run_id(conn)
    if not run_id:
        conn.close()
        return {"run_id": None, "empty_reason": "No brain label run exists yet."}
    rows = conn.execute(
        "SELECT target_type,label_json,summary_json,provenance_json FROM brain_labels WHERE run_id=?",
        (run_id,),
    ).fetchall()
    source_counts = Counter(json.loads(row[3] or "{}").get("source", "unknown") for row in rows)
    target_counts = Counter(row[0] for row in rows)
    vague = []
    for target_type, label_json, summary_json, provenance_json in rows:
        labels = json.loads(label_json or "[]")
        generic = {"memory", "project", "notes", "source", "run", "actions", "current"}
        if len(set(_tokens(*labels)) - generic) <= 1:
            vague.append({"target_type": target_type, "labels": labels})
    conn.close()
    return {
        "run_id": run_id,
        "counts": dict(target_counts),
        "sources": dict(source_counts),
        "vague_label_examples": vague[:limit],
    }
