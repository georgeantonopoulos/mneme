"""Regression tests for Codex PR #7 review fixes.

1. world_tick --dry-run must not leave temp DB copies on disk.
2. predict check --dry-run must not create world-model tables on a graph-only DB.
"""
import sqlite3
import tempfile
from pathlib import Path

from mneme.core import ingest_sense_events, init_db
from mneme.senses.base import SenseEvent
from mneme.world_model import add_prediction, world_tick
from mneme.world_model.predictions import check_prediction, check_due_predictions


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