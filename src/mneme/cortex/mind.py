"""The mind: the core's only connection to a language model, and agnostic about which.

The cortex never calls a model. It describes work as ``Task`` objects
(instructions, a JSON input and the JSON shape it expects back) and hands
batches of them to a ``Mind``. Anything that can answer a prompt with JSON can
be a mind:

    FileMind      writes tasks to an outbox folder and reads answers from an answers
                  folder. An outside worker (a person, a script, a sub-agent) fills it.
                  Raises ``AwaitingMind`` listing what is still unanswered; rerun after.
    FunctionMind  wraps any ``prompt -> text`` callable (an API client, a local model).

Task ids are content hashes, so answers are cached and runs are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class Task:
    kind: str
    instructions: str
    payload: dict
    reply_shape: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        blob = json.dumps([self.kind, self.instructions, self.payload, self.reply_shape], sort_keys=True, ensure_ascii=False)
        return f"{self.kind}-{hashlib.sha256(blob.encode()).hexdigest()[:16]}"

    def prompt(self) -> str:
        return (
            f"{self.instructions.strip()}\n\n"
            f"INPUT (JSON):\n{json.dumps(self.payload, ensure_ascii=False, indent=1)}\n\n"
            f"Reply with a single JSON object and nothing else, shaped like:\n{json.dumps(self.reply_shape, ensure_ascii=False, indent=1)}\n"
        )


class Mind(Protocol):
    def ask_many(self, tasks: list[Task]) -> list[dict]:
        """Answer every task, in order, as parsed JSON objects."""


class AwaitingMind(Exception):
    """Raised by a deferred mind when some tasks have no answer yet."""

    def __init__(self, pending: list[str], outbox: Path | None = None):
        self.pending = pending
        self.outbox = outbox
        super().__init__(f"{len(pending)} task(s) awaiting an answer" + (f" in {outbox}" if outbox else ""))


def parse_json_reply(text: str) -> dict:
    """Pull the JSON object out of a model reply (tolerates code fences and chatter)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("reply contains no JSON object")
    return json.loads(text[start : end + 1])


class FileMind:
    """Deferred mind backed by two folders: ``outbox/<task>.json`` and ``answers/<task>.json``."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.outbox = self.root / "outbox"
        self.answers = self.root / "answers"
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.answers.mkdir(parents=True, exist_ok=True)

    def answer_for(self, task: Task) -> dict | None:
        path = self.answers / f"{task.id}.json"
        if not path.exists():
            return None
        try:
            return parse_json_reply(path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            return None

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        results: list[dict | None] = []
        pending: list[str] = []
        for task in tasks:
            answer = self.answer_for(task)
            if answer is None:
                pending.append(task.id)
                (self.outbox / f"{task.id}.json").write_text(
                    json.dumps({"id": task.id, "kind": task.kind, "prompt": task.prompt()}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
            results.append(answer)
        if pending:
            raise AwaitingMind(pending, self.outbox)
        return results  # type: ignore[return-value]


class FunctionMind:
    """Immediate mind around any ``prompt -> reply text`` callable, with an optional answer cache."""

    def __init__(self, complete: Callable[[str], str], cache: FileMind | None = None):
        self.complete = complete
        self.cache = cache

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        out = []
        for task in tasks:
            cached = self.cache.answer_for(task) if self.cache else None
            if cached is None:
                reply = self.complete(task.prompt())
                cached = parse_json_reply(reply)
                if self.cache:
                    (self.cache.answers / f"{task.id}.json").write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
            out.append(cached)
        return out
