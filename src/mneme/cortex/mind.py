"""The mind: the core's only connection to a language model, and agnostic about which.

The cortex never calls a model. It describes work as ``Task`` objects
(instructions, a JSON input and the JSON shape it expects back) and hands
batches of them to a ``Mind``. Anything that can answer a prompt with JSON can
be a mind:

    FileMind      writes tasks to an outbox folder and reads answers from an answers
                  folder. An outside worker (a person, a script, a sub-agent) fills it.
                  Raises ``AwaitingMind`` listing what is still unanswered; rerun after.
    FunctionMind  wraps any ``prompt -> text`` callable.
    OpenAICompatibleMind  any OpenAI-compatible chat endpoint: Ollama (local or cloud),
                  LM Studio, vLLM, OpenRouter, Anthropic's compatibility endpoint...
    CommandMind   pipes each prompt through a shell command (e.g. ``claude -p``, ``llm``).
    RoleMind      routes task kinds to different minds (a cheap model for bulk perception,
                  a stronger one for recall).

``mind_from_config`` builds any of these from the ``mind`` block of Mneme's JSON config.
Task ids are content hashes, so answers are cached and runs are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import urllib.request
from collections import Counter
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
        # Stable parts first (instructions, reply shape) so providers can cache the prefix.
        return (
            f"{self.instructions.strip()}\n\n"
            f"Reply with a single JSON object and nothing else, shaped like:\n{_compact(self.reply_shape)}\n\n"
            f"INPUT (JSON):\n{_compact(self.payload)}\n"
        )


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


class OpenAICompatibleMind:
    """Any OpenAI-compatible ``/chat/completions`` endpoint, with JSON output requested."""

    def __init__(self, base_url: str, model: str, *, api_key_env: str | None = None, timeout: int = 300,
                 temperature: float = 0.0, cache: FileMind | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self._bearer = os.environ.get(api_key_env, "") if api_key_env else ""
        self.timeout = timeout
        self.temperature = temperature
        self._inner = FunctionMind(self.complete, cache=cache)

    def complete(self, prompt: str) -> str:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature, "response_format": {"type": "json_object"}}
        headers = {"Content-Type": "application/json"}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())["choices"][0]["message"]["content"]

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        return self._inner.ask_many(tasks)


class CommandMind:
    """Pipe each prompt to a shell command on stdin and read the reply from stdout."""

    def __init__(self, command: str, *, timeout: int = 600, cache: FileMind | None = None):
        self.argv = shlex.split(command)
        self.timeout = timeout
        self._inner = FunctionMind(self.complete, cache=cache)

    def complete(self, prompt: str) -> str:
        done = subprocess.run(self.argv, input=prompt, capture_output=True, text=True, timeout=self.timeout, check=True)
        return done.stdout

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        return self._inner.ask_many(tasks)


class RoleMind:
    """Send each task kind to its own mind, falling back to a default."""

    def __init__(self, default: Mind, roles: dict[str, Mind] | None = None):
        self.default = default
        self.roles = roles or {}

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        answers: dict[int, dict] = {}
        groups: dict[int, list[int]] = {}
        minds: dict[int, Mind] = {}
        for i, task in enumerate(tasks):
            mind = self.roles.get(task.kind, self.default)
            groups.setdefault(id(mind), []).append(i)
            minds[id(mind)] = mind
        for key, indexes in groups.items():
            for i, answer in zip(indexes, minds[key].ask_many([tasks[i] for i in indexes])):
                answers[i] = answer
        return [answers[i] for i in range(len(tasks))]


class MeteredMind:
    """Counts calls and prompt characters per task kind (characters / 4 ~ tokens)."""

    def __init__(self, inner: Mind):
        self.inner = inner
        self.calls: Counter = Counter()
        self.chars: Counter = Counter()

    def ask_many(self, tasks: list[Task]) -> list[dict]:
        for task in tasks:
            self.calls[task.kind] += 1
            self.chars[task.kind] += len(task.prompt())
        return self.inner.ask_many(tasks)


def mind_from_config(config: dict, *, cache_dir: Path | str | None = None) -> Mind:
    """Build a mind from a config block such as::

        {"provider": "openai-compatible", "base_url": "http://localhost:11434/v1", "model": "qwen3:8b",
         "roles": {"zoom_neurons": {"model": "qwen3:30b"}}}

    Providers: "openai-compatible", "command" (``"command": "claude -p"``) and "file" (``"path": ...``).
    A role entry overrides any keys of the default block for those task kinds.
    """
    cache = FileMind(cache_dir) if cache_dir else None

    def build(block: dict) -> Mind:
        provider = block.get("provider", "openai-compatible")
        if provider == "openai-compatible":
            return OpenAICompatibleMind(block["base_url"], block["model"], api_key_env=block.get("api_key_env"),
                                        timeout=int(block.get("timeout", 300)), cache=cache)
        if provider == "command":
            return CommandMind(block["command"], timeout=int(block.get("timeout", 600)), cache=cache)
        if provider == "file":
            return FileMind(block["path"])
        raise ValueError(f"unknown mind provider: {provider}")

    base = {k: v for k, v in config.items() if k != "roles"}
    default = build(base)
    roles = {kind: build({**base, **override}) for kind, override in (config.get("roles") or {}).items()}
    return RoleMind(default, roles) if roles else default
