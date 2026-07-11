import sqlite3
from pathlib import Path

from mneme.agent.preflight import agent_preflight
from mneme.core import init_db, remember_graph, write_research_edges
from mneme.world_model.conflicts import detect_state_conflicts
from mneme.world_model.loop import world_tick


def _claim(subject: str, value: str) -> dict:
    return {
        "title": "Fictional state resolution",
        "date": "2026-07-01",
        "claims": [
            {
                "subject": subject,
                "predicate": "status",
                "object": value,
                "certainty": "confirmed",
                "confidence": 0.95,
                "evidence": f"Fictional registry confirms status {value}.",
                "source_type": "research",
                "metadata": {"conflict_policy": "exclusive"},
            }
        ],
    }


def test_candidate_evidence_conflict_is_visible_without_replacing_current_state(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    write_research_edges(conn, "Sources/current.md", _claim("Fictional Permit", "ready"))
    conn.commit()
    conn.close()

    remember_graph(
        db,
        {
            "source_path": "mneme://sense/permit-update",
            "nodes": [
                {"ref": "permit", "type": "entity", "name": "Fictional Permit"},
                {"ref": "paused", "type": "state", "name": "paused"},
            ],
            "edges": [
                {
                    "src": "permit",
                    "dst": "paused",
                    "relation": "status",
                    "status": "candidate",
                    "confidence": 0.7,
                    "evidence": "A newly sensed fictional source says the permit may be paused.",
                }
            ],
        },
    )

    conflicts = detect_state_conflicts(db)

    assert len(conflicts) == 1
    assert conflicts[0]["kind"] == "evidence_conflict"
    assert conflicts[0]["severity"] == "review"
    assert conflicts[0]["current"]["object"] == "ready"
    assert conflicts[0]["challenger"]["object"] == "paused"
    assert conflicts[0]["challenger"]["status"] == "candidate"

    conn = sqlite3.connect(db)
    current = conn.execute(
        "SELECT object_value,status FROM world_state_assertions WHERE status='current'"
    ).fetchone()
    conn.close()
    assert current == ("ready", "current")


def test_superseded_assertion_evidence_is_not_reported_as_fresh_conflict(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    write_research_edges(conn, "Sources/old.md", _claim("Fictional Permit", "draft"))
    write_research_edges(conn, "Sources/new.md", _claim("Fictional Permit", "ready"))
    conn.commit()
    conn.close()

    assert detect_state_conflicts(db) == []


def test_multi_valued_predicate_does_not_create_false_conflicts(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    payload = _claim("Fictional Account", "invoice-a")
    payload["claims"][0]["predicate"] = "paid"
    payload["claims"][0]["metadata"] = {}
    write_research_edges(conn, "Sources/payment.md", payload)
    conn.commit()
    conn.close()
    remember_graph(
        db,
        {
            "source_path": "mneme://sense/another-payment",
            "nodes": [
                {"ref": "account", "type": "entity", "name": "Fictional Account"},
                {"ref": "other", "type": "invoice", "name": "invoice-b"},
            ],
            "edges": [{"src": "account", "dst": "other", "relation": "paid", "status": "candidate"}],
        },
    )

    assert detect_state_conflicts(db) == []


def test_world_tick_and_preflight_surface_conflicts_as_attention(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    write_research_edges(conn, "Sources/current.md", _claim("Fictional Permit", "ready"))
    conn.commit()
    conn.close()
    remember_graph(
        db,
        {
            "source_path": "mneme://sense/permit-update",
            "nodes": [
                {"ref": "permit", "type": "entity", "name": "Fictional Permit"},
                {"ref": "paused", "type": "state", "name": "paused"},
            ],
            "edges": [
                {
                    "src": "permit",
                    "dst": "paused",
                    "relation": "status",
                    "status": "candidate",
                    "confidence": 0.7,
                    "evidence": "A newly sensed fictional source says the permit may be paused.",
                }
            ],
        },
    )

    tick = world_tick(db, before="2026-07-02T00:00:00+00:00", dry_run=True)
    preflight = agent_preflight(db, "What is the Fictional Permit status?")

    assert tick["contradictions"][0]["kind"] == "evidence_conflict"
    assert any(item["kind"] == "evidence_conflict" for item in tick["attention"])
    assert preflight["world"]["contradictions"][0]["challenger"]["object"] == "paused"
    assert any("world-state contradiction" in warning for warning in preflight["warnings"])
