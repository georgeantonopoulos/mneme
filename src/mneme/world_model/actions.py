from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from mneme.contract import validate_agent_action
from mneme.world_model.schema import ensure_world_model_schema


def record_action(conn_or_path: sqlite3.Connection | Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        from mneme.core import init_db

        init_db(conn)
        ensure_world_model_schema(conn)
        report = validate_agent_action(payload, {})
        if not report.ok:
            raise ValueError("; ".join(report.failures))
        action_id = str(payload.get("id") or uuid.uuid4().hex)
        created_at = str(payload.get("created_at") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        metadata = payload.get("metadata_json", payload.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must be an object")
        conn.execute(
            """INSERT INTO world_actions(
                 id,actor,action_type,title,tool_name,tool_call_id,side_effect_level,reversibility,
                 external_ref,status,assertion_ids_json,prediction_id,source_path,metadata_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 actor=excluded.actor, action_type=excluded.action_type, title=excluded.title,
                 tool_name=excluded.tool_name, tool_call_id=excluded.tool_call_id,
                 side_effect_level=excluded.side_effect_level, reversibility=excluded.reversibility,
                 external_ref=excluded.external_ref, status=excluded.status,
                 assertion_ids_json=excluded.assertion_ids_json, prediction_id=excluded.prediction_id,
                 source_path=excluded.source_path, metadata_json=excluded.metadata_json
            """,
            (
                action_id,
                str(payload.get("actor") or "mneme"),
                str(payload.get("action_type") or "unknown"),
                str(payload.get("title") or "Untitled action"),
                payload.get("tool_name"),
                payload.get("tool_call_id"),
                str(payload.get("side_effect_level") or "none"),
                str(payload.get("reversibility") or "unknown"),
                payload.get("external_ref"),
                str(payload.get("status") or "recorded"),
                json.dumps(payload.get("assertion_ids") or payload.get("assertion_ids_json") or [], ensure_ascii=False),
                payload.get("prediction_id"),
                payload.get("source_path"),
                json.dumps(metadata, sort_keys=True, ensure_ascii=False),
                created_at,
            ),
        )
        if close:
            conn.commit()
        row = conn.execute("SELECT * FROM world_actions WHERE id=?", (action_id,)).fetchone()
        result = dict(row)
        result["metadata_json"] = json.loads(result.get("metadata_json") or "{}")
        result["assertion_ids_json"] = json.loads(result.get("assertion_ids_json") or "[]")
        return result
    finally:
        if close:
            conn.close()
