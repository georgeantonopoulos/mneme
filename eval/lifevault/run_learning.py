#!/usr/bin/env python3
"""Learning eval: does the cortex keep up when new memories arrive?

    python eval/lifevault/run_learning.py

Both systems start from the act-1 brain (data/, perceived from cached answers):

    stale        never updated; answers the act-2 questions with act-1 memory (the no-learning floor)
    incremental  ingests data_act2/ incrementally, perceives only what is new or changed, then answers

Questions (data_act2/questions.json):
    act2             16 questions about what changed, what is new, user corrections, and the past
    act2_regression  10 unchanged act-1 questions re-asked at the act-2 "now"

Like run_cortex.py this uses a deferred FileMind: each run advances as far as cached answers allow and
lists what is waiting in eval/lifevault/mind/outbox. Results go to results/learning.json.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

import run_baseline as rb  # noqa: E402
from mneme.cortex import AwaitingMind, Brain, FileMind  # noqa: E402
from mneme.cortex.mind import MeteredMind  # noqa: E402
from mneme.cortex.senses import read_sources  # noqa: E402

ACT1 = HERE / "data"
ACT2 = HERE / "data_act2"
OUT = HERE / "results" / "learning.json"
PERCEPTION = ("regions", "perceive", "topic_gist", "area_gist")


def _tokens(mind: MeteredMind, kinds) -> int:
    return sum(mind.chars[k] for k in kinds) // 4


def run(k: int = 8) -> int:
    files = FileMind(HERE / "mind")
    for stale in files.outbox.glob("*.json"):
        stale.unlink()
    questions = json.loads((ACT2 / "questions.json").read_text(encoding="utf-8"))
    asks = [(q["question"], q["as_of"]) for q in questions]
    report: dict = {"k": k, "systems": {}}
    pending: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("stale", "incremental"):
            mind = MeteredMind(files)
            brain = Brain(Path(tmp) / f"{name}.sqlite", mind)
            try:
                brain.ingest(read_sources(ACT1))
                brain.perceive()
                act1_cost = _tokens(mind, PERCEPTION)
                update = {}
                if name == "incremental":
                    update = brain.ingest(read_sources(ACT2), incremental=True)
                    before = {kind: mind.chars[kind] for kind in PERCEPTION}
                    update.update(brain.perceive())
                    update["update_tokens"] = sum(mind.chars[kind] - before[kind] for kind in PERCEPTION) // 4
                    update["full_rebuild_tokens_estimate"] = act1_cost
                hits = brain.recall_many(asks, k=k)
            except AwaitingMind as waiting:
                pending += waiting.pending
                continue
            rows = [rb.score(q, [{"refs": h.refs, "text": h.context_text()} for h in found], k) for q, found in zip(questions, hits)]
            by_split, by_cat = defaultdict(list), defaultdict(list)
            for row in rows:
                by_split[row["split"]].append(row)
                if row["split"] == "act2":
                    by_cat[row["category"]].append(row)
            report["systems"][name] = {
                "update": update,
                "summary": {split: rb.summarise(r) for split, r in sorted(by_split.items())},
                "by_category": {cat: rb.summarise(r) for cat, r in sorted(by_cat.items())},
                "per_question": rows,
            }
    if pending:
        kinds: dict[str, int] = defaultdict(int)
        for task_id in pending:
            kinds[task_id.rsplit("-", 1)[0]] += 1
        print(f"AWAITING {len(pending)} task(s): {dict(kinds)}")
        return 2
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{'system':12} {'split':16} {'hit@k':>6} {'ans_ctx':>8} {'stale':>6}")
    for name, data in report["systems"].items():
        for split, s in data["summary"].items():
            print(f"{name:12} {split:16} {s['hit@k']!s:>6} {s['answer_in_ctx@k']!s:>8} {s['stale_in_ctx@k']!s:>6}")
    inc = report["systems"]["incremental"]["update"]
    print(f"update: {inc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
