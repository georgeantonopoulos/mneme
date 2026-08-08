import json
import sqlite3
from pathlib import Path

import pytest

from mneme.agent import agent_preflight
from mneme.cli import main
from mneme.contract import check_db_contract
from mneme.core import (
    generate_proactive_thought,
    init_db,
    ingest_sense_events,
    now_iso,
    record_feedback,
    retrieve_context,
    surface_thoughts,
    tick,
    upsert_edge,
    upsert_node,
)
from mneme.senses.base import SenseEvent


def _nodes(conn: sqlite3.Connection) -> tuple[str, str]:
    init_db(conn)
    src = upsert_node(conn, "project", "Alpha", "alpha.md")
    dst = upsert_node(conn, "project", "Beta", "beta.md")
    return src, dst


def test_active_semantic_without_evidence_is_demoted_to_candidate(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    src, dst = _nodes(conn)

    edge = upsert_edge(conn, src, dst, "belongs_to", "alpha.md", "", 0.95, status="active")
    conn.commit()
    row = conn.execute("SELECT status,metadata_json FROM edges WHERE id=?", (edge,)).fetchone()
    conn.close()

    assert row[0] == "candidate"
    assert "requires_explicit_validation" in json.loads(row[1])["contract"]["reasons"]


def test_unknown_relation_requires_validation(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    src, dst = _nodes(conn)

    edge = upsert_edge(conn, src, dst, "made_up_relation", "alpha.md", "Alpha maybe Beta", 0.95, status="active")
    conn.commit()
    status = conn.execute("SELECT status FROM edges WHERE id=?", (edge,)).fetchone()[0]
    conn.close()

    assert status == "candidate"


def test_dynamic_domain_relation_is_known_but_requires_validation():
    from mneme.contract import relationship_policy

    policy = relationship_policy("payment_due")

    assert policy.known is True
    assert policy.category == "semantic_dynamic"
    assert policy.requires_validation is True


def test_domain_relation_labels_are_open_vocabulary():
    from mneme.contract import relationship_policy

    policy = relationship_policy("KS1 sign-up goes live")

    assert policy.known is True
    assert policy.category == "semantic_dynamic"
    assert policy.requires_validation is True


def test_blank_relation_remains_a_contract_warning():
    from mneme.contract import relationship_policy

    policy = relationship_policy("   ")

    assert policy.known is False
    assert policy.requires_validation is True


def test_validated_research_edge_can_be_active(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    src, dst = _nodes(conn)

    edge = upsert_edge(
        conn,
        src,
        dst,
        "belongs_to",
        "Sources/research.md",
        "Receipt confirms Alpha belongs to Beta.",
        0.95,
        status="active",
        source_type="research",
        metadata={"research_resolution": True},
    )
    conn.commit()
    status = conn.execute("SELECT status FROM edges WHERE id=?", (edge,)).fetchone()[0]
    conn.close()

    assert status == "active"
    assert check_db_contract(db).status == "pass"


def test_killed_tombstone_blocks_recreation_by_upsert_edge(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    src, dst = _nodes(conn)
    killed = upsert_edge(conn, src, dst, "relates_to", "old.md", "false relationship", 0.4, status="killed")

    recreated = upsert_edge(
        conn,
        src,
        dst,
        "relates_to",
        "new.md",
        "new attempt",
        0.95,
        status="active",
        source_type="research",
        metadata={"research_resolution": True},
    )
    conn.commit()
    rows = conn.execute("SELECT id,status FROM edges WHERE src_id=? AND dst_id=? AND relation='relates_to'", (src, dst)).fetchall()
    blocked_events = conn.execute("SELECT count(*) FROM edge_debug_log WHERE edge_id=? AND event='blocked_recreation'", (killed,)).fetchone()[0]
    conn.close()

    assert recreated == killed
    assert rows == [(killed, "killed")]
    assert blocked_events == 1


def test_ingest_sense_events_matches_markdown_observation_graph_shape(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    event = SenseEvent(
        id="evt-1",
        sense_id="vault",
        sense_type="md",
        source_id="alpha.md",
        source_uri=None,
        observed_at="2026-05-07T00:00:00+00:00",
        title="Alpha",
        text="- [ ] Need follow up with Beta by 2026-05-20\nRelated [[Beta]]",
        links=["Beta"],
        metadata={"path": "alpha.md", "node_type": "note"},
    )

    stats = ingest_sense_events(conn, [event], hints=["Beta"])
    conn.commit()
    relations = dict(conn.execute("SELECT relation,status FROM edges").fetchall())
    observation_nodes = conn.execute("SELECT count(*) FROM nodes WHERE type='observation'").fetchone()[0]
    conn.close()

    assert stats["observations"] == 1
    assert observation_nodes == 1
    assert relations["links_to"] == "candidate"
    assert relations["has_blocked"] == "active"
    assert relations["mentions_date"] == "candidate"


def test_generate_proactive_thought_uses_surface_truth_policy(tmp_path: Path):
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
                text="- [ ] Need invoice follow up by 2026-05-20",
                metadata={"path": "alpha.md"},
            )
        ],
        hints=["invoice"],
    )
    conn.commit()
    conn.close()

    thought = generate_proactive_thought(db, hints=["invoice"])

    assert thought["surface"]["truth_policy"] == "source_contained_observation"


def test_feedback_dismiss_weakens_related_edge(tmp_path: Path):
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
    edge_id, before = conn.execute("SELECT id,strength FROM edges WHERE relation='has_blocked'").fetchone()
    conn.close()
    tick(db)
    thought_id = surface_thoughts(db, limit=1)[0]["id"]

    result = record_feedback(db, thought_id, "deny", reason="not useful now")
    conn = sqlite3.connect(db)
    after = conn.execute("SELECT strength,status FROM edges WHERE id=?", (edge_id,)).fetchone()
    conn.close()

    assert result["edge_changes"][0]["action"] == "weaken"
    assert after[0] < before
    assert after[1] == "active"


def test_feedback_kill_creates_edge_tombstone_only_when_false(tmp_path: Path):
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
    edge_id = conn.execute("SELECT id FROM edges WHERE relation='has_blocked'").fetchone()[0]
    conn.close()
    tick(db)
    thought_id = surface_thoughts(db, limit=1)[0]["id"]

    result = record_feedback(db, thought_id, "kill", reason="false assumption")
    conn = sqlite3.connect(db)
    status, strength = conn.execute("SELECT status,strength FROM edges WHERE id=?", (edge_id,)).fetchone()
    conn.close()

    assert result["edge_changes"][0]["action"] == "kill"
    assert status == "killed"
    assert strength == 0.0


def test_agent_preflight_returns_mandatory_rules(tmp_path: Path):
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
                text="- [ ] Need invoice follow up by 2026-05-20",
                metadata={"path": "alpha.md"},
            )
        ],
        hints=["invoice"],
    )
    conn.commit()
    conn.close()

    result = agent_preflight(db, "invoice follow up", hints=["invoice"])

    assert result["contract"]["status"] == "pass"
    assert "Read truth_policy before using any item." in result["agent_rules"]
    assert result["context"]["items"][0]["truth_policy"]


def test_agent_preflight_fails_when_contract_check_fails(tmp_path: Path, capsys):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    src, dst = _nodes(conn)
    conn.execute(
        """INSERT INTO edges(id,src_id,dst_id,relation,source_path,confidence,evidence_text,created_at,updated_at,status,strength,source_type,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("bad-edge", src, dst, "belongs_to", "alpha.md", 0.95, "", now_iso(), now_iso(), "active", 0.95, "vault", "{}"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit):
        main(["agent", "preflight", "--db", str(db), "--prompt", "Alpha Beta"])
    output = json.loads(capsys.readouterr().out)

    assert output["contract"]["status"] == "fail"
    assert output["failures"]
