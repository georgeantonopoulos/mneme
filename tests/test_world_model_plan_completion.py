import json
import sqlite3
from pathlib import Path

import pytest

from mneme.cli import main
from mneme.contract import check_db_contract, validate_agent_action
from mneme.core import ingest_sense_events, init_db, write_research_resolution
from mneme.senses.base import SenseEvent
from mneme.world_model.loop import world_tick
from mneme.world_model.predictions import add_prediction, check_prediction
from mneme.world_model.schema import ensure_world_model_schema
from mneme.world_model.state import upsert_assertion


def _event(event_id: str, *, title: str = "Routine", text: str = "- unrelated", observed_at: str = "2026-07-02T10:00:00+00:00") -> SenseEvent:
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
        metadata={},
    )


def test_prediction_add_is_content_hash_idempotent(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    payload = {
        "title": "Fictional confirmation should appear",
        "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["orchid", "permit"]},
        "check_after": "2026-07-01T00:00:00+00:00",
        "expires_at": "2026-07-03T00:00:00+00:00",
    }

    first = add_prediction(db, payload)
    second = add_prediction(db, payload)

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT count(*) FROM world_predictions").fetchone()[0]
    conn.close()
    assert first["id"] == second["id"]
    assert count == 1


def test_resolve_payload_writes_predictions_idempotently(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    payload = {
        "title": "Fictional resolver",
        "date": "2026-07-02",
        "claims": [
            {
                "subject": "Fictional Form",
                "predicate": "due_on",
                "object": "2026-07-04",
                "certainty": "confirmed",
                "confidence": 0.95,
                "evidence": "Fictional email says the form is due on 2026-07-04.",
                "source_type": "research",
            }
        ],
        "predictions": [
            {
                "title": "Created task should be sensed",
                "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["fictional", "form"]},
                "check_after": "2026-07-02T00:00:00+00:00",
                "expires_at": "2026-07-03T00:00:00+00:00",
            }
        ],
    }

    first = write_research_resolution(vault, db, payload)
    second = write_research_resolution(vault, db, payload)

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT count(*) FROM world_predictions").fetchone()[0]
    conn.close()
    assert first["predictions_written"] == 1
    assert second["predictions"][0]["id"] == first["predictions"][0]["id"]
    assert count == 1


def test_missed_prediction_couples_assertion_confidence_once_and_dry_run_is_safe(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    ingest_sense_events(conn, [_event("evt-1")])
    assertion = upsert_assertion(
        conn,
        {
            "subject": "Fictional Assertion",
            "predicate": "expects",
            "object": "signal",
            "certainty": "confirmed",
            "confidence": 1.0,
            "evidence": "Fictional source confirms the expected signal.",
            "source_type": "research",
        },
        source_path="Sources/signal.md",
        valid_from="2026-07-01",
    )
    add_prediction(
        conn,
        {
            "id": "pred-coupled",
            "title": "Signal should arrive",
            "subject_assertion_id": assertion["id"],
            "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["missing", "signal"]},
            "check_after": "2026-07-01T00:00:00+00:00",
            "expires_at": "2026-07-02T00:00:00+00:00",
        },
    )
    conn.commit(); conn.close()

    dry = check_prediction(db, "pred-coupled", now="2026-07-03T00:00:00+00:00", dry_run=True)
    conn = sqlite3.connect(db)
    confidence_after_dry = conn.execute("SELECT confidence FROM world_state_assertions WHERE id=?", (assertion["id"],)).fetchone()[0]
    status_after_dry = conn.execute("SELECT status FROM world_predictions WHERE id='pred-coupled'").fetchone()[0]
    conn.close()
    batch_dry = world_tick(db, before="2026-07-03T00:00:00+00:00", dry_run=True)
    conn = sqlite3.connect(db)
    confidence_after_batch_dry = conn.execute("SELECT confidence FROM world_state_assertions WHERE id=?", (assertion["id"],)).fetchone()[0]
    status_after_batch_dry = conn.execute("SELECT status FROM world_predictions WHERE id='pred-coupled'").fetchone()[0]
    conn.close()
    real = check_prediction(db, "pred-coupled", now="2026-07-03T00:00:00+00:00")
    again = check_prediction(db, "pred-coupled", now="2026-07-04T00:00:00+00:00")
    conn = sqlite3.connect(db)
    confidence, assertion_status = conn.execute("SELECT confidence,status FROM world_state_assertions WHERE id=?", (assertion["id"],)).fetchone()
    conn.close()

    assert dry["status"] == "missed"
    assert confidence_after_dry == 1.0
    assert status_after_dry == "open"
    assert batch_dry["dry_run"] is True
    assert confidence_after_batch_dry == 1.0
    assert status_after_batch_dry == "open"
    assert real["confidence_coupled"] is True
    assert again["confidence_coupled"] is False
    assert confidence == 0.8
    assert assertion_status == "contradicted"
    assert check_db_contract(db).status == "pass"


def test_state_cli_list_explain_and_backfill(tmp_path: Path, capsys):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    # Existing research edge can be backfilled into an assertion.
    from mneme.core import write_research_edges
    write_research_edges(conn, "Sources/backfill.md", {
        "date": "2026-07-02",
        "claims": [{
            "subject": "Fictional Backfill",
            "predicate": "located_in",
            "object": "Example City",
            "object_type": "place",
            "certainty": "confirmed",
            "confidence": 0.95,
            "evidence": "Fictional registry confirms this location.",
            "source_type": "research",
        }],
    })
    conn.commit(); conn.close()

    main(["state", "backfill", "--db", str(db), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    main(["state", "list", "--db", str(db), "--subject", "Backfill"])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["subject_name"] == "Fictional Backfill"
    main(["state", "explain", rows[0]["id"], "--db", str(db)])
    explained = json.loads(capsys.readouterr().out)
    assert explained["assertion"]["id"] == rows[0]["id"]
    assert explained["hints"]["source_edge_alive"] is True


def test_world_tick_reports_lapsed_open_loops_and_contract_action_failures(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    assertion = upsert_assertion(
        conn,
        {
            "subject": "Fictional Loop",
            "predicate": "due_on",
            "object": "2026-07-01",
            "state_type": "open_loop",
            "valid_until": "2026-07-01T00:00:00+00:00",
            "certainty": "confirmed",
            "confidence": 0.95,
            "evidence": "Fictional source confirms the loop was due.",
            "source_type": "research",
        },
        source_path="Sources/loop.md",
        valid_from="2026-06-30",
    )
    ensure_world_model_schema(conn)
    conn.execute(
        "INSERT INTO world_actions(id,actor,action_type,title,side_effect_level,status,created_at) VALUES(?,?,?,?,?,?,?)",
        ("bad-action", "agent:test", "email_sent", "Bad side effect", "private_external", "recorded", "2026-07-02T00:00:00+00:00"),
    )
    conn.commit(); conn.close()

    report = world_tick(db, before="2026-07-02T00:00:00+00:00", dry_run=True)
    contract = check_db_contract(db)
    action_report = validate_agent_action({"side_effect_level": "private_external"}, {})

    assert report["dry_run"] is True
    assert report["lapsed_open_loops"][0]["id"] == assertion["id"]
    assert any(item["kind"] == "lapsed_open_loop" for item in report["attention"])
    assert contract.status == "fail"
    assert "external_ref" in action_report.failures[0]


def test_retrieval_and_preflight_include_world_items(tmp_path: Path):
    from mneme.agent.preflight import agent_preflight
    from mneme.core import retrieve_context

    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    written = upsert_assertion(
        conn,
        {
            "subject": "Fictional Passport",
            "predicate": "expires_on",
            "object": "2026-12-31",
            "certainty": "confirmed",
            "confidence": 0.95,
            "evidence": "Fictional registry confirms the passport expiry date.",
            "source_type": "research",
        },
        source_path="Sources/passport.md",
        valid_from="2026-07-02",
    )
    add_prediction(conn, {
        "id": "pred-preflight",
        "title": "Passport renewal task should appear",
        "match_json": {"sense_type": "fictional_tasks", "observation_terms_all": ["passport", "renewal"]},
        "check_after": "2026-07-01T00:00:00+00:00",
        "expires_at": "2026-07-03T00:00:00+00:00",
    })
    conn.commit(); conn.close()

    context = retrieve_context(db, "passport expiry", max_items=5)
    preflight = agent_preflight(db, "passport expiry", max_items=5, surface_limit=1)

    assert any(item["kind"] == "world_state_assertion" and item["id"] == written["id"] for item in context["items"])
    assert preflight["world"]["current_assertions"]
    assert preflight["world"]["due_predictions"][0]["id"] == "pred-preflight"


def test_record_action_enforces_side_effect_handles(tmp_path: Path):
    from mneme.world_model.actions import record_action

    db = tmp_path / "mneme.sqlite"
    with pytest.raises(ValueError, match="external_ref or tool_call_id"):
        record_action(db, {
            "actor": "agent:test",
            "action_type": "email_sent",
            "title": "Impossible send",
            "side_effect_level": "private_external",
        })

    recorded = record_action(db, {
        "actor": "agent:test",
        "action_type": "email_drafted",
        "title": "Drafted fictional email",
        "side_effect_level": "private_external",
        "tool_call_id": "tool-call-1",
    })

    assert recorded["tool_call_id"] == "tool-call-1"
    assert check_db_contract(db).status == "pass"
