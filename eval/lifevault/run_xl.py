#!/usr/bin/env python3
"""Recall on LifeVault XL: the same brain, a haystack about 5x bigger.

    python eval/lifevault/run_xl.py

Asks BM25 and the cortex (Haiku mind, deferred FileMind as in run_cortex.py) about data_xl/:
    dev, holdout          the 81 hand-written questions, unchanged, so the scores compare directly with the
                          402-memory vault in CORTEX.md
    xl-dev, xl-holdout    every 4th generated question (64), drawn from storylines that exist only in XL

Results go to results/xl.json.
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

DATA = HERE / "data_xl"
OUT = HERE / "results" / "xl.json"
PERCEPTION = ("regions", "perceive", "topic_gist", "area_gist")
RECALL = ("zoom_areas", "zoom_topics", "skim_neurons", "read_neurons")


def selected() -> list[dict]:
    questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    original = [q for q in questions if q["split"] in ("dev", "holdout")]
    generated = [q for q in questions if q["split"].startswith("xl-")]
    return original + generated[::4]


def run(k: int = 8) -> int:
    files = FileMind(HERE / "mind")
    for stale in files.outbox.glob("*.json"):
        stale.unlink()
    questions = selected()
    bm25 = rb.BM25(rb.load_documents(DATA))
    rows = {"bm25": [rb.score(q, bm25.search(q, k), k) for q in questions]}
    mind = MeteredMind(files)
    with tempfile.TemporaryDirectory() as tmp:
        brain = Brain(Path(tmp) / "xl.sqlite", mind)
        brain.ingest(read_sources(DATA))
        try:
            perceived = brain.perceive()
            hits = brain.recall_many([(q["question"], q["as_of"]) for q in questions], k=k)
        except AwaitingMind as waiting:
            kinds: dict[str, int] = defaultdict(int)
            for task_id in waiting.pending:
                kinds[task_id.rsplit("-", 1)[0]] += 1
            print(f"AWAITING {len(waiting.pending)} task(s): {dict(kinds)}")
            return 2
        neurons = brain.conn.execute("SELECT count(*) FROM neurons").fetchone()[0]
        regions = dict(brain.conn.execute("SELECT level, count(*) FROM regions GROUP BY level").fetchall())
    rows["cortex"] = [rb.score(q, [{"refs": h.refs, "text": h.context_text()} for h in found], k) for q, found in zip(questions, hits)]
    report = {"k": k, "neurons": neurons, "areas": regions.get(1, 0), "topics": regions.get(2, 0),
              "perception_tokens": sum(mind.chars[x] for x in PERCEPTION) // 4,
              "recall_tokens_per_question": sum(mind.chars[x] for x in RECALL) // 4 // len(questions), "systems": {}}
    for name, scored in rows.items():
        by_split = defaultdict(list)
        for row in scored:
            by_split[row["split"]].append(row)
        report["systems"][name] = {"summary": {s: rb.summarise(r) for s, r in sorted(by_split.items())}, "per_question": scored}
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{neurons} neurons, {report['areas']} areas, {report['topics']} topics; perception {report['perception_tokens']:,} tokens, "
          f"recall {report['recall_tokens_per_question']:,} tokens/question")
    print(f"{'system':7} {'split':11} {'hit@k':>6} {'recall':>7} {'ans_ctx':>8}")
    for name, data in report["systems"].items():
        for split, s in data["summary"].items():
            print(f"{name:7} {split:11} {s['hit@k']!s:>6} {s['recall@k']!s:>7} {s['answer_in_ctx@k']!s:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
