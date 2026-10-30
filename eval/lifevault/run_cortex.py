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
from mneme.cortex.mind import MeteredMind  # noqa: E402

DATA = HERE / "data"
MIND = HERE / "mind"
RECALL = HERE / "results" / "cortex_recall.json"
TOKENS = HERE / "results" / "cortex_tokens.json"
PERCEPTION_KINDS = ("regions", "perceive", "topic_gist", "area_gist")
RECALL_KINDS = ("zoom_areas", "zoom_topics", "zoom_neurons", "skim_neurons", "read_neurons")


def run(k: int = 8) -> int:
    files = FileMind(MIND)
    for stale in files.outbox.glob("*.json"):
        stale.unlink()
    mind = MeteredMind(files)
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
    tokens = {
        "note": "prompt tokens estimated as characters / 4",
        "perception_tokens": sum(mind.chars[k] for k in PERCEPTION_KINDS) // 4,
        "perception_calls": sum(mind.calls[k] for k in PERCEPTION_KINDS),
        "recall_tokens_per_question": sum(mind.chars[k] for k in RECALL_KINDS) // 4 // len(questions),
        "recall_calls_per_question": sum(mind.calls[k] for k in RECALL_KINDS) / len(questions),
        "by_kind": {k: {"calls": mind.calls[k], "tokens": mind.chars[k] // 4} for k in sorted(mind.calls)},
    }
    TOKENS.write_text(json.dumps(tokens, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in tokens.items() if k != "by_kind"}))
    print(f"recall complete for {len(questions)} questions -> {RECALL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
