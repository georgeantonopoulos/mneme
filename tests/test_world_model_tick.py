import sqlite3
from pathlib import Path

from mneme.core import ingest_sense_events
from mneme.senses.base import SenseEvent
from mneme.world_model import add_prediction, world_tick


def test_world_tick_checks_due_predictions(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(
        conn,
        [
            SenseEvent(
                id="evt-1",
                sense_id="fictional",
                sense_type="fictional_tasks",
                source_id="task:evt-1",
                source_uri="fictional://tasks/evt-1",
                observed_at="2026-07-02T10:00:00+00:00",
                title="Harbor permit",
                text="- Need harbor permit confirmation from records desk",
                event_type="task",
            )
        ],
    )
    add_prediction(
        conn,
        {
            "id": "pred-tick",
            "title": "Harbor permit should appear",
            "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["harbor", "permit"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-03T00:00:00+00:00",
        },
    )
    conn.commit()
    conn.close()

    result = world_tick(db, before="2026-07-02T12:00:00+00:00")

    assert result["ok"] is True
    assert result["graph"]["candidates_updated"] >= 1
    assert result["predictions"]["checked"] == 1
    assert result["predictions"]["results"][0]["status"] == "confirmed"

    conn = sqlite3.connect(db)
    candidate_count = conn.execute("SELECT COUNT(*) FROM thought_candidates").fetchone()[0]
    conn.close()
    assert candidate_count >= 1


def test_world_tick_dry_run_reports_prediction_dry_run(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(
        conn,
        [
            SenseEvent(
                id="evt-dry",
                sense_id="fictional",
                sense_type="fictional_tasks",
                source_id="task:evt-dry",
                source_uri="fictional://tasks/evt-dry",
                observed_at="2026-07-02T10:00:00+00:00",
                title="Dry run permit",
                text="- Need dry run permit confirmation from records desk",
                event_type="task",
            )
        ],
    )
    add_prediction(
        conn,
        {
            "id": "pred-dry-tick",
            "title": "Dry run permit should appear",
            "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["dry", "permit"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-03T00:00:00+00:00",
        },
    )
    conn.commit()
    conn.close()

    result = world_tick(db, before="2026-07-02T12:00:00+00:00", dry_run=True)

    assert result["dry_run"] is True
    assert result["predictions"]["dry_run"] is True
    assert result["predictions"]["results"][0]["dry_run"] is True
    conn = sqlite3.connect(db)
    status = conn.execute("SELECT status FROM world_predictions WHERE id='pred-dry-tick'").fetchone()[0]
    conn.close()
    assert status == "open"
