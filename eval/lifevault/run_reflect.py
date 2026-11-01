#!/usr/bin/env python3
"""Proactive eval: what does the brain raise, retire and connect while idle?

    python eval/lifevault/run_reflect.py [--runs 3]

Each run:
    act 1  perceive data/ (cached), reflect at 2026-10-29 18:00, score the open thoughts and the new synapses
    act 2  learn data_act2/ incrementally (cached), reflect again at 2026-11-12 18:00 with act-1 thoughts still
           open, and score again: new items found, and resolved items that are still being raised

Scored against proactive.py, which was written before the reflection code. Perception answers are shared;
reflection answers are cached per run (run 1 in mind/answers, later runs in mind/runs/rN), so runs differ
only in the mind's reflection choices. Results go to results/reflect.json.
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

import proactive as P  # noqa: E402
from mneme.cortex import AwaitingMind, Brain, FileMind  # noqa: E402
from mneme.cortex.senses import read_sources  # noqa: E402

MIND = HERE / "mind"
OUT = HERE / "results" / "reflect.json"


class LayeredMind(FileMind):
    """A run's own answers first, then the shared cache; anything unanswered is queued in the run's outbox."""

    def __init__(self, root: Path, shared: FileMind):
        super().__init__(root)
        self.shared = shared

    def answer_for(self, task):
        return super().answer_for(task) or (self.shared.answer_for(task) if self.shared.root != self.root else None)


def _matches(text: str, groups: list[list[str]]) -> bool:
    text = text.lower()
    return all(any(s.lower() in text for s in group) for group in groups)


def score(thoughts: list[dict], surface: list[dict], stale: list[dict]) -> dict:
    found, rows = set(), []
    for t in thoughts:
        refs = {r for hit in t["evidence"] for r in hit.refs}
        items = [i["id"] for i in surface if refs & set(i["evidence"]) or _matches(t["text"], i["match"])]
        stales = [s["id"] for s in stale if _matches(t["text"], s["match"])]
        found |= set(items)
        rows.append({"text": t["text"], "kind": t["kind"], "urgency": t["urgency"], "items": items, "stale": stales})
    return {"thoughts": len(thoughts), "surfaced": sorted(found), "recall": round(len(found) / len(surface), 3),
            "stale": sum(1 for r in rows if r["stale"]), "unmatched": sum(1 for r in rows if not r["items"] and not r["stale"]),
            "per_thought": rows}


def link_score(brain: Brain) -> dict:
    refs = {r["id"]: set(json.loads(r["refs"])) for r in brain.conn.execute("SELECT id, refs FROM neurons")}
    made = brain.conn.execute("SELECT src, dst, relation FROM synapses WHERE made_by = 'reflect'").fetchall()
    found = sorted({link["id"] for link in P.LINKS for s, d, _ in made
                    if link["a"] in refs.get(s, ()) and link["b"] in refs.get(d, ())})
    return {"made": len(made) // 2, "gold_found": found, "gold_recall": round(len(found) / len(P.LINKS), 3),
            "examples": [{"src": brain.conn.execute("SELECT title FROM neurons WHERE id = ?", (s,)).fetchone()[0],
                          "dst": brain.conn.execute("SELECT title FROM neurons WHERE id = ?", (d,)).fetchone()[0], "relation": rel}
                         for s, d, rel in made[::2][:12]]}


def one_run(mind, tmp: str, name: str) -> dict:
    brain = Brain(Path(tmp) / f"{name}.sqlite", mind)
    brain.ingest(read_sources(HERE / "data"))
    brain.perceive()
    brain.reflect(now=P.ACT1_NOW)
    act1 = score(brain.thoughts(), P.ACT1_SURFACE, P.ACT1_STALE)
    links = link_score(brain)
    brain.ingest(read_sources(HERE / "data_act2"), incremental=True)
    brain.perceive()
    stats = brain.reflect(now=P.ACT2_NOW)
    act2 = score(brain.thoughts(), P.ACT2_SURFACE, P.ACT2_STALE)
    act2["retired"] = stats["retired"]
    return {"act1": act1, "links": links, "act2": act2}


def run(runs: int) -> int:
    shared = FileMind(MIND)
    minds = [LayeredMind(MIND if i == 1 else MIND / "runs" / f"r{i}", shared) for i in range(1, runs + 1)]
    for mind in minds:
        for stale in mind.outbox.glob("*.json"):
            stale.unlink()
    results, pending = [], defaultdict(int)
    with tempfile.TemporaryDirectory() as tmp:
        for i, mind in enumerate(minds, 1):
            try:
                results.append(one_run(mind, tmp, f"r{i}"))
            except AwaitingMind as waiting:
                for task_id in waiting.pending:
                    pending[f"r{i}:{task_id.rsplit('-', 1)[0]}"] += 1
    if pending:
        print(f"AWAITING {sum(pending.values())} task(s): {dict(pending)}")
        return 2
    mean = lambda xs: round(statistics.mean(xs), 3)  # noqa: E731
    summary = {
        "act1_recall": mean([r["act1"]["recall"] for r in results]), "act1_stale": mean([r["act1"]["stale"] for r in results]),
        "act1_thoughts": mean([r["act1"]["thoughts"] for r in results]),
        "act2_recall": mean([r["act2"]["recall"] for r in results]), "act2_stale": mean([r["act2"]["stale"] for r in results]),
        "act2_thoughts": mean([r["act2"]["thoughts"] for r in results]), "act2_retired": mean([r["act2"]["retired"] for r in results]),
        "links_made": mean([r["links"]["made"] for r in results]), "gold_link_recall": mean([r["links"]["gold_recall"] for r in results]),
    }
    OUT.write_text(json.dumps({"runs": runs, "summary": summary, "per_run": results}, indent=1) + "\n", encoding="utf-8")
    for i, r in enumerate(results, 1):
        print(f"run {i}: act1 {r['act1']['surfaced']} stale={r['act1']['stale']} n={r['act1']['thoughts']} | "
              f"links {r['links']['gold_found']} made={r['links']['made']} | act2 {r['act2']['surfaced']} "
              f"stale={r['act2']['stale']} n={r['act2']['thoughts']} retired={r['act2']['retired']}")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    raise SystemExit(run(parser.parse_args().runs))
