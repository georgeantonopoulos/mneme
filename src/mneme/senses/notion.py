from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from ..core import now_iso
from .base import SenseEvent


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> str:
        ...


@dataclass
class CurlRunner:
    def run(self, args: list[str]) -> str:
        completed = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return completed.stdout


class NotionSense:
    """Collect Notion database pages as normalized Mneme sense events.

    This is intentionally thin: Notion is a sense, not a truth engine. Rows are
    converted into source packets that Mneme can cross-check against action
    candidates and connected graph nodes.
    """

    sense_type = "notion"

    def __init__(self, *, sense_id: str = "notion", database_id: str | None = None, access: str | None = None, runner: CommandRunner | None = None) -> None:
        self.sense_id = sense_id
        self.database_id = database_id or os.environ.get("NOTION_DATABASE_ID") or os.environ.get("MNEME_NOTION_DATABASE_ID")
        self.auth_value = access or os.environ.get("NOTION_TOKEN") or os.environ.get("MNEME_NOTION_TOKEN")
        self.runner = runner

    def commands(self, *, limit: int | None = None, redact: bool = True) -> list[list[str]]:
        if not self.database_id:
            raise RuntimeError("Notion sense missing database_id")
        if not self.auth_value:
            raise RuntimeError("Notion sense missing token")
        body = json.dumps({"page_size": int(limit or 25)})
        auth_header = "Authorization: Bearer ***" if redact else f"Authorization: Bearer {self.auth_value}"
        return [[
            "curl", "-sS", "-X", "POST",
            f"https://api.notion.com/v1/databases/{self.database_id}/query",
            "-H", auth_header,
            "-H", "Notion-Version: 2022-06-28",
            "-H", "Content-Type: application/json",
            "--data", body,
        ]]

    def dry_run(self, *, limit: int | None = None) -> dict:
        return {"sense_id": self.sense_id, "sense_type": self.sense_type, "commands": self.commands(limit=limit, redact=True)}

    def collect(self, *, since: str | None = None, limit: int | None = None) -> Iterable[SenseEvent]:
        if self.runner is not None:
            for cmd in self.commands(limit=limit, redact=False):
                output = self.runner.run(cmd)
                yield from self._events_from_output(output)
            return
        yield from self._events_from_output(self._query_database(limit=limit))

    def _query_database(self, *, limit: int | None = None) -> str:
        if not self.database_id:
            raise RuntimeError("Notion sense missing database_id")
        if not self.auth_value:
            raise RuntimeError("Notion sense missing token")
        body = json.dumps({"page_size": int(limit or 25)}).encode()
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{self.database_id}/query",
            data=body,
            headers={
                "Authorization": f"Bearer {self.auth_value}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(f"Notion API request failed with HTTP {exc.code}: {detail}") from exc

    def _events_from_output(self, output: str) -> Iterable[SenseEvent]:
        payload = json.loads(output)
        rows = payload.get("results", []) if isinstance(payload, dict) else payload
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                yield self._event_from_page(row)

    def _event_from_page(self, row: dict[str, Any]) -> SenseEvent:
        source_id = str(row.get("id") or hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:20])
        title, parts = _notion_page_text(row)
        text = "\n".join(parts).strip() or title or source_id
        digest = hashlib.sha1(f"{self.sense_id}:notion_page:{source_id}:{text[:200]}".encode()).hexdigest()[:24]
        return SenseEvent(
            id=digest,
            sense_id=self.sense_id,
            sense_type=self.sense_type,
            source_id=f"notion_page:{source_id}",
            source_uri=row.get("url"),
            observed_at=str(row.get("last_edited_time") or row.get("created_time") or now_iso()),
            title=title or "Notion page",
            text=text,
            tags=["notion_page"],
            event_type="notion_page",
            confidence=0.8,
            metadata={"notion_page_id": source_id, "last_edited_time": row.get("last_edited_time")},
        )


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("plain_text"), str):
            return value["plain_text"]
        if isinstance(value.get("name"), str):
            return value["name"]
        if "title" in value:
            return _plain_text(value["title"])
        if "rich_text" in value:
            return _plain_text(value["rich_text"])
        if "status" in value:
            return _plain_text(value["status"])
        if "select" in value:
            return _plain_text(value["select"])
        if "date" in value and isinstance(value["date"], dict):
            return " ".join(str(value["date"].get(k) or "") for k in ("start", "end")).strip()
        return " ".join(_plain_text(v) for v in value.values()).strip()
    if isinstance(value, list):
        return " ".join(_plain_text(v) for v in value).strip()
    if value is None:
        return ""
    return str(value)


def _notion_page_text(row: dict[str, Any]) -> tuple[str, list[str]]:
    raw_props = row.get("properties")
    props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
    parts: list[str] = []
    title = ""
    for name, prop in props.items():
        text = _plain_text(prop).strip()
        if not text:
            continue
        parts.append(f"{name}: {text}")
        if not title and (isinstance(prop, dict) and prop.get("type") == "title" or name.lower() in {"name", "title"}):
            title = text
    return title, parts
