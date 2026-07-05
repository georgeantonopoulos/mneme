from __future__ import annotations

"""Scored retrieval evaluation.

``tests/test_retrieval_quality.py`` already encodes golden cases, but it asserts
them *binarily* (is the expected item in the top-3? does a forbidden pattern
appear in the top-1?). That catches a hard regression but produces no number you
can watch move when you tune the scorer — so any change to
``retrieve_context`` weighting is effectively evaluated by vibes.

This module turns the same golden cases into metrics:

* ``hit@k``            — expected source path present in the top-k
* ``mrr``             — reciprocal rank of the first expected source path
* ``forbidden_rate``  — fraction of cases whose top result trips a forbidden pattern
* ``min_items_rate``  — fraction of cases returning at least ``min_expected_items``
* ``score``           — composite in [0,1]: mean(hit@k, mrr, 1-forbidden_rate)

Run standalone against the bundled fixture:

    mneme eval retrieval --demo

or against a real DB with a JSON case file:

    mneme eval retrieval --db mneme.sqlite --cases cases.json
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RetrievalCase:
    query: str
    expected_source_paths: list[str]
    expected_node_names: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    min_expected_items: int = 1
    hints: list[str] = field(default_factory=lambda: ["current", "urgent", "deadline"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalCase":
        return cls(
            query=data["query"],
            expected_source_paths=list(data.get("expected_source_paths", [])),
            expected_node_names=list(data.get("expected_node_names", [])),
            forbidden_patterns=list(data.get("forbidden_patterns", [])),
            min_expected_items=int(data.get("min_expected_items", 1)),
            hints=list(data.get("hints", ["current", "urgent", "deadline"])),
        )


def _item_text(item: dict[str, Any]) -> str:
    return f"{item.get('title') or ''} {item.get('source_path') or ''} {item.get('snippet') or ''}"


def score_case(items: list[dict[str, Any]], case: RetrievalCase, *, k: int) -> dict[str, Any]:
    top_k = items[:k]
    rank = None
    for idx, item in enumerate(top_k, start=1):
        text = _item_text(item)
        if any(path in text for path in case.expected_source_paths):
            rank = idx
            break
    hit = rank is not None
    forbidden_hit = False
    if items:
        top_text = _item_text(items[0])
        forbidden_hit = any(re.search(p, top_text, re.I) for p in case.forbidden_patterns)
    return {
        "query": case.query,
        "hit": hit,
        "rank": rank,
        "reciprocal_rank": (1.0 / rank) if rank else 0.0,
        "forbidden_hit": forbidden_hit,
        "returned": len(items),
        "min_items_ok": len(items) >= case.min_expected_items,
        "node_name_ok": any(name in "\n".join(_item_text(i) for i in items[:3]) for name in case.expected_node_names) if case.expected_node_names else True,
    }


def run_retrieval_eval(db_path: Path | str, cases: list[RetrievalCase], *, k: int = 3, max_items: int = 6) -> dict[str, Any]:
    from mneme.core import retrieve_context

    per_case = []
    for case in cases:
        result = retrieve_context(db_path, case.query, max_items=max_items, hints=case.hints)
        per_case.append(score_case(result.get("items", []), case, k=k))

    n = len(per_case) or 1
    hit_rate = sum(1 for c in per_case if c["hit"]) / n
    mrr = sum(c["reciprocal_rank"] for c in per_case) / n
    forbidden_rate = sum(1 for c in per_case if c["forbidden_hit"]) / n
    min_items_rate = sum(1 for c in per_case if c["min_items_ok"]) / n
    node_name_rate = sum(1 for c in per_case if c["node_name_ok"]) / n
    score = (hit_rate + mrr + (1.0 - forbidden_rate)) / 3.0

    return {
        "k": k,
        "cases": len(per_case),
        "hit@k": round(hit_rate, 4),
        "mrr": round(mrr, 4),
        "forbidden_rate": round(forbidden_rate, 4),
        "min_items_rate": round(min_items_rate, 4),
        "node_name_rate": round(node_name_rate, 4),
        "score": round(score, 4),
        "failures": [c for c in per_case if not c["hit"] or c["forbidden_hit"] or not c["min_items_ok"]],
        "per_case": per_case,
    }


# --- Self-contained fixture so the harness runs without the test module -------

DEMO_CASES = [
    RetrievalCase("Sequency App", ["Projects/sequency-app.md"], ["Sequency App"], [r"old daily"]),
    RetrievalCase("Cassini broken window", ["vendors/cassini-property.md"], ["Cassini Broken Window"], [r"resolved complaint"]),
    RetrievalCase("Chepstow House school fees", ["Projects/chepstow-house-fees.md"], ["Chepstow House School Fees"], [r"April deadline"]),
    RetrievalCase("due tomorrow", ["gws://tasks/fresh-due-tomorrow"], ["Fresh Due Tomorrow"], [r"Mar 31"]),
    RetrievalCase("urgent deadline", ["email://inbox/urgent-deadline"], ["Fresh Urgent Deadline"], [r"Mar 31"]),
    RetrievalCase("gws email calendar", ["gws://calendar/source-authority"], ["GWS Calendar Item"], [r"old memory"]),
]


def seed_demo_db(db_path: Path) -> None:
    from mneme.core import add_observation, init_db, upsert_node

    conn = sqlite3.connect(db_path)
    init_db(conn)

    def obs(name: str, path: str, text: str, kind: str = "blocked", score: float = 8.0, node_type: str = "project") -> None:
        node_id = upsert_node(conn, node_type, name, path, 0.95)
        add_observation(conn, node_id, kind, text, path, score)

    obs("Sequency App", "Projects/sequency-app.md", "Sequency App launch partner notes and active follow up list.")
    obs("Cassini Broken Window", "vendors/cassini-property.md", "Cassini broken window open repair issue, awaiting landlord response.", kind="risk", node_type="vendor")
    obs("Chepstow House School Fees", "Projects/chepstow-house-fees.md", "Chepstow House school fees current payment plan and finance contact.", node_type="finance")
    obs("Fresh Due Tomorrow", "gws://tasks/fresh-due-tomorrow", "Due tomorrow: call current supplier about booking.", node_type="event")
    obs("Fresh Urgent Deadline", "email://inbox/urgent-deadline", "Urgent deadline from email: submit current form.", kind="risk", node_type="event")
    obs("GWS Calendar Item", "gws://calendar/source-authority", "gws email calendar sources contain the live appointment.", node_type="event")
    # Stale distractors that must not outrank the live items.
    for name, path, text in [
        ("Sequency Daily", "archive/daily/2026-03-28.md", "Sequency App old daily archived note."),
        ("Cassini Complaint", "archive/daily/2026-03-28.md", "Cassini broken window resolved complaint sent."),
        ("Chepstow Deadline", "daily/2026-04-01.md", "Chepstow House school fees April deadline summary paid."),
        ("Old Urgent", "daily/2026-03-31.md", "Urgent deadline due tomorrow Mar 31."),
        ("Old GWS Memory", "memory/2026-04-01.md", "gws email calendar old memory summary."),
    ]:
        obs(name, path, text, score=9.5)
    conn.commit()
    conn.close()


def run_demo(*, k: int = 3) -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "reteval.sqlite"
        seed_demo_db(db)
        return run_retrieval_eval(db, DEMO_CASES, k=k)


def load_cases(path: Path) -> list[RetrievalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RetrievalCase.from_dict(item) for item in data]

