from __future__ import annotations

import sqlite3


def ensure_world_model_schema(conn: sqlite3.Connection) -> None:
    """Create durable world-model prediction tables.

    These tables intentionally live outside ``init_db()``. Graph rows are a
    rebuildable cache; prediction rows are durable state created only by
    world-model writers.
    """

    conn.executescript(
        """
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
        """
    )

