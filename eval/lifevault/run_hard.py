#!/usr/bin/env python3
"""Hard-question eval with repeated runs, to separate real differences from run-to-run variance.

    python eval/lifevault/run_hard.py [--runs 3]

The 30 questions in hard.py go to:
    bm25    keyword baseline (deterministic, one run)
    fresh   act-1 cortex, no experience
    used    act-1 cortex after confirmed feedback on the 55 dev questions (as in run_use.py)

Perception and the dev-feedback phase are shared and cached (mind/answers), so every run starts from the same
brain. The recall of the hard questions is asked afresh in each run: run 1 uses the shared cache, and runs
2+ use their own folders (mind/runs/rN). Results go to results/hard.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

import hard  # noqa: E402
import run_baseline as rb  # noqa: E402
from mneme.cortex import AwaitingMind, Brain, FileMind  # noqa: E402
from mneme.cortex.senses import read_sources  # noqa: E402

DATA = HERE / "data"
MIND = HERE / "mind"
OUT = HERE / "results" / "hard.json"
METRICS = ("hit@k", "recall@k", "answer_in_ctx@k")


class Switch:
    """Sends tasks to whichever mind is current, so one brain can use a shared cache, then a per-run one."""

    def __init__(self, mind):
        self.target = mind

    def ask_many(self, tasks):
        return self.target.ask_many(tasks)


def _cortex(name: str, run_mind: FileMind, shared: FileMind, dev: list[dict], tests: list[dict], k: int, tmp: str) -> list[dict]:
    switch = Switch(shared)
    brain = Brain(Path(tmp) / f"{name}-{run_mind.root.name}.sqlite", switch)
    brain.ingest(read_sources(DATA))
    brain.perceive()
    if name == "used":
        answers = brain.recall_many([(q["question"], q["as_of"]) for q in dev], k=k)
        for q, trace, hits in zip(dev, brain.last_traces, answers):
            useful = [h.id for h in hits if set(h.refs) & set(q["evidence"])]
            if useful:
                brain.feedback(trace, useful=useful)
    switch.target = run_mind
    hits = brain.recall_many([(q["question"], q["as_of"]) for q in tests], k=k)
    return [rb.score(q, [{"refs": h.refs, "text": h.context_text()} for h in found], k) for q, found in zip(tests, hits)]


def run(runs: int, k: int = 8) -> int:
    shared = FileMind(MIND)
    run_minds = [shared] + [FileMind(MIND / "runs" / f"r{i}") for i in range(2, runs + 1)]
    for mind in run_minds:
        for stale in mind.outbox.glob("*.json"):
            stale.unlink()
    all_q = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    dev = [q for q in all_q if q["split"] == "dev"]
    tests = hard.questions()

    bm25 = rb.BM25(rb.load_documents())
    report: dict = {"k": k, "runs": runs, "systems": {"bm25": [[rb.score(q, bm25.search(q, k), k) for q in tests]]}}
    pending: dict[str, int] = defaultdict(int)
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("fresh", "used"):
            report["systems"][name] = []
            for mind in run_minds:
                try:
                    report["systems"][name].append(_cortex(name, mind, shared, dev, tests, k, tmp))
                except AwaitingMind as waiting:
                    for task_id in waiting.pending:
                        pending[f"{mind.root.relative_to(MIND) if mind.root != MIND else '.'}:{task_id.rsplit('-', 1)[0]}"] += 1
    if pending:
        print(f"AWAITING {sum(pending.values())} task(s): {dict(pending)}")
        return 2

    summary = {}
    for name, per_run in report["systems"].items():
        means = {m: [rb.summarise(rows)[m] for rows in per_run] for m in METRICS}
        summary[name] = {m: {"mean": round(statistics.mean(v), 3), "min": min(v), "max": max(v)} for m, v in means.items()}
        stable = defaultdict(int)
        for i in range(len(tests)):
            outcomes = {rows[i]["answer_in_ctx@k"] for rows in per_run}
            stable["always" if outcomes == {True} else "never" if outcomes == {False} else "sometimes"] += 1
        summary[name]["answer_in_ctx_per_question"] = dict(stable)
    report["summary"] = summary
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{'system':7} {'runs':>4}  " + "  ".join(f"{m:>22}" for m in METRICS) + "   always/sometimes/never")
    for name, s in summary.items():
        cells = "  ".join(f"{s[m]['mean']:>8} [{s[m]['min']}-{s[m]['max']}]".rjust(22) for m in METRICS)
        per_q = s["answer_in_ctx_per_question"]
        print(f"{name:7} {len(report['systems'][name]):>4}  {cells}   {per_q.get('always', 0)}/{per_q.get('sometimes', 0)}/{per_q.get('never', 0)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    raise SystemExit(run(parser.parse_args().runs))
