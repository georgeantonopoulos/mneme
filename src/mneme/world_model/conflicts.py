from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _object_value(row: sqlite3.Row | dict[str, Any], *, name_key: str, value_key: str) -> str:
    return str(row[name_key] or row[value_key] or "").strip()


def _is_exclusive(assertion: sqlite3.Row) -> bool:
    """Whether one subject/predicate may hold only one current object.

    Cardinality is explicit rather than guessed from predicate wording: relations
    such as ``paid`` or ``owns`` are naturally multi-valued and must not generate
    false contradictions merely because their objects differ.
    """

    try:
        metadata = json.loads(assertion["metadata_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    return metadata.get("conflict_policy") == "exclusive" or metadata.get("cardinality") in {"one", 1}


def detect_state_conflicts(conn_or_path: sqlite3.Connection | Path | str) -> list[dict[str, Any]]:
    """Return source-backed signals that disagree with durable current state.

    Conflicts are attention items, not automatic state transitions. This preserves
    the world model's evidence gate while ensuring newly perceived disagreement is
    visible instead of being silently suppressed by an older current assertion.
    """

    if not isinstance(conn_or_path, sqlite3.Connection) and not Path(conn_or_path).exists():
        return []
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "world_state_assertions" not in tables:
            return []

        assertions = conn.execute(
            """SELECT id,subject_name,predicate,object_name,object_value,confidence,
                      evidence_text,source_path,source_edge_id,metadata_json,updated_at
               FROM world_state_assertions
               WHERE status='current'
               ORDER BY lower(subject_name),predicate,id"""
        ).fetchall()
        conflicts: list[dict[str, Any]] = []

        # A healthy state layer has one current value per canonical subject/predicate.
        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in assertions:
            grouped.setdefault((_norm(row["subject_name"]), row["predicate"]), []).append(row)
        for rows in grouped.values():
            values = {_norm(_object_value(row, name_key="object_name", value_key="object_value")) for row in rows}
            if len(values) > 1:
                conflicts.append(
                    {
                        "kind": "world_state_collision",
                        "severity": "high",
                        "subject": rows[0]["subject_name"],
                        "predicate": rows[0]["predicate"],
                        "assertion_ids": [row["id"] for row in rows],
                        "values": [_object_value(row, name_key="object_name", value_key="object_value") for row in rows],
                        "summary": "multiple current world-state values disagree",
                    }
                )

        if not {"edges", "nodes"} <= tables:
            return conflicts

        # Evidence already represented by a superseded/contradicted assertion is
        # historical context, not a fresh challenge to the current value.
        historical_edge_ids = {
            row["source_edge_id"]
            for row in conn.execute(
                """SELECT source_edge_id FROM world_state_assertions
                   WHERE status IN ('superseded','contradicted','killed')
                     AND source_edge_id IS NOT NULL"""
            ).fetchall()
        }

        for assertion in assertions:
            if not _is_exclusive(assertion):
                continue
            current_object = _object_value(assertion, name_key="object_name", value_key="object_value")
            if not current_object:
                continue
            rows = conn.execute(
                """SELECT e.id,e.status,e.relation,e.confidence,e.strength,e.evidence_text,
                          e.source_path,e.source_type,d.name AS object_name
                   FROM edges e
                   JOIN nodes s ON s.id=e.src_id
                   JOIN nodes d ON d.id=e.dst_id
                   WHERE lower(s.name)=lower(?) AND e.relation=?
                     AND e.status IN ('active','candidate')
                   ORDER BY CASE e.status WHEN 'active' THEN 0 ELSE 1 END,
                            e.confidence DESC,e.strength DESC,e.id""",
                (assertion["subject_name"], assertion["predicate"]),
            ).fetchall()
            for edge in rows:
                if edge["id"] in historical_edge_ids:
                    continue
                if assertion["source_edge_id"] and edge["id"] == assertion["source_edge_id"]:
                    continue
                if _norm(edge["object_name"]) == _norm(current_object):
                    continue
                conflicts.append(
                    {
                        "kind": "evidence_conflict",
                        "severity": "high" if edge["status"] == "active" else "review",
                        "subject": assertion["subject_name"],
                        "predicate": assertion["predicate"],
                        "current": {
                            "assertion_id": assertion["id"],
                            "object": current_object,
                            "confidence": float(assertion["confidence"] or 0),
                            "source_path": assertion["source_path"],
                            "evidence": assertion["evidence_text"],
                        },
                        "challenger": {
                            "edge_id": edge["id"],
                            "status": edge["status"],
                            "object": edge["object_name"],
                            "confidence": float(edge["confidence"] or 0),
                            "strength": float(edge["strength"] or 0),
                            "source_path": edge["source_path"],
                            "source_type": edge["source_type"],
                            "evidence": edge["evidence_text"],
                        },
                        "summary": f"new {edge['status']} evidence disagrees with current state",
                    }
                )
        return conflicts
    finally:
        if close:
            conn.close()
