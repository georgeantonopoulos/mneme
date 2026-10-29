#!/usr/bin/env python3
"""Drive the cortex over LifeVault with a deferred FileMind.

    python eval/lifevault/run_cortex.py            # advance as far as cached answers allow

Each run replays cached answers from eval/lifevault/mind/answers and stops at the
first stage with unanswered tasks, listing them in eval/lifevault/mind/outbox.
Any LLM can answer them (one JSON file per task id); rerun to continue. When
every stage is answered, recall results are written for run_baseline.py.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.dont_write_bytecode = True

from mneme.cortex import AwaitingMind, Brain, FileMind  # noqa: E402

DATA = HERE / "data"
MIND = HERE / "mind"
RECALL = HERE / "results" / "cortex_recall.json"


def run(k: int = 8) -> int:
    mind = FileMind(MIND)
    for stale in mind.outbox.glob("*.json"):
        stale.unlink()
    questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        brain = Brain(Path(tmp) / "cortex.sqlite", mind)
        print(json.dumps(brain.ingest_sources(DATA)))
        try:
            print(json.dumps(brain.perceive()))
            results = brain.recall_many([(q["question"], q["as_of"]) for q in questions], k=k)
        except AwaitingMind as waiting:
            kinds: dict[str, int] = {}
            for task_id in waiting.pending:
                kinds[task_id.rsplit("-", 1)[0]] = kinds.get(task_id.rsplit("-", 1)[0], 0) + 1
            print(f"AWAITING {len(waiting.pending)} task(s): {kinds}")
            return 2
    RECALL.parent.mkdir(parents=True, exist_ok=True)
    RECALL.write_text(json.dumps({q["id"]: [{"refs": h.refs, "text": h.context_text()} for h in hits]
                                  for q, hits in zip(questions, results)}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"recall complete for {len(questions)} questions -> {RECALL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
