from __future__ import annotations

import sqlite3

WORLD_MODEL_TABLES = (
    "world_state_assertions",
    "world_predictions",
    "world_actions",
)


def ensure_world_model_schema(conn: sqlite3.Connection) -> None:
    """Create durable world-model tables.

    These tables intentionally live outside ``init_db()``. Graph rows are a
    rebuildable cache; world-model rows are durable state created only by
    world-model writers. Graph ID columns are best-effort hints; denormalized
    text columns carry the durable meaning across rebuilds.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS world_state_assertions(
          id TEXT PRIMARY KEY,
          subject_name TEXT NOT NULL,
          subject_type TEXT NOT NULL DEFAULT 'entity',
          predicate TEXT NOT NULL,
          object_name TEXT,
          object_value TEXT,
          state_type TEXT NOT NULL DEFAULT 'belief',
          status TEXT NOT NULL DEFAULT 'current',
          confidence REAL NOT NULL DEFAULT 0.5,
          certainty TEXT,
          evidence_text TEXT NOT NULL,
          source_path TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT 'research',
          subject_node_id TEXT,
          source_edge_id TEXT,
          valid_from TEXT,
          valid_until TEXT,
          supersedes_id TEXT,
          superseded_by_id TEXT,
          metadata_json TEXT DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          CHECK ((object_name IS NOT NULL AND object_value IS NULL) OR (object_name IS NULL AND object_value IS NOT NULL))
        );
        CREATE INDEX IF NOT EXISTS idx_wsa_subject ON world_state_assertions(subject_name, predicate, status);
        CREATE INDEX IF NOT EXISTS idx_wsa_status ON world_state_assertions(status, state_type);
        CREATE INDEX IF NOT EXISTS idx_wsa_source ON world_state_assertions(source_path);
        CREATE INDEX IF NOT EXISTS idx_wsa_subject_current ON world_state_assertions(subject_name, predicate)
          WHERE status='current';

        CREATE TABLE IF NOT EXISTS world_predictions(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          prediction_type TEXT NOT NULL DEFAULT 'confirmation_expected',
          subject_assertion_id TEXT,
          source_action_id TEXT,
          match_json TEXT NOT NULL,
          check_after TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          confidence REAL NOT NULL DEFAULT 0.5,
          status TEXT NOT NULL DEFAULT 'open',
          outcome_sense_event_id TEXT,
          outcome_summary TEXT,
          checked_at TEXT,
          metadata_json TEXT DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wp_due ON world_predictions(status, check_after);
        CREATE INDEX IF NOT EXISTS idx_wp_assertion ON world_predictions(subject_assertion_id);

        CREATE TABLE IF NOT EXISTS world_actions(
          id TEXT PRIMARY KEY,
          actor TEXT NOT NULL,
          action_type TEXT NOT NULL,
          title TEXT NOT NULL,
          tool_name TEXT,
          tool_call_id TEXT,
          side_effect_level TEXT NOT NULL DEFAULT 'none',
          reversibility TEXT NOT NULL DEFAULT 'unknown',
          external_ref TEXT,
          status TEXT NOT NULL DEFAULT 'recorded',
          assertion_ids_json TEXT DEFAULT '[]',
          prediction_id TEXT,
          source_path TEXT,
          metadata_json TEXT DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wa_actor ON world_actions(actor, created_at);
        CREATE INDEX IF NOT EXISTS idx_wa_source ON world_actions(source_path);
        """
    )


def _existing_world_model_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?)",
        WORLD_MODEL_TABLES,
    ).fetchall()
    return {str(row[0]) for row in rows}


def delete_world_model_source(conn: sqlite3.Connection, source_path: str, *, dry_run: bool = False) -> dict[str, int]:
    """Cascade an explicit mneme:// source forget into durable world-model rows.

    This is intentionally a no-op until the schema exists, so graph-only callers
    do not create world-model tables as a side effect.
    """

    existing = _existing_world_model_tables(conn)
    counts = {table: 0 for table in WORLD_MODEL_TABLES}
    if "world_predictions" in existing:
        prediction_clauses = []
        prediction_params = []
        if "world_state_assertions" in existing:
            prediction_clauses.append(
                "subject_assertion_id IN (SELECT id FROM world_state_assertions WHERE source_path=?)"
            )
            prediction_params.append(source_path)
        if "world_actions" in existing:
            prediction_clauses.append(
                "source_action_id IN (SELECT id FROM world_actions WHERE source_path=?)"
            )
            prediction_params.append(source_path)
        prediction_where = " OR ".join(prediction_clauses)
        if prediction_where:
            counts["world_predictions"] = conn.execute(
                "SELECT COUNT(*) FROM world_predictions WHERE " + prediction_where,
                prediction_params,
            ).fetchone()[0]
        if prediction_where and not dry_run:
            conn.execute("DELETE FROM world_predictions WHERE " + prediction_where, prediction_params)
    if "world_state_assertions" in existing:
        counts["world_state_assertions"] = conn.execute(
            "SELECT COUNT(*) FROM world_state_assertions WHERE source_path=?",
            (source_path,),
        ).fetchone()[0]
        if not dry_run:
            conn.execute("DELETE FROM world_state_assertions WHERE source_path=?", (source_path,))
    if "world_actions" in existing:
        counts["world_actions"] = conn.execute(
            "SELECT COUNT(*) FROM world_actions WHERE source_path=?",
            (source_path,),
        ).fetchone()[0]
        if not dry_run:
            conn.execute("DELETE FROM world_actions WHERE source_path=?", (source_path,))
    return counts
