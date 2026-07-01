import sqlite3
from pathlib import Path

from mneme.contract import check_db_contract
from mneme.core import forget_source, init_db, remember_graph, write_research_edges
from mneme.world_model.schema import ensure_world_model_schema
from mneme.world_model.state import upsert_assertion


def _payload(date: str, subject: str, predicate: str, obj: str, **claim_overrides):
    claim = {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "certainty": "confirmed",
        "confidence": 0.95,
        "evidence": f"Fictional source confirms {subject} {predicate} {obj}.",
        "source_type": "research",
    }
    claim.update(claim_overrides)
    return {"title": "Fictional resolution", "date": date, "claims": [claim]}


def _rows(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT id,subject_name,predicate,object_value,status,supersedes_id,superseded_by_id FROM world_state_assertions ORDER BY object_value"
    ).fetchall()


def test_research_edges_dual_write_confirmed_claims_once(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    payload = _payload("2026-07-01", "Fictional License", "expires_on", "2026-10-01")

    first = write_research_edges(conn, "Sources/license.md", payload)
    second = write_research_edges(conn, "Sources/license.md", payload)
    conn.commit()

    rows = _rows(conn)
    edge_count = conn.execute("SELECT count(*) FROM edges").fetchone()[0]
    conn.close()

    assert first[0]["assertion_id"] == second[0]["assertion_id"]
    assert edge_count == 1
    assert len(rows) == 1
    assert rows[0]["status"] == "current"
    assert rows[0]["object_value"] == "2026-10-01"


def test_research_dual_write_ignores_candidate_claims(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    init_db(conn)
    payload = _payload(
        "2026-07-01",
        "Fictional Subscription",
        "renews_on",
        "2026-08-15",
        confidence=0.5,
        certainty="candidate",
    )

    written = write_research_edges(conn, "Sources/subscription.md", payload)
    conn.commit()
    count = conn.execute("SELECT count(*) FROM world_state_assertions").fetchone()[0]
    conn.close()

    assert written[0]["status"] == "candidate"
    assert written[0]["assertion_id"] is None
    assert count == 0


def test_supersession_is_deterministic_under_replay(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    init_db(conn)
    old = _payload("2026-07-01", "Fictional Appointment", "scheduled_on", "2026-09-15")
    new = _payload("2026-07-02", "Fictional Appointment", "scheduled_on", "2026-09-16")

    write_research_edges(conn, "Sources/appointment-old.md", old)
    write_research_edges(conn, "Sources/appointment-new.md", new)
    write_research_edges(conn, "Sources/appointment-old.md", old)
    write_research_edges(conn, "Sources/appointment-new.md", new)
    conn.commit()

    rows = _rows(conn)
    conn.close()

    assert [(row["object_value"], row["status"]) for row in rows] == [
        ("2026-09-15", "superseded"),
        ("2026-09-16", "current"),
    ]
    assert rows[0]["superseded_by_id"] == rows[1]["id"]
    assert rows[1]["supersedes_id"] == rows[0]["id"]


def test_explicit_correction_contradicts_prior_current_and_blocks_replay(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    init_db(conn)
    old = _payload("2026-07-01", "Fictional Delivery", "arrives_on", "2026-07-10")
    correction = _payload(
        "2026-07-02",
        "Fictional Delivery",
        "arrives_on",
        "2026-07-11",
        certainty="user_confirmed",
        confidence=1.0,
        source_type="user_correction",
        metadata={"correction_type": "contradiction"},
    )

    write_research_edges(conn, "Sources/delivery-old.md", old)
    write_research_edges(conn, "Sources/delivery-correction.md", correction)
    write_research_edges(conn, "Sources/delivery-old.md", old)
    conn.commit()

    rows = _rows(conn)
    conn.close()

    assert [(row["object_value"], row["status"]) for row in rows] == [
        ("2026-07-10", "contradicted"),
        ("2026-07-11", "current"),
    ]


def test_killed_assertion_blocks_recreation_unless_user_confirmed(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "mneme.sqlite")
    init_db(conn)
    claim = _payload("2026-07-01", "Fictional Permit", "expires_on", "2026-12-01")["claims"][0]
    written = upsert_assertion(conn, claim, source_path="Sources/permit.md", valid_from="2026-07-01")
    conn.execute("UPDATE world_state_assertions SET status='killed' WHERE id=?", (written["id"],))

    blocked = upsert_assertion(conn, claim, source_path="Sources/permit.md", valid_from="2026-07-01")
    revived = upsert_assertion(
        conn,
        {**claim, "certainty": "user_confirmed", "confidence": 1.0, "source_type": "user_confirmation"},
        source_path="Sources/permit.md",
        valid_from="2026-07-02",
    )
    conn.commit()
    status = conn.execute("SELECT status FROM world_state_assertions WHERE id=?", (written["id"],)).fetchone()[0]
    conn.close()

    assert blocked["blocked"] is True
    assert revived["blocked"] is False
    assert status == "current"


def test_remember_graph_accepts_assertions_and_forget_cascades(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    payload = {
        "source_path": "mneme://agent/fictional-case",
        "assertions": [
            {
                "subject": "Fictional Case",
                "predicate": "status",
                "object": "ready",
                "certainty": "user_confirmed",
                "confidence": 1.0,
                "evidence": "User confirmed the fictional case is ready.",
                "source_type": "user_confirmation",
            }
        ],
    }

    remembered = remember_graph(db, payload)
    report = check_db_contract(db)
    dry = forget_source(db, payload["source_path"], dry_run=True)
    removed = forget_source(db, payload["source_path"])

    conn = sqlite3.connect(db)
    ensure_world_model_schema(conn)
    remaining = conn.execute("SELECT count(*) FROM world_state_assertions").fetchone()[0]
    conn.close()

    assert remembered["assertions"][0]["blocked"] is False
    assert report.status == "pass"
    assert dry["world_removed"]["world_state_assertions"] == 1
    assert removed["world_removed"]["world_state_assertions"] == 1
    assert remaining == 0
