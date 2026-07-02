from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from .predictions import check_due_predictions, parse_before


def _lapsed_open_loops(db_path: Path, *, before: str | None = None) -> list[dict]:
    if not db_path.exists():
        return []
    before_iso = parse_before(before)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_state_assertions'").fetchone()
        if exists is None:
            return []
        rows = conn.execute(
            """SELECT id,subject_name,predicate,object_name,object_value,valid_until,evidence_text,source_path
               FROM world_state_assertions
               WHERE status='current' AND state_type='open_loop' AND valid_until IS NOT NULL AND valid_until < ?
               ORDER BY valid_until,id""",
            (before_iso,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _dry_run_copy(db_path: Path) -> Path:
    tmp = tempfile.NamedTemporaryFile(prefix="mneme_world_tick_dryrun_", suffix=".sqlite", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    if db_path.exists():
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    return tmp_path


def world_tick(db_path: Path, *, before: str | None = None, dry_run: bool = False) -> dict:
    """Run graph tick plus deterministic world-model maintenance.

    Dry-run runs every mutating component against a SQLite backup under /tmp,
    so graph candidate generation and prediction status transitions are previewed
    without touching the caller's database.
    """

    from mneme.contract import check_db_contract
    from mneme.core import tick

    work_db = _dry_run_copy(db_path) if dry_run else db_path
    graph_report = tick(work_db)
    prediction_report = check_due_predictions(work_db, before=before, dry_run=False)
    lapsed = _lapsed_open_loops(work_db, before=before)
    contract = check_db_contract(work_db).to_dict()
    attention = []
    for item in prediction_report.get("results", []):
        if item.get("status") in {"missed", "unverifiable"}:
            attention.append({"kind": "prediction", "id": item.get("id"), "status": item.get("status"), "summary": item.get("outcome_summary")})
    for item in lapsed:
        attention.append({"kind": "lapsed_open_loop", "id": item.get("id"), "subject": item.get("subject_name"), "valid_until": item.get("valid_until")})
    return {
        "ok": contract.get("status") != "fail",
        "dry_run": dry_run,
        "graph": graph_report,
        "predictions": prediction_report,
        "lapsed_open_loops": lapsed,
        "contradictions": [],
        "contract": contract,
        "attention": attention,
        "dry_run_db": str(work_db) if dry_run else None,
    }
