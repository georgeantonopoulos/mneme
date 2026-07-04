import sqlite3
from pathlib import Path

from mneme.core import clear_graph_for_rebuild, init_db
from mneme.world_model.schema import ensure_world_model_schema


def test_ensure_world_model_schema_is_idempotent(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)

    ensure_world_model_schema(conn)
    ensure_world_model_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'world_%'"
        ).fetchall()
    }
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_w%'"
        ).fetchall()
    }
    assertion_columns = {row[1]: row[2].upper() for row in conn.execute("PRAGMA table_info(world_state_assertions)")}
    conn.close()

    assert tables == {"world_state_assertions", "world_predictions", "world_actions"}
    assert {"idx_wsa_subject", "idx_wsa_status", "idx_wsa_source", "idx_wp_due", "idx_wa_actor"} <= indexes
    assert "BOOLEAN" not in set(assertion_columns.values())
    assert assertion_columns["subject_name"] == "TEXT"
    assert assertion_columns["confidence"] == "REAL"


def test_rebuild_clear_does_not_delete_world_model_rows(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_world_model_schema(conn)
    conn.execute(
        """
        INSERT INTO world_state_assertions(
          id, subject_name, subject_type, predicate, object_name, object_value,
          state_type, status, confidence, certainty, evidence_text, source_path,
          source_type, created_at, updated_at
        ) VALUES('assertion-1','Fictional Permit','entity','due_on',NULL,'2026-09-01',
          'belief','current',0.95,'confirmed','A fictional notice confirmed the date.','Sources/permit.md',
          'research','2026-07-01T00:00:00+00:00','2026-07-01T00:00:00+00:00')
        """
    )
    conn.commit()

    clear_graph_for_rebuild(conn)
    remaining = conn.execute("SELECT count(*) FROM world_state_assertions").fetchone()[0]
    conn.close()

    assert remaining == 1
