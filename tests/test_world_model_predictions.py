import json
import sqlite3
from pathlib import Path

import pytest

from mneme.cli import main
from mneme.core import ingest_sense_events, init_db
from mneme.senses.base import SenseEvent
from mneme.world_model.predictions import add_prediction, check_prediction, due_predictions


def _event(event_id: str, *, title: str, text: str, observed_at: str = "2026-07-02T10:00:00+00:00") -> SenseEvent:
    return SenseEvent(
        id=event_id,
        sense_id="fictional",
        sense_type="fictional_tasks",
        source_id=f"task:{event_id}",
        source_uri=f"fictional://tasks/{event_id}",
        observed_at=observed_at,
        title=title,
        text=text,
        event_type="task",
        metadata={"path": f"Fictional/{event_id}.md"},
    )


def test_add_due_and_confirm_prediction_from_observation_terms(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(
        conn,
        [
            _event(
                "evt-1",
                title="Orchid permit",
                text="- Need orchid permit confirmation from city desk by Friday",
            )
        ],
    )
    payload = {
        "id": "pred-1",
        "title": "Orchid permit should appear",
        "match_json": {
            "sense_type": "fictional_tasks",
            "title_terms_all": ["orchid"],
            "observation_terms_all": ["permit", "confirmation"],
            "observed_after": "2026-07-02T00:00:00+00:00",
            "observed_before": "2026-07-03T00:00:00+00:00",
        },
        "check_after": "2026-07-02T00:00:00+00:00",
        "expires_at": "2026-07-03T00:00:00+00:00",
        "confidence": 0.8,
    }

    added = add_prediction(conn, payload)
    due = due_predictions(conn, before="2026-07-02T12:00:00+00:00")
    checked = check_prediction(conn, "pred-1", now="2026-07-02T12:00:00+00:00")

    assert added["status"] == "open"
    assert [item["id"] for item in due] == ["pred-1"]
    assert checked["status"] == "confirmed"
    assert checked["outcome_sense_event_id"] == "evt-1"
    assert checked["matches"][0]["overlap"]


def test_expired_prediction_is_missed_when_sense_type_has_events(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(conn, [_event("evt-1", title="Unrelated", text="- Need unrelated archive review")])
    add_prediction(
        conn,
        {
            "id": "pred-missed",
            "title": "Comet invoice should appear",
            "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["comet", "invoice"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-02T00:00:00+00:00",
        },
    )

    result = check_prediction(conn, "pred-missed", now="2026-07-03T00:00:00+00:00")

    assert result["status"] == "missed"
    assert result["outcome_sense_event_id"] is None


def test_expired_prediction_is_unverifiable_without_sense_events(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    add_prediction(
        conn,
        {
            "id": "pred-unverifiable",
            "title": "Fictional sensor should report",
            "match_json": {"sense_type": "missing_sensor", "title_terms_any": ["signal"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-02T00:00:00+00:00",
        },
    )

    result = check_prediction(conn, "pred-unverifiable", now="2026-07-03T00:00:00+00:00")

    assert result["status"] == "unverifiable"
    assert "missing_sensor" in result["outcome_summary"]


def test_no_news_expected_confirms_when_window_expires_quietly(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    ingest_sense_events(conn, [_event("evt-1", title="Routine digest", text="- Need routine archive review")])
    add_prediction(
        conn,
        {
            "id": "pred-no-news",
            "title": "No comet escalation expected",
            "prediction_type": "no_news_expected",
            "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["comet", "escalation"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-02T00:00:00+00:00",
        },
    )

    result = check_prediction(conn, "pred-no-news", now="2026-07-03T00:00:00+00:00")

    assert result["status"] == "confirmed"


def test_rejects_uncheckable_match_json(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")

    with pytest.raises(ValueError, match="source_id or at least one terms field"):
        add_prediction(
            conn,
            {
                "title": "Bad prediction",
                "match_json": {"sense_type": "fictional_tasks"},
                "check_after": "2026-07-01T00:00:00+00:00",
                "expires_at": "2026-07-02T00:00:00+00:00",
            },
        )


def test_due_predictions_does_not_create_world_model_schema_for_empty_db(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.commit()
    conn.close()

    assert due_predictions(db, before="2026-07-02T12:00:00+00:00") == []

    conn = sqlite3.connect(db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'world_%'"
        )
    }
    conn.close()
    assert tables == set()


def test_cli_predict_add_due_and_check(tmp_path: Path, capsys):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(conn, [_event("evt-1", title="Silver receipt", text="- Need silver receipt confirmation")])
    conn.commit()
    conn.close()
    payload = tmp_path / "prediction.json"
    payload.write_text(
        json.dumps(
            {
                "id": "pred-cli",
                "title": "Silver receipt should appear",
                "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["silver", "receipt"]},
                "check_after": "2026-07-01T00:00:00+00:00",
                "expires_at": "2026-07-03T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    main(["predict", "add", "--db", str(db), "--file", str(payload)])
    assert json.loads(capsys.readouterr().out)["id"] == "pred-cli"

    main(["predict", "due", "--db", str(db), "--before", "2026-07-02T00:00:00+00:00"])
    assert json.loads(capsys.readouterr().out)[0]["id"] == "pred-cli"

    main(["predict", "check", "--db", str(db), "--id", "pred-cli"])
    assert json.loads(capsys.readouterr().out)["status"] == "confirmed"
