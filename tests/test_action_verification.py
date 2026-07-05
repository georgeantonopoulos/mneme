from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from mneme.core import init_db
from mneme.world_model.actions import record_action
from mneme.world_model.predictions import add_prediction, now_iso, prediction_watch
from mneme.world_model.schema import ensure_world_model_schema
from mneme.world_model.loop import world_tick


def _iso(offset_hours: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=offset_hours)).isoformat(timespec="seconds")


def _base_action(**over):
    payload = {
        "id": "act-1",
        "actor": "mneme",
        "action_type": "email_sent",
        "title": "Emailed school finance office about invoice",
        "side_effect_level": "external",
        "tool_call_id": "tool-123",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    payload.update(over)
    return payload


def test_action_without_verify_spawns_nothing(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    result = record_action(db, _base_action())
    assert "spawned_prediction_id" not in result
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM world_predictions").fetchone()[0] == 0


def test_verify_block_spawns_and_links(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    result = record_action(
        db,
        _base_action(verify={"sense_type": "email", "check_after": "1d", "expires": "3d", "terms": ["invoice", "finance"]}),
    )
    pred_id = result["spawned_prediction_id"]
    assert pred_id
    assert result["prediction_id"] == pred_id  # linked back onto the action row
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM world_predictions WHERE id=?", (pred_id,)).fetchone()
    assert row["source_action_id"] == "act-1"
    # Window anchored on the action created_at, not wall-clock.
    assert row["check_after"] == "2026-01-02T00:00:00+00:00"
    assert row["expires_at"] == "2026-01-04T00:00:00+00:00"


def test_verify_is_idempotent_on_replay(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    action = _base_action(verify={"sense_type": "email", "terms": ["invoice"]})
    first = record_action(db, action)["spawned_prediction_id"]
    second = record_action(db, action)["spawned_prediction_id"]
    assert first == second
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM world_predictions").fetchone()[0] == 1


def test_no_side_effect_does_not_spawn(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    result = record_action(
        db,
        _base_action(side_effect_level="none", tool_call_id=None, verify={"sense_type": "email", "terms": ["x"]}),
    )
    assert "spawned_prediction_id" not in result


def test_prediction_watch_flags_pending_without_evidence(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    add_prediction(
        db,
        {
            "id": "p1",
            "title": "Verify reply from finance",
            "prediction_type": "confirmation_expected",
            "match_json": {"sense_type": "email", "observation_terms_any": ["invoice"]},
            "check_after": _iso(-1),   # already due
            "expires_at": _iso(48),    # not yet expired
            "confidence": 0.6,
        },
    )
    watched = prediction_watch(db, lead="1d")
    assert [w["id"] for w in watched] == ["p1"]
    assert "no email evidence yet" in watched[0]["summary"]


def test_prediction_watch_skips_when_evidence_present(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_world_model_schema(conn)
    # A sense event + linked observation that satisfies the match terms.
    conn.execute(
        "INSERT INTO sense_events(id,sense_id,sense_type,source_id,observed_at,ingested_at) VALUES('se1','s','email','inbox',?,?)",
        (_iso(1), _iso(1)),
    )
    conn.execute(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at,sense_event_id) VALUES('o1','se1','fact','invoice reply received from finance','email://inbox/1',5,?, 'se1')",
        (_iso(1),),
    )
    conn.commit()
    add_prediction(
        conn,
        {
            "id": "p2",
            "title": "Verify invoice reply",
            # Two overlapping terms clear the engine's 0.34 bridge-score threshold
            # (a single-term overlap scores 1/3 and is treated as "no evidence").
            "match_json": {"sense_type": "email", "observation_terms_any": ["invoice", "reply"]},
            "check_after": _iso(-1),
            "expires_at": _iso(48),
        },
    )
    conn.commit()
    watched = prediction_watch(conn, lead="1d")
    assert watched == []


def test_world_tick_surfaces_watch_in_attention(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_world_model_schema(conn)
    conn.commit()
    conn.close()
    add_prediction(
        db,
        {
            "id": "p3",
            "title": "Verify school reply",
            "match_json": {"sense_type": "email", "observation_terms_any": ["school"]},
            "check_after": _iso(-1),
            "expires_at": _iso(48),
        },
    )
    report = world_tick(Path(db))
    assert any(a.get("kind") == "prediction_watch" and a.get("id") == "p3" for a in report["attention"])
    assert any(p["id"] == "p3" for p in report["pending_predictions"])

