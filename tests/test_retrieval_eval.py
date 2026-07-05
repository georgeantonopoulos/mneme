from __future__ import annotations

from pathlib import Path

from mneme import reteval


def test_demo_eval_produces_metrics():
    report = reteval.run_demo(k=3)
    # Structural: every metric present and in range.
    for key in ("hit@k", "mrr", "forbidden_rate", "min_items_rate", "score"):
        assert key in report
        assert 0.0 <= report[key] <= 1.0
    assert report["cases"] == len(reteval.DEMO_CASES)


def test_demo_eval_meets_baseline():
    """The number to watch. If a scorer change regresses retrieval, this drops.

    Baselines are deliberately conservative so the gate catches real regressions
    without flapping. Raise them as the scorer improves.
    """

    report = reteval.run_demo(k=3)
    assert report["forbidden_rate"] == 0.0, report["failures"]
    assert report["min_items_rate"] == 1.0, report["failures"]
    assert report["hit@k"] >= 0.8, report["failures"]
    assert report["score"] >= 0.75, report


def test_run_retrieval_eval_on_seeded_db(tmp_path: Path):
    db = tmp_path / "reteval.sqlite"
    reteval.seed_demo_db(db)
    report = reteval.run_retrieval_eval(db, reteval.DEMO_CASES, k=3)
    assert report["score"] >= 0.75

