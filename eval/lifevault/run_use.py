#!/usr/bin/env python3
"""Learning-from-use eval: does confirmed experience help later questions?

    python eval/lifevault/run_use.py

Both systems start from the act-1 brain (data/, perceived from cached answers):

    fresh  no experience
    used   first answers the 55 dev questions, and the user confirms which returned memories were right
           (simulated with the dev answer key: useful = returned memories that are gold evidence)

Then both answer:
    reask    26 dev needs reworded (reask.py), never used for feedback
    holdout  the 26 held-out questions, never used for feedback

Like run_cortex.py this uses a deferred FileMind and advances as far as cached answers allow.
Results go to results/use.json.
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

import reask  # noqa: E402
import run_baseline as rb  # noqa: E402
from mneme.cortex import AwaitingMind, Brain, FileMind  # noqa: E402
from mneme.cortex.mind import MeteredMind  # noqa: E402
from mneme.cortex.senses import read_sources  # noqa: E402

DATA = HERE / "data"
OUT = HERE / "results" / "use.json"
RECALL_KINDS = ("zoom_areas", "zoom_topics", "skim_neurons", "read_neurons")


def run(k: int = 8) -> int:
    files = FileMind(HERE / "mind")
    for stale in files.outbox.glob("*.json"):
        stale.unlink()
    all_q = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    dev = [q for q in all_q if q["split"] == "dev"]
    tests = reask.questions(dev) + [q for q in all_q if q["split"] == "holdout"]
    report: dict = {"k": k, "systems": {}}
    pending: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("fresh", "used"):
            mind = MeteredMind(files)
            brain = Brain(Path(tmp) / f"{name}.sqlite", mind)
            try:
                brain.ingest(read_sources(DATA))
                brain.perceive()
                confirmed = 0
                if name == "used":
                    answers = brain.recall_many([(q["question"], q["as_of"]) for q in dev], k=k)
                    for q, trace, hits in zip(dev, brain.last_traces, answers):
                        useful = [h.id for h in hits if set(h.refs) & set(q["evidence"])]
                        if useful:
                            brain.feedback(trace, useful=useful)
                            confirmed += 1
                before = {kind: mind.chars[kind] for kind in RECALL_KINDS}
                hits = brain.recall_many([(q["question"], q["as_of"]) for q in tests], k=k)
            except AwaitingMind as waiting:
                pending += waiting.pending
                continue
            rows = [rb.score(q, [{"refs": h.refs, "text": h.context_text()} for h in found], k) for q, found in zip(tests, hits)]
            by_split = defaultdict(list)
            for row in rows:
                by_split[row["split"]].append(row)
            report["systems"][name] = {
                "confirmed_dev_answers": confirmed,
                "recall_tokens_per_question": sum(mind.chars[kind] - before[kind] for kind in RECALL_KINDS) // 4 // len(tests),
                "summary": {split: rb.summarise(r) for split, r in sorted(by_split.items())},
                "per_question": rows,
            }
    if pending:
        kinds: dict[str, int] = defaultdict(int)
        for task_id in pending:
            kinds[task_id.rsplit("-", 1)[0]] += 1
        print(f"AWAITING {len(pending)} task(s): {dict(kinds)}")
        return 2
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{'system':8} {'split':8} {'hit@k':>6} {'recall':>7} {'ans_ctx':>8} {'tokens/q':>9}")
    for name, data in report["systems"].items():
        for split, s in data["summary"].items():
            print(f"{name:8} {split:8} {s['hit@k']!s:>6} {s['recall@k']!s:>7} {s['answer_in_ctx@k']!s:>8} {data['recall_tokens_per_question']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
