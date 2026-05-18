from __future__ import annotations

import heapq
import json
import math
import random
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .core import now_iso, stable_id


LOW_VALUE_RELATIONS = {"has_heading", "mentions_date", "mentions_email"}
HIGH_SIGNAL_NODE_TYPES = {"note", "observation", "wikilink"}


@dataclass
class PhysarumRunConfig:
    iterations: int = 80
    terminals: int = 24
    paths_per_iteration: int = 12
    decay: float = 0.92
    reinforcement: float = 1.0
    relation_penalty: float = 1.0
    hub_penalty: float = 0.35
    seed: int = 13


def init_physarum_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS physarum_runs(
          id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          config_json TEXT NOT NULL,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS physarum_edges(
          run_id TEXT NOT NULL,
          edge_id TEXT NOT NULL,
          conductivity REAL NOT NULL,
          flow_count INTEGER NOT NULL,
          PRIMARY KEY(run_id, edge_id)
        );
        CREATE INDEX IF NOT EXISTS idx_physarum_edges_run_conductivity
          ON physarum_edges(run_id, conductivity DESC);
        """
    )


def _load_nodes(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT id,type,name,source_path,metadata_json FROM nodes"
    ).fetchall()
    return {
        row[0]: {
            "id": row[0],
            "type": row[1],
            "name": row[2],
            "source_path": row[3],
            "metadata": json.loads(row[4] or "{}"),
        }
        for row in rows
    }


def _edge_cost(relation: str, src_type: str, dst_type: str, confidence: float, strength: float, src_degree: int, dst_degree: int, cfg: PhysarumRunConfig) -> float:
    cost = 1.0
    if relation in LOW_VALUE_RELATIONS:
        cost += cfg.relation_penalty
    if relation == "links_to":
        cost += cfg.relation_penalty * 0.35
    cost *= 1.0 + cfg.hub_penalty * math.log1p(max(src_degree, dst_degree))
    if src_type == "observation" or dst_type == "observation":
        cost *= 0.7
    if src_type == "note" and dst_type == "note":
        cost *= 0.85
    signal = max(0.05, (float(confidence or 0.0) + float(strength or 0.0)) / 2)
    return max(0.05, cost / signal)


def _load_graph(conn: sqlite3.Connection, nodes: dict[str, dict], cfg: PhysarumRunConfig) -> tuple[dict[str, list[tuple[str, str, float]]], dict[str, dict]]:
    rows = conn.execute(
        """
        SELECT id,src_id,dst_id,relation,confidence,strength,status,source_path,evidence_text
        FROM edges
        WHERE COALESCE(status,'candidate') != 'killed'
        """
    ).fetchall()
    degrees: dict[str, int] = {}
    for _edge_id, src, dst, _relation, _confidence, _strength, _status, _source_path, _evidence_text in rows:
        if src in nodes and dst in nodes:
            degrees[src] = degrees.get(src, 0) + 1
            degrees[dst] = degrees.get(dst, 0) + 1
    graph: dict[str, list[tuple[str, str, float]]] = {}
    edges: dict[str, dict] = {}
    for edge_id, src, dst, relation, confidence, strength, status, source_path, evidence_text in rows:
        if src not in nodes or dst not in nodes:
            continue
        cost = _edge_cost(relation, nodes[src]["type"], nodes[dst]["type"], confidence, strength, degrees.get(src, 0), degrees.get(dst, 0), cfg)
        graph.setdefault(src, []).append((dst, edge_id, cost))
        graph.setdefault(dst, []).append((src, edge_id, cost))
        edges[edge_id] = {
            "id": edge_id,
            "src_id": src,
            "dst_id": dst,
            "relation": relation,
            "status": status,
            "confidence": confidence,
            "strength": strength,
            "source_path": source_path,
            "evidence_text": evidence_text,
        }
    return graph, edges


def _node_weight(node: dict, degree: int) -> float:
    weight = math.log1p(degree)
    if node["type"] == "observation":
        kind = (node.get("metadata") or {}).get("kind")
        weight += {"blocked": 4.0, "risk": 3.5, "fact": 1.5, "done": 0.5}.get(kind, 1.0)
    elif node["type"] == "note":
        weight += 2.0
    elif node["type"] == "wikilink":
        weight += 1.0
    elif node["type"] == "heading":
        weight *= 0.25
    return max(0.05, weight)


def choose_terminals(nodes: dict[str, dict], graph: dict[str, list], count: int, rng: random.Random) -> list[str]:
    candidates = [
        (node_id, _node_weight(node, len(graph.get(node_id, []))))
        for node_id, node in nodes.items()
        if node["type"] in HIGH_SIGNAL_NODE_TYPES and graph.get(node_id)
    ]
    if not candidates:
        return []
    chosen: list[str] = []
    available = candidates[:]
    while available and len(chosen) < count:
        node_ids = [node_id for node_id, _ in available]
        weights = [weight for _, weight in available]
        picked = rng.choices(node_ids, weights=weights, k=1)[0]
        chosen.append(picked)
        available = [(node_id, weight) for node_id, weight in available if node_id != picked]
    return chosen


def shortest_path_edges(graph: dict[str, list[tuple[str, str, float]]], start: str, goal: str) -> list[str]:
    queue: list[tuple[float, str, list[str]]] = [(0.0, start, [])]
    best: dict[str, float] = {start: 0.0}
    while queue:
        cost, node_id, path = heapq.heappop(queue)
        if node_id == goal:
            return path
        if cost > best.get(node_id, float("inf")):
            continue
        for neighbor, edge_id, edge_cost in graph.get(node_id, []):
            next_cost = cost + edge_cost
            if next_cost < best.get(neighbor, float("inf")):
                best[neighbor] = next_cost
                heapq.heappush(queue, (next_cost, neighbor, path + [edge_id]))
    return []


def run_physarum(db_path: Path, config: PhysarumRunConfig | None = None) -> dict:
    cfg = config or PhysarumRunConfig()
    rng = random.Random(cfg.seed)
    with sqlite3.connect(db_path) as conn:
        init_physarum_tables(conn)
        nodes = _load_nodes(conn)
        graph, edges = _load_graph(conn, nodes, cfg)
        terminals = choose_terminals(nodes, graph, cfg.terminals, rng)

        conductivity = {edge_id: 0.0 for edge_id in edges}
        flow_count = {edge_id: 0 for edge_id in edges}

        for _ in range(cfg.iterations):
            for edge_id in conductivity:
                conductivity[edge_id] *= cfg.decay
            if len(terminals) < 2:
                continue
            for _ in range(cfg.paths_per_iteration):
                start, goal = rng.sample(terminals, 2)
                path = shortest_path_edges(graph, start, goal)
                if not path:
                    continue
                boost = cfg.reinforcement / max(1.0, math.sqrt(len(path)))
                for edge_id in path:
                    conductivity[edge_id] += boost
                    flow_count[edge_id] += 1

        active_edges = [
            edge_id for edge_id, value in conductivity.items()
            if value > 0 and flow_count.get(edge_id, 0) > 0
        ]
        run_id = stable_id("physarum_run", f"{now_iso()}:{cfg.seed}:{len(edges)}")
        summary = {
            "nodes": len(nodes),
            "edges": len(edges),
            "terminals": len(terminals),
            "reinforced_edges": len(active_edges),
            "top_edges": [
                edge_to_record(edge_id, conductivity[edge_id], flow_count[edge_id], edges, nodes)
                for edge_id in sorted(active_edges, key=lambda item: conductivity[item], reverse=True)[:20]
            ],
        }
        conn.execute(
            "INSERT INTO physarum_runs(id,created_at,config_json,summary_json) VALUES(?,?,?,?)",
            (run_id, now_iso(), json.dumps(asdict(cfg), ensure_ascii=False, sort_keys=True), json.dumps(summary, ensure_ascii=False, sort_keys=True)),
        )
        conn.executemany(
            "INSERT INTO physarum_edges(run_id,edge_id,conductivity,flow_count) VALUES(?,?,?,?)",
            [(run_id, edge_id, conductivity[edge_id], flow_count[edge_id]) for edge_id in active_edges],
        )
        conn.commit()
    return {"run_id": run_id, **summary}


def edge_to_record(edge_id: str, conductivity: float, flow_count: int, edges: dict[str, dict], nodes: dict[str, dict]) -> dict:
    edge = edges[edge_id]
    src = nodes.get(edge["src_id"], {})
    dst = nodes.get(edge["dst_id"], {})
    return {
        "edge_id": edge_id,
        "conductivity": round(conductivity, 4),
        "flow_count": flow_count,
        "relation": edge["relation"],
        "status": edge["status"],
        "src": {"type": src.get("type"), "name": src.get("name"), "source_path": src.get("source_path")},
        "dst": {"type": dst.get("type"), "name": dst.get("name"), "source_path": dst.get("source_path")},
        "source_path": edge.get("source_path"),
        "evidence_text": edge.get("evidence_text"),
    }


def top_physarum_edges(db_path: Path, run_id: str, limit: int = 20) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        nodes = _load_nodes(conn)
        _graph, edges = _load_graph(conn, nodes, PhysarumRunConfig())
        try:
            rows = conn.execute(
                """
                SELECT edge_id,conductivity,flow_count
                FROM physarum_edges
                WHERE run_id=?
                ORDER BY conductivity DESC, flow_count DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            return []
        return [edge_to_record(edge_id, conductivity, flow_count, edges, nodes) for edge_id, conductivity, flow_count in rows if edge_id in edges]
