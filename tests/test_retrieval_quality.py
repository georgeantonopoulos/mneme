from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from mneme.core import (
    _retrieval_edge_source_authority,
    _retrieval_source_authority,
    _retrieval_staleness,
    add_observation,
    init_db,
    retrieve_context,
    upsert_edge,
    upsert_node,
)


@dataclass
class RetrievalEvalCase:
    query: str
    expected_source_paths: list[str]
    expected_node_names: list[str]
    forbidden_patterns: list[str]
    min_expected_items: int = 1


def _obs(conn: sqlite3.Connection, kind: str, name: str, source_path: str, text: str, score: float = 8.0, node_type: str = "project") -> str:
    node_id = upsert_node(conn, node_type, name, source_path, 0.95)
    add_observation(conn, node_id, kind, text, source_path, score)
    return node_id


def _seed_quality_db(db: Path) -> dict[str, str]:
    conn = sqlite3.connect(db)
    init_db(conn)
    nodes = {
        "sequency": _obs(conn, "blocked", "Sequency App", "Projects/sequency-app.md", "Sequency App launch partner notes and active follow up list."),
        "maya": _obs(conn, "blocked", "Maya Greek Summer Camp", "events/maya-greek-summer-camp.md", "Maya Greek summer camp current booking and contact details.", node_type="event"),
        "cassini": _obs(conn, "risk", "Cassini Broken Window", "vendors/cassini-property.md", "Cassini broken window open repair issue, awaiting landlord response.", node_type="vendor"),
        "chepstow": _obs(conn, "blocked", "Chepstow House School Fees", "Projects/chepstow-house-fees.md", "Chepstow House school fees current payment plan and finance contact.", node_type="finance"),
        "moraitis": _obs(conn, "blocked", "Moraitis Placement Quiz", "people/moraitis-school.md", "Moraitis placement quiz school-related items and preparation notes.", node_type="person"),
        "belvedere": _obs(conn, "blocked", "Belvedere Tony Xu", "vendors/belvedere-tony-xu.md", "Belvedere Tony Xu property agent viewing thread.", node_type="vendor"),
        "invoice": _obs(conn, "blocked", "Power of Play Invoice", "Projects/power-of-play-invoice.md", "Power of Play invoice finance item needs reconciliation.", node_type="finance"),
        "tomorrow": _obs(conn, "blocked", "Fresh Due Tomorrow", "gws://tasks/fresh-due-tomorrow", "Due tomorrow: call current supplier about booking.", node_type="event"),
        "urgent": _obs(conn, "risk", "Fresh Urgent Deadline", "email://inbox/urgent-deadline", "Urgent deadline from email: submit current form.", node_type="event"),
        "resolved": _obs(conn, "done", "Current Resolution Policy", "Projects/resolution-policy.md", "Resolved sent paid historical examples should not outrank current open items."),
        "gws": _obs(conn, "blocked", "GWS Calendar Item", "gws://calendar/source-authority", "gws email calendar sources contain the live appointment.", node_type="event"),
        "confirmed": _obs(conn, "correction", "User Confirmed Correction", "Projects/user-confirmed-correction.md", "User confirmed correction is the authoritative current fact."),
        "vague": _obs(conn, "blocked", "Current Status", "Projects/current-status.md", "Current status overview with live project work."),
    }
    stale = [
        ("Sequency Daily", "archive/daily/2026-04-01.md", "Sequency App old daily summary resolved sent paid."),
        ("Maya Daily", "daily/2026-04-02.md", "Maya Greek summer camp archived daily note."),
        ("Cassini Complaint", "archive/daily/2026-03-28.md", "Cassini broken window resolved complaint sent."),
        ("Chepstow Deadline", "daily/2026-04-01.md", "Chepstow House school fees April deadline summary paid."),
        ("Moraitis Briefing", "memory/2026-04-01.md", "Moraitis placement quiz old daily briefing."),
        ("Old Urgent", "daily/2026-03-31.md", "Urgent deadline due tomorrow Mar 31."),
        ("Old GWS Memory", "memory/2026-04-01.md", "gws email calendar old memory summary."),
        ("Vague Daily", "archive/daily/2026-04-01.md", "Current status old daily summary resolved."),
    ]
    for name, path, text in stale:
        _obs(conn, "blocked", name, path, text, 9.5)

    active_src = upsert_node(conn, "person", "Active Edge Source", "Projects/active-edge.md", 1.0)
    active_dst = upsert_node(conn, "vendor", "Active Edge Target", "Projects/active-edge.md", 1.0)
    candidate_src = upsert_node(conn, "person", "Candidate Edge Source", "Projects/candidate-edge.md", 1.0)
    candidate_dst = upsert_node(conn, "vendor", "Candidate Edge Target", "Projects/candidate-edge.md", 1.0)
    upsert_edge(conn, active_src, active_dst, "candidate_edge_active", "Projects/active-edge.md", "candidate edge active confirmed evidence.", 0.95, status="active", strength=0.95, source_type="user_confirmed")
    upsert_edge(conn, candidate_src, candidate_dst, "candidate_edge_unconfirmed", "Projects/candidate-edge.md", "candidate edge unconfirmed evidence.", 0.95, status="candidate", strength=0.95, source_type="candidate")
    nodes["active_edge"] = active_src
    nodes["candidate_edge"] = candidate_src
    conn.commit()
    conn.close()
    return nodes


EVAL_CASES = [
    RetrievalEvalCase("Sequency App", ["Projects/sequency-app.md"], ["Sequency App"], [r"old daily"]),
    RetrievalEvalCase("Maya Greek summer camp", ["events/maya-greek-summer-camp.md"], ["Maya Greek Summer Camp"], [r"archived daily"]),
    RetrievalEvalCase("Cassini broken window", ["vendors/cassini-property.md"], ["Cassini Broken Window"], [r"resolved complaint"]),
    RetrievalEvalCase("Chepstow House school fees", ["Projects/chepstow-house-fees.md"], ["Chepstow House School Fees"], [r"April deadline"]),
    RetrievalEvalCase("Moraitis placement quiz", ["people/moraitis-school.md"], ["Moraitis Placement Quiz"], [r"old daily briefing"]),
    RetrievalEvalCase("Belvedere Tony Xu", ["vendors/belvedere-tony-xu.md"], ["Belvedere Tony Xu"], []),
    RetrievalEvalCase("Power of Play invoice", ["Projects/power-of-play-invoice.md"], ["Power of Play Invoice"], []),
    RetrievalEvalCase("due tomorrow", ["gws://tasks/fresh-due-tomorrow"], ["Fresh Due Tomorrow"], [r"Mar 31"]),
    RetrievalEvalCase("urgent deadline", ["email://inbox/urgent-deadline"], ["Fresh Urgent Deadline"], [r"Mar 31"]),
    RetrievalEvalCase("resolved sent paid", ["Projects/resolution-policy.md"], ["Current Resolution Policy"], [r"archive/daily"]),
    RetrievalEvalCase("gws email calendar", ["gws://calendar/source-authority"], ["GWS Calendar Item"], [r"old memory"]),
    RetrievalEvalCase("current status", ["Projects/current-status.md"], ["Current Status"], [r"old daily summary"]),
    RetrievalEvalCase("user confirmed correction", ["Projects/user-confirmed-correction.md"], ["User Confirmed Correction"], []),
    RetrievalEvalCase("candidate edge", ["Projects/active-edge.md"], ["Active Edge Source candidate_edge_active Active Edge Target"], [r"unconfirmed evidence"]),
    RetrievalEvalCase("property agent", ["vendors/belvedere-tony-xu.md"], ["Belvedere Tony Xu"], []),
]


def test_retrieval_smoke(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    _seed_quality_db(db)

    for case in EVAL_CASES:
        result = retrieve_context(db, case.query, max_items=6, hints=["current", "urgent", "deadline"])
        items = result["items"]
        assert len(items) >= case.min_expected_items, case.query
        top_text = f"{items[0].get('title')} {items[0].get('source_path')} {items[0].get('snippet')}"
        top_three_text = "\n".join(f"{item.get('title')} {item.get('source_path')} {item.get('snippet')}" for item in items[:3])
        assert any(path in top_three_text for path in case.expected_source_paths), case.query
        assert any(name in top_three_text for name in case.expected_node_names), case.query
        for pattern in case.forbidden_patterns:
            assert not re.search(pattern, top_text, re.I), case.query


def test_retrieval_authority_and_staleness(tmp_path: Path):
    assert _retrieval_source_authority("memory/2026-04-01.md", None) <= 0.25
    assert _retrieval_source_authority("Projects/sequency-app.md", None) == 1.2
    assert _retrieval_edge_source_authority("user_confirmed") == 1.4
    assert _retrieval_edge_source_authority("candidate") == 0.7
    assert _retrieval_staleness("Due tomorrow Mar 31", "memory/2026-04-01.md") < 0.5
    assert _retrieval_staleness("Resolved sent paid on Mar 31", "memory/2026-04-01.md") <= 0.05

    db = tmp_path / "mneme.sqlite"
    _seed_quality_db(db)
    result = retrieve_context(db, "gws email calendar", max_items=4, hints=["calendar"])
    assert result["items"][0]["source_path"].startswith("gws://")
