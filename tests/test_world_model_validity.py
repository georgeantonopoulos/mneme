import sqlite3
from pathlib import Path

from mneme.agent.preflight import agent_preflight
from mneme.core import init_db, retrieve_context, write_research_edges


def _payload(subject: str, value: str, valid_until: str) -> dict:
    return {
        "title": "Fictional temporal state",
        "date": "2026-07-01",
        "claims": [
            {
                "subject": subject,
                "predicate": "status",
                "object": value,
                "certainty": "confirmed",
                "confidence": 0.95,
                "evidence": f"Fictional registry confirms {subject} status {value}.",
                "source_type": "research",
                "valid_until": valid_until,
            }
        ],
    }


def test_retrieval_labels_elapsed_assertion_without_mutating_status(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    expired = write_research_edges(conn, "Sources/old.md", _payload("Old Permit", "pending", "2026-07-02T00:00:00+00:00"))[0]
    active = write_research_edges(conn, "Sources/new.md", _payload("New Permit", "ready", "2026-07-04T00:00:00+00:00"))[0]
    conn.commit()
    before = [tuple(row) for row in conn.execute("SELECT id,status,updated_at FROM world_state_assertions ORDER BY id").fetchall()]
    conn.close()

    result = retrieve_context(db, "permit status", max_items=10, as_of="2026-07-03T00:00:00+00:00")
    by_id = {item["id"]: item for item in result["items"] if item["kind"] == "world_state_assertion"}

    assert by_id[expired["assertion_id"]]["truth_policy"] == "lapsed_state_assertion"
    assert by_id[expired["assertion_id"]]["status"] == "lapsed"
    assert by_id[active["assertion_id"]]["truth_policy"] == "current_state_assertion"
    assert by_id[active["assertion_id"]]["score"] > by_id[expired["assertion_id"]]["score"]

    conn = sqlite3.connect(db)
    after = conn.execute("SELECT id,status,updated_at FROM world_state_assertions ORDER BY id").fetchall()
    conn.close()
    assert after == before


def test_valid_until_boundary_is_inclusive(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    written = write_research_edges(conn, "Sources/boundary.md", _payload("Boundary Permit", "ready", "2026-07-03T00:00:00+00:00"))[0]
    conn.commit()
    conn.close()

    result = retrieve_context(db, "boundary permit", max_items=5, as_of="2026-07-03T00:00:00+00:00")
    item = next(item for item in result["items"] if item["id"] == written["assertion_id"])
    assert item["truth_policy"] == "current_state_assertion"


def test_preflight_partitions_effective_current_and_lapsed_assertions(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    expired = write_research_edges(conn, "Sources/old.md", _payload("Old Permit", "pending", "2026-07-02T00:00:00+00:00"))[0]
    active = write_research_edges(conn, "Sources/new.md", _payload("New Permit", "ready", "2026-07-04T00:00:00+00:00"))[0]
    conn.commit()
    conn.close()

    result = agent_preflight(db, "permit status", max_items=10, as_of="2026-07-03T00:00:00+00:00")

    assert result["world"]["as_of"] == "2026-07-03T00:00:00+00:00"
    assert {row["id"] for row in result["world"]["current_assertions"]} == {active["assertion_id"]}
    assert {row["id"] for row in result["world"]["lapsed_assertions"]} == {expired["assertion_id"]}
    assert all(
        thought.get("surface", {}).get("truth_policy") != "current_state_assertion"
        for thought in result["surface"].get("thoughts", [])
        if thought.get("surface", {}).get("id") == expired["assertion_id"]
    )
