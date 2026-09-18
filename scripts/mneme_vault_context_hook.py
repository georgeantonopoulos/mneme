#!/usr/bin/env python3
"""Generic Hermes pre-session vault-context hook.

Bridges a vault (via optional ``obsidian-cli``) and the Mneme graph into the
Hermes memory directory at session start, using the public ``mneme`` CLI with
the optional Jev advisory router enabled (``--router jev``). The router only
re-orders retrieval results; it never decides truth and degrades silently to
the deterministic ordering when unavailable.

Configuration (environment variables, all optional):
  HERMES_HOME           Hermes home directory (default: ~/.hermes)
  MNEME_DB              Path to the Mneme SQLite DB (default: mneme CLI config)
  MNEME_BUDGET          Retrieval budget in characters (default: 2500)
  MNEME_MAX_ITEMS       Max retrieval items (default: 8)
  MNEME_THINK_ROUTER    Advisory router override; default "jev", "" disables
  OBSIDIAN_CLI          Path to obsidian-cli (default: /usr/local/bin/obsidian-cli)
  VAULT_SNAPSHOT_SECTIONS  Comma-separated vault sections to include
                          (default: "MEMORY.md,USER.md,daily,status")

Deploy by copying this file to $HERMES_HOME/hooks/vault-context/handler.py
(or keep a thin wrapper that imports it) and registering the hook for the
``session:start`` event. It writes $HERMES_HOME/memories/obsidian-vault.md.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

MAX_SECTION_CHARS = 5500
RETRIEVAL_CLIP_CHARS = 2000


def _clip(text: str, limit: int = MAX_SECTION_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n\n...[truncated {len(text) - limit} chars]"


def _run_obsidian(cli: str, args: list[str], timeout: int = 12) -> str:
    if not cli or not os.path.isfile(cli):
        return "[obsidian-cli not configured; skipping vault section]"
    try:
        proc = subprocess.run(
            [cli, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except Exception as exc:
        return f"[obsidian-cli failed: {exc}]"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return f"[obsidian-cli exited {proc.returncode}: {(proc.stderr or out)[:200]}]"
    return out


def _run_mneme_retrieve(prompt: str) -> str:
    """Routed Mneme retrieval via the public CLI; silent fallback on failure."""
    budget = os.environ.get("MNEME_BUDGET", "2500")
    max_items = os.environ.get("MNEME_MAX_ITEMS", "8")
    router = os.environ.get("MNEME_THINK_ROUTER", "jev")
    cmd = [
        "mneme", "retrieve",
        "--prompt", prompt,
        "--budget", budget,
        "--max-items", max_items,
    ]
    if router:
        cmd += ["--router", router]
    env = dict(os.environ)
    if router:
        env.setdefault("MNEME_THINK_ROUTER", router)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False, env=env
        )
    except Exception as exc:
        return f"[Mneme retrieval failed: {exc}]"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return f"[Mneme retrieval error: {((proc.stderr or '').strip() or out)[:300]}]"
    if not out:
        return "[Mneme: no results]"
    try:
        data = json.loads(out)
    except Exception:
        return _clip(out, RETRIEVAL_CLIP_CHARS)
    md = data.get("markdown") if isinstance(data, dict) else None
    router_report = data.get("router") if isinstance(data, dict) else None
    section = _clip(md if md else out, RETRIEVAL_CLIP_CHARS)
    if isinstance(router_report, dict):
        note = f"\n\n[router: {router_report.get('mode')} applied={router_report.get('applied')}]"
        section = _clip(section + note, RETRIEVAL_CLIP_CHARS)
    return section


def _build_snapshot(event_type: str, context: Dict[str, Any]) -> str:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    cli = os.environ.get("OBSIDIAN_CLI", "/usr/local/bin/obsidian-cli")
    sections = os.environ.get(
        "VAULT_SNAPSHOT_SECTIONS", "MEMORY.md,USER.md,daily,status"
    ).split(",")

    parts: dict[str, str] = {}
    for name in [s.strip() for s in sections if s.strip()]:
        if name == "MEMORY.md":
            parts["MEMORY.md"] = _clip(_run_obsidian(cli, ["read", "path=MEMORY.md"]))
        elif name == "USER.md":
            parts["USER.md"] = _clip(_run_obsidian(cli, ["read", "path=USER.md"]), 3500)
        elif name == "daily":
            parts["daily"] = _clip(_run_obsidian(cli, ["daily:read"]), 3500)
        elif name == "status":
            parts["status"] = _clip(_run_obsidian(cli, ["status"]), 2500)

    platform = context.get("platform", "")
    session_id = context.get("session_id", "")
    chat_title = context.get("chat_title", "")
    query_parts = [p for p in (f"session on {platform}" if platform else "",
                               f"chat: {chat_title}" if chat_title else "") if p]
    prompt = "active projects deadlines status changes recent corrections " + " ".join(query_parts)
    mneme = _run_mneme_retrieve(prompt)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Live Vault Snapshot",
        "",
        f"Generated: {now}",
        f"Event: {event_type}",
        f"Platform: {platform}",
        f"Session: {session_id}",
        "",
        "This file is generated by the generic Mneme vault-context hook using"
        " `obsidian-cli` (optional) and the public `mneme` CLI with the optional"
        " Jev advisory router. The router only re-orders retrieval results and"
        " degrades silently when unavailable.",
        "",
        "## Mneme Graph Retrieval",
        "",
        mneme,
        "",
    ]
    if "status" in parts:
        lines += ["## Vault Status", "", "```text", parts["status"], "```", ""]
    if "MEMORY.md" in parts:
        lines += ["## MEMORY.md", "", parts["MEMORY.md"], ""]
    if "USER.md" in parts:
        lines += ["## USER.md", "", parts["USER.md"], ""]
    if "daily" in parts:
        lines += ["## Today's Daily Note", "", parts["daily"], ""]
    return "\n".join(lines)


def handle(event_type: str, context: Dict[str, Any] | None = None) -> None:
    context = context or {}
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    out_path = hermes_home / "memories" / "obsidian-vault.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".md.tmp")
    tmp.write_text(_build_snapshot(event_type, context), encoding="utf-8")
    tmp.replace(out_path)
    print(f"[vault-context] refreshed {out_path}", flush=True)


if __name__ == "__main__":
    handle("session:start", {"platform": "cli", "session_id": ""})