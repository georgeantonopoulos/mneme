from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from ..core import now_iso
from ..html_visible import extract_visible_text
from .base import SenseEvent


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> str:
        ...


@dataclass
class SubprocessRunner:
    def run(self, args: list[str]) -> str:
        if shutil.which(args[0]) is None:
            raise RuntimeError(f"{args[0]} command not found")
        completed = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return completed.stdout


class GwsSense:
    sense_type = "gws"

    def __init__(
        self,
        *,
        sense_id: str = "gws",
        include_email: bool = True,
        include_calendar: bool = True,
        include_tasks: bool = True,
        query: str | None = None,
        calendar_window_days: int = 14,
        task_filter: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.sense_id = sense_id
        self.include_email = include_email
        self.include_calendar = include_calendar
        self.include_tasks = include_tasks
        self.query = query
        self.calendar_window_days = calendar_window_days
        self.task_filter = task_filter
        self.runner = runner or SubprocessRunner()

    def commands(self, *, since: str | None = None, limit: int | None = None) -> list[list[str]]:
        cmds: list[list[str]] = []
        limit_n = int(limit or 25)
        if self.include_email:
            params: dict[str, Any] = {"userId": "me", "maxResults": limit_n}
            if self.query:
                params["q"] = self.query
            if since:
                params["q"] = f"{params.get('q', '')} after:{since}".strip()
            cmds.append(["gws", "gmail", "users", "messages", "list", "--params", json.dumps(params), "--format", "json"])
        if self.include_calendar:
            now = dt.datetime.now(dt.timezone.utc)
            time_min = since or now.isoformat().replace("+00:00", "Z")
            time_max = (now + dt.timedelta(days=self.calendar_window_days)).isoformat().replace("+00:00", "Z")
            params = {"calendarId": "primary", "maxResults": limit_n, "singleEvents": True, "orderBy": "startTime", "timeMin": time_min, "timeMax": time_max}
            cmds.append(["gws", "calendar", "events", "list", "--params", json.dumps(params), "--format", "json"])
        if self.include_tasks:
            params = {"tasklist": "@default", "maxResults": limit_n}
            cmd = ["gws", "tasks", "tasks", "list", "--params", json.dumps(params), "--format", "json"]
            if self.task_filter:
                # Google Tasks list does not expose arbitrary server-side text search;
                # keep this as metadata for callers/tests rather than inventing a flag.
                cmd += []
            cmds.append(cmd)
        return cmds

    def dry_run(self, *, since: str | None = None, limit: int | None = None) -> dict:
        return {"sense_id": self.sense_id, "sense_type": self.sense_type, "commands": self.commands(since=since, limit=limit)}

    def collect(self, *, since: str | None = None, limit: int | None = None) -> Iterable[SenseEvent]:
        for cmd in self.commands(since=since, limit=limit):
            output = self.runner.run(cmd)
            yield from self._events_from_output(cmd, output)

    def _events_from_output(self, cmd: list[str], output: str) -> Iterable[SenseEvent]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ValueError("gws output could not be parsed") from exc
        rows = _coerce_rows(payload)
        event_type = _event_type_from_cmd(cmd)
        for row in rows:
            if not isinstance(row, dict):
                continue
            yield self._event_from_row(event_type, row)

    def _event_from_row(self, event_type: str, row: dict[str, Any]) -> SenseEvent:
        source_id = str(row.get("id") or row.get("message_id") or row.get("event_id") or row.get("task_id") or hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:20])
        title = str(row.get("title") or row.get("subject") or row.get("summary") or row.get("name") or event_type).strip()
        text_parts = [
            title,
            str(row.get("from") or row.get("sender") or ""),
            str(row.get("when") or row.get("start") or row.get("due") or ""),
            str(row.get("snippet") or row.get("body") or row.get("description") or row.get("notes") or ""),
        ]
        text = "\n".join(part for part in text_parts if part).strip() or title
        if "<" in text and ">" in text:
            text = extract_visible_text(text)
        observed_at = str(row.get("observed_at") or row.get("date") or row.get("updated") or row.get("start") or now_iso())
        uri = row.get("uri") or row.get("url") or row.get("htmlLink") or row.get("link")
        digest = hashlib.sha1(f"{self.sense_id}:{event_type}:{source_id}:{text[:200]}".encode()).hexdigest()[:24]
        return SenseEvent(
            id=digest,
            sense_id=self.sense_id,
            sense_type=self.sense_type,
            source_id=f"{event_type}:{source_id}",
            source_uri=str(uri) if uri else None,
            observed_at=observed_at,
            title=title,
            text=text,
            links=[str(link) for link in row.get("links", [])] if isinstance(row.get("links"), list) else [],
            tags=[event_type],
            event_type=event_type,
            confidence=0.85,
            metadata={"gws": row},
        )


def _coerce_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "messages", "events", "tasks", "results", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


def _event_type_from_cmd(cmd: list[str]) -> str:
    joined = " ".join(cmd).lower()
    if "gmail" in joined or "mail" in joined:
        return "email_message"
    if "calendar" in joined:
        return "calendar_event"
    if "task" in joined:
        return "task"
    return "workspace_event"
