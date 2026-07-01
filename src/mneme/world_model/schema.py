from __future__ import annotations

import sqlite3


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
