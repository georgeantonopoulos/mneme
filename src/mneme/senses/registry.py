from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .gws import GwsSense
from .hermes_sessions import HermesSessionSense
from .markdown import MarkdownSense
from .notion import NotionSense

SENSE_TYPES = {
    "md": MarkdownSense,
    "markdown": MarkdownSense,
    "gws": GwsSense,
    "notion": NotionSense,
    "hermes_sessions": HermesSessionSense,
    "sessions": HermesSessionSense,
}


def available_senses() -> list[str]:
    return sorted({"md", "gws", "notion", "hermes_sessions"})


def get_sense_class(sense_type: str):
    try:
        return SENSE_TYPES[sense_type]
    except KeyError as exc:
        raise ValueError(f"unknown sense type: {sense_type}") from exc


def build_sense_from_config(entry: dict[str, Any]):
    sense_type = entry.get("type") or entry.get("sense_type")
    sense_id = entry.get("id") or sense_type
    config = dict(entry.get("config") or {})
    if sense_type in {"md", "markdown"}:
        path = config.get("path") or config.get("vault") or entry.get("vault")
        if not path:
            raise ValueError(f"markdown sense {sense_id!r} missing config.path")
        return MarkdownSense(sense_id=sense_id, vault=Path(path).expanduser(), follow_symlinks=bool(config.get("follow_symlinks", False)))
    if sense_type == "gws":
        return GwsSense(
            sense_id=sense_id,
            include_email=bool(config.get("email", config.get("include_email", True))),
            include_calendar=bool(config.get("calendar", config.get("include_calendar", True))),
            include_tasks=bool(config.get("tasks", config.get("include_tasks", True))),
            query=config.get("query"),
            calendar_window_days=int(config.get("calendar_window_days", 14)),
            task_filter=config.get("task_filter"),
        )
    if sense_type == "notion":
        return NotionSense(
            sense_id=sense_id,
            database_id=config.get("database_id"),
            access=config.get("token"),
        )
    if sense_type in {"hermes_sessions", "sessions"}:
        sessions_dir = config.get("path") or config.get("sessions_dir") or os.path.expanduser("~/.hermes/sessions")
        return HermesSessionSense(sense_id=sense_id, sessions_dir=Path(sessions_dir).expanduser(), limit=config.get("limit"))
    return get_sense_class(str(sense_type))(sense_id=sense_id, **config)
