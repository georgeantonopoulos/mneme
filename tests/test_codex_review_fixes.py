"""Regression tests for Codex PR #7 review fixes.

1. world_tick --dry-run must not leave temp DB copies on disk.
2. predict check --dry-run must not create world-model tables on a graph-only DB.
"""
import sqlite3
import tempfile
from pathlib import Path

from mneme.core import ingest_sense_events, init_db, remember_graph
from mneme.senses.base import SenseEvent
from mneme.world_model import add_prediction, ensure_world_model_schema, list_assertions, upsert_assertion, world_tick
from mneme.world_model.predictions import check_due_predictions, check_prediction, due_predictions
from mneme.world_model.schema import delete_world_model_source


def test_world_tick_dry_run_leaves_no_temp_files(tmp_path: Path):
    """world_tick(dry_run=True) must not leave SQLite artifacts on disk."""
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS sense_events (id TEXT PRIMARY KEY, sense_type TEXT)")
    conn.commit()
    conn.close()

    import os
    before_temps = set(f.name for f in Path(tempfile.gettempdir()).glob("mneme_world_tick_dryrun_*"))

    result = world_tick(db, dry_run=True)

    after_temps = set(f.name for f in Path(tempfile.gettempdir()).glob("mneme_world_tick_dryrun_*"))
    new_temps = after_temps - before_temps

    assert result["dry_run"] is True
    assert result["dry_run_db"] is None, f"dry_run_db should be None, got {result['dry_run_db']}"
    assert len(new_temps) == 0, f"Temp files left behind: {new_temps}"


def test_predict_check_dry_run_no_schema_on_graph_only_db(tmp_path: Path):
    """check_prediction(dry_run=True) must not create world_* tables on a graph-only DB."""
    db = tmp_path / "graph_only.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.commit()
    conn.close()

    # Verify no world-model tables exist yet
    conn = sqlite3.connect(db)
    tables_before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "world_predictions" not in tables_before
    assert "world_state_assertions" not in tables_before

    # Dry-run check on a non-existent prediction should not create schema
    try:
        check_prediction(db, "nonexistent-pred", dry_run=True)
    except (ValueError, sqlite3.OperationalError):
        pass  # expected — prediction doesn't exist

    # Verify no world-model tables were created
    conn = sqlite3.connect(db)
    tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "world_predictions" not in tables_after, f"world_predictions was created by dry-run: {tables_after}"
    assert "world_state_assertions" not in tables_after, f"world_state_assertions was created by dry-run: {tables_after}"


def test_check_due_predictions_dry_run_no_schema_on_graph_only_db(tmp_path: Path):
    """check_due_predictions(dry_run=True) must not create world_* tables on a graph-only DB."""
    db = tmp_path / "graph_only.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.commit()
    conn.close()

    # Verify no world-model tables exist
    conn = sqlite3.connect(db)
    tables_before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "world_predictions" not in tables_before

    # Dry-run due check should not create schema
    result = check_due_predictions(db, dry_run=True)
    assert result["dry_run"] is True

    # Verify no world-model tables were created
    conn = sqlite3.connect(db)
    tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "world_predictions" not in tables_after, f"world_predictions was created by dry-run: {tables_after}"


def test_remember_graph_dry_run_with_assertions_does_not_commit_graph_rows(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    payload = {
        "source_path": "mneme://test/dry-run-assertion",
        "nodes": [
            {"ref": "a", "name": "Dry Run Alpha"},
            {"ref": "b", "name": "Dry Run Beta"},
        ],
        "edges": [{"src": "a", "dst": "b", "relation": "supports", "confidence": 0.9}],
        "assertions": [
            {
                "subject": "Dry Run Alpha",
                "predicate": "supports",
                "object": "Dry Run Beta",
                "object_type": "entity",
                "confidence": 0.9,
                "certainty": "confirmed",
                "evidence": "Dry run evidence.",
            }
        ],
    }

    result = remember_graph(db, payload, dry_run=True)

    assert result["dry_run"] is True
    conn = sqlite3.connect(db)
    node_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE source_path=?", (payload["source_path"],)).fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges WHERE source_path=?", (payload["source_path"],)).fetchone()[0]
    world_tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'world_%'")
    }
    conn.close()
    assert node_count == 0
    assert edge_count == 0
    assert world_tables == set()


def test_list_assertions_is_read_only_and_can_limit_by_recent_update(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.commit()
    conn.close()

    assert list_assertions(db, status="current") == []
    conn = sqlite3.connect(db)
    assert {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'world_%'")
    } == set()
    ensure_world_model_schema(conn)
    for index in range(3):
        conn.execute(
            """
            INSERT INTO world_state_assertions(
              id, subject_name, predicate, object_value, evidence_text, source_path,
              confidence, certainty, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"wsa-{index}",
                f"Subject {index}",
                "has_status",
                f"value-{index}",
                "Evidence.",
                "mneme://test/list-order",
                0.9,
                "confirmed",
                f"2026-07-01T00:00:0{index}+00:00",
                f"2026-07-01T00:00:0{index}+00:00",
            ),
        )
    conn.commit()
    conn.close()

    recent = list_assertions(db, status="current", order_by="updated_at_desc", limit=2)

    assert [item["id"] for item in recent] == ["wsa-2", "wsa-1"]


def test_user_correction_reassertion_revives_contradicted_assertion(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    claim = {
        "subject": "Orchid permit",
        "predicate": "has_status",
        "object_value": "approved",
        "confidence": 0.95,
        "certainty": "confirmed",
        "evidence": "The permit was approved.",
    }
    first = upsert_assertion(conn, claim, source_path="mneme://test/reassert")
    conn.execute("UPDATE world_state_assertions SET status='contradicted' WHERE id=?", (first["id"],))

    revived = upsert_assertion(
        conn,
        {
            **claim,
            "certainty": "confirmed",
            "source_type": "user_correction",
            "metadata": {"correction_type": "correction"},
        },
        source_path="mneme://test/reassert",
    )

    assert revived["blocked"] is False
    assert revived["status"] == "current"
    conn.close()


def test_due_predictions_compares_offset_timestamps_as_datetimes(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    add_prediction(
        conn,
        {
            "id": "pred-offset-due",
            "title": "Offset timestamp should be due",
            "match_json": {"sense_type": "fictional_tasks", "title_terms_any": ["offset"]},
            "check_after": "2026-07-02T13:00:00+02:00",
            "expires_at": "2026-07-03T00:00:00+00:00",
        },
    )

    due = due_predictions(conn, before="2026-07-02T12:00:00+00:00")

    assert [item["id"] for item in due] == ["pred-offset-due"]
    conn.close()


def test_delete_world_model_source_cascades_predictions_from_source_actions(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_world_model_schema(conn)
    conn.execute(
        """
        INSERT INTO world_actions(id, actor, action_type, title, side_effect_level, source_path, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        ("action-1", "mneme", "email_sent", "Sent test email", "private_external", "mneme://test/action-source", "2026-07-01T00:00:00+00:00"),
    )
    conn.execute(
        """
        INSERT INTO world_predictions(
          id, title, source_action_id, match_json, check_after, expires_at, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            "pred-action-linked",
            "Action follow-up should appear",
            "action-1",
            "{}",
            "2026-07-02T00:00:00+00:00",
            "2026-07-03T00:00:00+00:00",
            "2026-07-01T00:00:00+00:00",
            "2026-07-01T00:00:00+00:00",
        ),
    )

    removed = delete_world_model_source(conn, "mneme://test/action-source")

    assert removed["world_predictions"] == 1
    assert removed["world_actions"] == 1
    assert conn.execute("SELECT COUNT(*) FROM world_predictions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM world_actions").fetchone()[0] == 0
    conn.close()
