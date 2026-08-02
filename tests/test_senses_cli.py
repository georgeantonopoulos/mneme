import json
import sqlite3
from pathlib import Path

from mneme.cli import main
from mneme.core import explain_thought, ingest_sense_events, record_feedback, surface_thoughts, tick
from mneme.senses.base import SenseEvent
from mneme.senses.gws import GwsSense
from mneme.senses.markdown import MarkdownSense


def test_markdown_sense_emits_normalized_events(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- [ ] Follow up with Casey by 2026-05-10\nRelated: [[Casey]]\n", encoding="utf-8")

    event = list(MarkdownSense(sense_id="vault", vault=vault).collect())[0]

    assert event.sense_id == "vault"
    assert event.sense_type == "md"
    assert event.source_id == "alpha.md"
    assert event.title == "Alpha"
    assert event.links == ["Casey"]
    assert event.metadata["path"] == "alpha.md"


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.commands = []

    def run(self, args):
        self.commands.append(args)
        return self.outputs.pop(0)


def test_gws_sense_parses_email_calendar_and_task_fixture_output(tmp_path: Path):
    runner = FakeRunner(
        [
            json.dumps({"messages": [{"id": "m1", "threadId": "thread-1", "subject": "ARRI feedback", "snippet": "Need reply about Sequency ARRI feedback", "from": "Casey"}]}),
            json.dumps({
                "id": "m1",
                "threadId": "thread-1",
                "internalDate": "1778236800000",
                "payload": {
                    "mimeType": "multipart/mixed",
                    "headers": [
                        {"name": "Subject", "value": "ARRI feedback"},
                        {"name": "From", "value": "Casey (test sender)"},
                        {"name": "To", "value": "George (test recipient)"},
                        {"name": "Date", "value": "Fri, 08 May 2026 10:00:00 +0000"},
                    ],
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": "QWN0aW9uIHJlcXVpcmVkOiBzaWduIGFuZCByZXR1cm4gdGhlIHJlbGVhc2UgZm9ybS4="}},
                        {"mimeType": "application/pdf", "filename": "feedback.pdf", "body": {"attachmentId": "att-1", "size": 1234}},
                    ],
                },
            }),
            json.dumps({"events": [{"id": "e1", "summary": "ARRI review", "start": "2026-05-08", "description": "Deadline risk for feedback"}]}),
            json.dumps({"tasks": [{"id": "t1", "title": "Send ARRI reply", "notes": "Follow up today"}]}),
        ]
    )

    events = list(GwsSense(runner=runner).collect(limit=3))

    assert [event.event_type for event in events] == ["email_message", "calendar_event", "task"]
    assert events[0].source_id == "email_message:m1"
    assert "Need reply" in events[0].text
    assert "Action required: sign and return the release form." in events[0].text
    assert events[0].metadata["gws"]["threadId"] == "thread-1"
    assert events[0].metadata["gws"]["headers"]["from"] == "Casey (test sender)"
    assert events[0].metadata["gws"]["attachments"][0]["filename"] == "feedback.pdf"
    assert len(runner.commands) == 4

    conn = sqlite3.connect(tmp_path / "observations.sqlite")
    ingest_sense_events(conn, [events[0]])
    observation = conn.execute("SELECT text FROM observations WHERE sense_event_id=?", (events[0].id,)).fetchone()
    conn.close()
    assert observation is not None
    assert "Action required: sign and return the release form." in observation[0]


def test_gws_sense_malformed_email_detail_falls_back_to_list_row():
    runner = FakeRunner(
        [
            json.dumps({"messages": [{"id": "m2", "subject": "Malformed detail", "snippet": "Keep this message"}]}),
            json.dumps({"id": "m2", "payload": [], "parts": {"unexpected": "mapping"}}),
        ]
    )

    events = list(GwsSense(include_calendar=False, include_tasks=False, runner=runner).collect(limit=1))

    assert len(events) == 1
    assert "Keep this message" in events[0].text
    assert events[0].metadata["gws"]["headers"] == {}
    assert events[0].metadata["gws"]["attachments"] == []


def test_ingest_sense_events_stores_provenance_and_candidate_links(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    event = SenseEvent(
        id="evt-1",
        sense_id="gws",
        sense_type="gws",
        source_id="email_message:m1",
        source_uri="gws://mail/m1",
        observed_at="2026-05-07T00:00:00+00:00",
        title="Project feedback",
        text="- [ ] Follow up on project feedback by 2026-05-10\nRelated [[Project X]]",
        links=["Project X"],
        event_type="email_message",
    )

    stats = ingest_sense_events(conn, [event], hints=["feedback"])
    conn.commit()

    source = conn.execute("SELECT sense_id,sense_type,source_id,event_type FROM sense_events").fetchone()
    link_status = conn.execute("SELECT status FROM edges WHERE relation='links_to'").fetchone()[0]
    obs_count = conn.execute("SELECT count(*) FROM observations WHERE sense_event_id='evt-1'").fetchone()[0]
    conn.close()

    assert stats["events"] == 1
    assert source == ("gws", "gws", "email_message:m1", "email_message")
    assert link_status == "candidate"
    assert obs_count == 1


def test_tick_surface_feedback_and_explain_are_source_agnostic(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    events = [
        SenseEvent(
            id="md-1",
            sense_id="vault",
            sense_type="md",
            source_id="project.md",
            source_uri=None,
            observed_at="2026-05-07T00:00:00+00:00",
            title="Sequency",
            text="- [ ] Need Sequency ARRI feedback reply by 2026-05-10",
            event_type="document",
            metadata={"path": "project.md"},
        ),
        SenseEvent(
            id="gws-1",
            sense_id="gws",
            sense_type="gws",
            source_id="email_message:m1",
            source_uri="gws://mail/m1",
            observed_at="2026-05-07T00:00:00+00:00",
            title="ARRI feedback",
            text="Need Sequency ARRI feedback reply soon",
            event_type="email_message",
        ),
    ]
    ingest_sense_events(conn, events, hints=["feedback"])
    conn.commit()
    conn.close()

    pulse = tick(db, hints=["feedback"])
    surfaced = surface_thoughts(db, limit=1)
    thought_id = surfaced[0]["id"]
    explanation = explain_thought(db, thought_id)
    denied = record_feedback(db, thought_id, "deny", reason="not useful now")
    snoozed = record_feedback(db, thought_id, "snooze", snooze="7d")
    after_snooze = surface_thoughts(db, limit=5)

    assert pulse["candidates_updated"] >= 1
    assert surfaced[0]["activation_score"] > 0
    assert "cross_sense_corroboration" in surfaced[0]["why_now"]["factors"]
    assert explanation["seed_observation"]["text"]
    assert explanation["sense_provenance"]
    assert denied["status"] == "dismissed"
    assert snoozed["cooldown_until"]
    assert all(item["id"] != thought_id for item in after_snooze)


def test_feedback_kill_prevents_surface(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    ingest_sense_events(
        conn,
        [
            SenseEvent(
                id="evt",
                sense_id="vault",
                sense_type="md",
                source_id="alpha.md",
                source_uri=None,
                observed_at="2026-05-07T00:00:00+00:00",
                title="Alpha",
                text="- [ ] Need follow up by 2026-05-20",
                metadata={"path": "alpha.md"},
            )
        ],
    )
    conn.commit()
    conn.close()
    tick(db)
    thought_id = surface_thoughts(db, limit=1)[0]["id"]

    killed = record_feedback(db, thought_id, "kill", reason="false assumption")

    assert killed["status"] == "killed"
    assert all(item["id"] != thought_id for item in surface_thoughts(db, limit=5))


def test_cli_sense_list_run_dry_tick_surface_feedback_explain(tmp_path: Path, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- [ ] Follow up about invoice by 2026-05-20\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"vault": str(vault), "db": str(db), "hints": ["invoice"]}), encoding="utf-8")

    main(["--config", str(config), "sense", "list", "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert any(item["type"] == "md" for item in listed)

    main(["--config", str(config), "sense", "run", "md", "--db", str(db), "--json"])
    run_stats = json.loads(capsys.readouterr().out)
    assert run_stats["events"] == 1

    main(["sense", "run", "gws", "--dry-run", "--json"])
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] is True
    assert dry["by_sense"]["gws"]["commands"]

    main(["--config", str(config), "tick", "--db", str(db), "--json"])
    assert json.loads(capsys.readouterr().out)["candidates_updated"] >= 1

    main(["surface", "--db", str(db), "--json"])
    surfaced = json.loads(capsys.readouterr().out)
    thought_id = surfaced[0]["id"]

    main(["feedback", thought_id, "--db", str(db), "--too-obvious", "--json"])
    assert json.loads(capsys.readouterr().out)["feedback_type"] == "too_obvious"

    main(["explain", thought_id, "--db", str(db), "--json"])
    explained = json.loads(capsys.readouterr().out)
    assert explained["id"] == thought_id
    assert explained["feedback_history"]
