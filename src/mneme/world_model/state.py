from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from typing import Any

from mneme.contract import enforce_assertion_write
from mneme.world_model.schema import ensure_world_model_schema


ENTITY_OBJECT_TYPES = {"entity", "person", "project", "place", "event", "organization", "note", "wikilink"}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def assertion_id(subject_name: str, predicate: str, object_name: str | None, object_value: str | None, source_path: str) -> str:
    obj = object_name if object_name is not None else object_value
    key = f"wsa:{_norm(subject_name)}:{predicate}:{_norm(str(obj or ''))}:{source_path}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _object_fields(assertion: dict[str, Any]) -> tuple[str | None, str | None]:
    if assertion.get("object_name") is not None and assertion.get("object_value") is not None:
        raise ValueError("assertion requires exactly one of object_name or object_value")
    if assertion.get("object_name") is not None:
        return str(assertion["object_name"]).strip(), None
    if assertion.get("object_value") is not None:
        return None, str(assertion["object_value"]).strip()
    obj = str(assertion.get("object") or "").strip()
    if not obj:
        raise ValueError("assertion requires object, object_name, or object_value")
    object_type = str(assertion.get("object_type") or "").strip().lower()
    if object_type in ENTITY_OBJECT_TYPES:
        return obj, None
    return None, obj


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_explicit_reassertion(certainty: str | None, source_type: str, metadata: dict[str, Any]) -> bool:
    return (
        str(certainty or "").lower() == "user_confirmed"
        or source_type in {"user_confirmation", "user_correction"}
        or bool(metadata.get("user_confirmed") or metadata.get("explicit_reassertion"))
    )


def _replacement_status(source_type: str, metadata: dict[str, Any]) -> str:
    correction_type = str(metadata.get("correction_type") or metadata.get("replacement_type") or "").lower()
    if correction_type in {"contradiction", "contradicted", "correction", "false_previous"}:
        return "contradicted"
    if source_type in {"user_correction", "correction"}:
        return "contradicted"
    return "superseded"


def _same_object(row: sqlite3.Row, object_name: str | None, object_value: str | None) -> bool:
    return (row["object_name"] or "") == (object_name or "") and (row["object_value"] or "") == (object_value or "")


def recompute_current(conn: sqlite3.Connection, subject_name: str, predicate: str) -> str | None:
    ensure_world_model_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM world_state_assertions
        WHERE lower(subject_name)=lower(?) AND predicate=? AND status IN ('current','superseded')
        ORDER BY COALESCE(valid_from, created_at), created_at, id
        """,
        (subject_name, predicate),
    ).fetchall()
    if not rows:
        return None
    current = rows[-1]
    now = _now_iso()
    for row in rows[:-1]:
        conn.execute(
            """
            UPDATE world_state_assertions
            SET status='superseded', superseded_by_id=?, updated_at=?
            WHERE id=? AND status != 'killed'
            """,
            (current["id"], now, row["id"]),
        )
    supersedes_id = rows[-2]["id"] if len(rows) > 1 else current["supersedes_id"]
    conn.execute(
        """
        UPDATE world_state_assertions
        SET status='current', supersedes_id=?, superseded_by_id=NULL, updated_at=?
        WHERE id=?
        """,
        (supersedes_id, now, current["id"]),
    )
    return current["id"]


def upsert_assertion(
    conn: sqlite3.Connection,
    assertion: dict[str, Any],
    *,
    source_path: str,
    source_edge_id: str | None = None,
    subject_node_id: str | None = None,
    valid_from: str | None = None,
    active: bool = True,
) -> dict[str, Any]:
    """Write a durable state assertion after the existing claim gate approves it."""

    ensure_world_model_schema(conn)
    conn.row_factory = sqlite3.Row
    subject_name = str(assertion.get("subject") or assertion.get("subject_name") or "").strip()
    if not subject_name:
        raise ValueError("assertion requires subject")
    predicate = str(assertion.get("predicate") or assertion.get("relation") or "related_to").strip()
    object_name, object_value = _object_fields(assertion)
    confidence = float(assertion.get("confidence") or 0.0)
    certainty = str(assertion.get("certainty") or "").strip() or None
    evidence = str(assertion.get("evidence") or assertion.get("evidence_text") or "").strip()
    source_type = str(assertion.get("source_type") or "research")
    metadata = dict(assertion.get("metadata") or {})
    state_type = str(assertion.get("state_type") or "belief")
    valid_from = str(assertion.get("valid_from") or valid_from or "").strip() or None
    valid_until = str(assertion.get("valid_until") or assertion.get("due") or "").strip() or None
    requested_status = "current" if active else "candidate"
    decision = enforce_assertion_write(
        predicate=predicate,
        requested_status=requested_status,
        evidence_text=evidence,
        confidence=confidence,
        certainty=certainty,
        source_type=source_type,
        metadata=metadata,
    )
    if decision.blocked or decision.status != "current":
        return {"id": None, "status": decision.status, "blocked": True, "reasons": decision.reasons}

    row_id = assertion_id(subject_name, predicate, object_name, object_value, source_path)
    existing = conn.execute("SELECT * FROM world_state_assertions WHERE id=?", (row_id,)).fetchone()
    if existing and existing["status"] in {"killed", "contradicted"} and not _is_explicit_reassertion(certainty, source_type, metadata):
        return {"id": row_id, "status": existing["status"], "blocked": True, "reasons": ["blocked_recreation"]}

    replacement_status = _replacement_status(source_type, metadata)
    prior = conn.execute(
        """
        SELECT * FROM world_state_assertions
        WHERE lower(subject_name)=lower(?) AND predicate=? AND status='current' AND id != ?
        ORDER BY COALESCE(valid_from, created_at), created_at, id
        """,
        (subject_name, predicate, row_id),
    ).fetchall()
    supersedes_id = None
    now = _now_iso()
    for old in prior:
        if not _same_object(old, object_name, object_value):
            supersedes_id = old["id"]
            conn.execute(
                """
                UPDATE world_state_assertions
                SET status=?, superseded_by_id=?, updated_at=?
                WHERE id=?
                """,
                (replacement_status, row_id, now, old["id"]),
            )

    metadata["contract"] = decision.contract_payload
    values = (
        row_id,
        subject_name,
        str(assertion.get("subject_type") or "entity"),
        predicate,
        object_name,
        object_value,
        state_type,
        "current",
        confidence,
        certainty,
        evidence[:500],
        source_path,
        source_type,
        subject_node_id or assertion.get("subject_node_id"),
        source_edge_id or assertion.get("source_edge_id"),
        valid_from,
        valid_until,
        supersedes_id,
        _json(metadata),
        now,
        now,
    )
    conn.execute(
        """
        INSERT INTO world_state_assertions(
          id, subject_name, subject_type, predicate, object_name, object_value,
          state_type, status, confidence, certainty, evidence_text, source_path,
          source_type, subject_node_id, source_edge_id, valid_from, valid_until,
          supersedes_id, metadata_json, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          subject_name=excluded.subject_name,
          subject_type=excluded.subject_type,
          predicate=excluded.predicate,
          object_name=excluded.object_name,
          object_value=excluded.object_value,
          state_type=excluded.state_type,
          status=CASE
            WHEN world_state_assertions.status='killed' AND excluded.certainty != 'user_confirmed' THEN world_state_assertions.status
            WHEN world_state_assertions.status='contradicted' AND excluded.certainty != 'user_confirmed' THEN world_state_assertions.status
            ELSE excluded.status
          END,
          confidence=max(world_state_assertions.confidence, excluded.confidence),
          certainty=excluded.certainty,
          evidence_text=excluded.evidence_text,
          source_type=excluded.source_type,
          subject_node_id=COALESCE(excluded.subject_node_id, world_state_assertions.subject_node_id),
          source_edge_id=COALESCE(excluded.source_edge_id, world_state_assertions.source_edge_id),
          valid_from=COALESCE(excluded.valid_from, world_state_assertions.valid_from),
          valid_until=COALESCE(excluded.valid_until, world_state_assertions.valid_until),
          supersedes_id=COALESCE(excluded.supersedes_id, world_state_assertions.supersedes_id),
          metadata_json=excluded.metadata_json,
          updated_at=excluded.updated_at
        """,
        values,
    )
    current_id = recompute_current(conn, subject_name, predicate)
    row = conn.execute("SELECT status FROM world_state_assertions WHERE id=?", (row_id,)).fetchone()
    return {"id": row_id, "status": row["status"], "current_id": current_id, "blocked": False, "reasons": decision.reasons}


def write_assertions(
    conn: sqlite3.Connection,
    assertions: list[dict[str, Any]],
    *,
    source_path: str,
    valid_from: str | None = None,
    active_status_fn: Any | None = None,
    edge_hints: dict[int, dict[str, str | None]] | None = None,
) -> list[dict[str, Any]]:
    written = []
    for index, assertion in enumerate(assertions):
        active = True
        if active_status_fn is not None:
            active = active_status_fn(assertion) == "active"
        if not active:
            written.append({"id": None, "status": "candidate", "blocked": True, "reasons": ["claim_not_active"]})
            continue
        hints = (edge_hints or {}).get(index, {})
        written.append(
            upsert_assertion(
                conn,
                assertion,
                source_path=source_path,
                source_edge_id=hints.get("source_edge_id"),
                subject_node_id=hints.get("subject_node_id"),
                valid_from=valid_from,
                active=True,
            )
        )
    return written
