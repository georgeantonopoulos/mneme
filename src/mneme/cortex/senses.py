"""Senses: turn raw sources into small, timestamped episodes.

An episode is the unit of memory (a neuron). It keeps the original text, when
the thing happened (``event_time``), when Mneme could first have known it
(``known_at``), where it came from, and raw source metadata such as email
headers, mailbox labels or text hidden in HTML.

Readers are mechanical: they parse formats and never judge content. Deciding
what an episode means, how it relates to others and whether to trust it is the
mind's job (see ``perceive.py``).
"""
from __future__ import annotations

import datetime as dt
import email
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from ..html_visible import extract_visible_and_hidden

LONDON = ZoneInfo("Europe/London")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
SHORT_NOTE_CHARS = 900
MAX_EPISODE_CHARS = 900  # longer memories are split into parts, so reading and answering always see all of them
DATED_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class Episode:
    id: str
    source: str  # note | journal | email | event | chat | task
    doc: str  # the document this came from; used for diversity and same-doc synapses
    refs: list[str]
    title: str
    text: str
    known_at: str  # ISO timestamp: earliest moment this content existed
    event_time: str | None = None  # ISO timestamp the content is about, when there is one
    thread: str | None = None
    people: list[str] = field(default_factory=list)  # participants: email addresses, chat names
    meta: dict = field(default_factory=dict)  # raw source metadata: header, labels, folder, hidden_text, status


def _iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LONDON)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _day_iso(day: str) -> str:
    return _iso(dt.datetime.fromisoformat(day[:10]).replace(hour=12))


# ---------------------------------------------------------------------------
# Markdown notes
# ---------------------------------------------------------------------------
def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def _sections(body: str) -> list[tuple[str, str]]:
    """Split a note into (heading path, text) sections at H2 and below."""
    matches = [m for m in HEADING_RE.finditer(body) if len(m.group(1)) >= 2]
    if not matches:
        return [("", body.strip())]
    out = []
    if body[: matches[0].start()].strip():
        out.append(("", body[: matches[0].start()].strip()))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[m.end():end].strip()
        if text:
            out.append((m.group(2).strip(), text))
    return out


def read_vault(vault: Path, *, journal_dir: str = "Journal") -> Iterator[Episode]:
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue  # .obsidian, .trash and other hidden folders
        meta, body = _frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        title_match = re.match(r"\s*#\s+(.+)", body)
        title = title_match.group(1).strip() if title_match else path.stem
        if title_match:
            body = body[title_match.end():]
        updated = meta.get("updated") or meta.get("created") or dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
        known_at = _day_iso(updated)
        if rel.startswith(journal_dir + "/") and DATED_RE.fullmatch(path.stem):
            yield Episode(id=f"journal:{path.stem}", source="journal", doc=rel, refs=[f"journal:{path.stem}"], title=title,
                          text=body.strip(), known_at=known_at, event_time=_day_iso(path.stem))
            continue
        ref = f"note:{rel}"
        sections = [("", body.strip())] if len(body) <= SHORT_NOTE_CHARS else _sections(body)
        for i, (heading, text) in enumerate(sections):
            label = f"{title} > {heading}" if heading else title
            yield Episode(id=f"{ref}#{i}", source="note", doc=rel, refs=[ref], title=label, text=text,
                          known_at=known_at, meta={"path": rel, "tags": meta.get("tags", "")})


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def read_email_dir(directory: Path) -> Iterator[Episode]:
    for path in sorted(directory.glob("*.eml")):
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        mid = (msg["X-LifeVault-Id"] or msg["Message-ID"] or path.stem).strip("<>")
        sent = parsedate_to_datetime(msg["Date"]) if msg["Date"] else dt.datetime.fromtimestamp(path.stat().st_mtime)
        plain = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
        text = plain.get_content().strip() if plain else ""
        hidden: list[str] = []
        if html_part is not None and html_part is not plain:
            visible, hidden = extract_visible_and_hidden(html_part.get_content())
            if not text:
                text = visible
        people = [a.lower() for _, a in (parseaddr(x) for x in [msg["From"] or "", msg["To"] or "", msg["Cc"] or ""]) if a]
        attachments = [part.get_filename() for part in msg.iter_attachments() if part.get_filename()]
        header = f"From: {msg['From']}\nTo: {msg['To']}"
        if msg["Cc"]:
            header += f"\nCc: {msg['Cc']}"
        if attachments:
            header += f"\nAttachments: {', '.join(attachments)}"
        meta = {"header": header, "folder": msg["X-LifeVault-Folder"] or "", "labels": msg["X-LifeVault-Labels"] or ""}
        if hidden:
            meta["hidden_text"] = " ".join(hidden)[:1000]
        yield Episode(id=f"email:{mid}", source="email", doc=f"email:{mid}", refs=[f"email:{mid}"], title=msg["Subject"] or "(no subject)",
                      text=text, known_at=_iso(sent), event_time=_iso(sent),
                      thread=(msg["X-LifeVault-Thread"] or (msg["References"] or msg["Message-ID"] or mid).split()[0]),
                      people=people, meta=meta)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
def _ics_value(raw: str) -> dt.datetime:
    params, value = raw.split(":", 1) if ":" in raw else ("", raw)
    tzid = next((p.split("=", 1)[1].strip('"') for p in params.split(";") if p.upper().startswith("TZID=")), None)
    try:
        zone = ZoneInfo(tzid) if tzid else LONDON
    except (ValueError, KeyError, OSError):  # an unknown or Windows-style zone name
        zone = LONDON
    if "VALUE=DATE" in params or len(value) == 8:
        return dt.datetime.strptime(value[:8], "%Y%m%d").replace(hour=9, tzinfo=zone)
    stamp = dt.datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    return stamp.replace(tzinfo=dt.timezone.utc if value.endswith("Z") else zone)


def read_ics(path: Path) -> Iterator[Episode]:
    text = path.read_text(encoding="utf-8").replace("\r\n ", "")
    for block in text.split("BEGIN:VEVENT")[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key = line.split(":", 1)[0].split(";")[0]
            fields[key] = line if key in ("DTSTART", "DTEND", "CREATED", "DTSTAMP") else line.split(":", 1)[1]
        unescape = lambda s: s.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")  # noqa: E731
        uid = fields.get("UID", "").split("@")[0]
        start = _ics_value(fields["DTSTART"])
        all_day = "VALUE=DATE" in fields["DTSTART"]
        when = start.strftime("%A %d %B %Y") + ("" if all_day else start.strftime(", %H:%M"))
        status = fields.get("STATUS", "CONFIRMED")
        summary = unescape(fields.get("SUMMARY", ""))
        body = f"{summary}\nWhen: {when}\nStatus: {status}"
        if fields.get("LOCATION"):
            body += f"\nWhere: {unescape(fields['LOCATION'])}"
        if fields.get("DESCRIPTION"):
            body += f"\n{unescape(fields['DESCRIPTION'])}"
        created = _ics_value(fields.get("CREATED") or fields.get("DTSTAMP") or fields["DTSTART"])
        yield Episode(id=f"event:{uid}", source="event", doc=f"event:{uid}", refs=[f"event:{uid}"], title=summary, text=body,
                      known_at=_iso(created), event_time=_iso(start), meta={"status": status})


# ---------------------------------------------------------------------------
# Chat: messages in one conversation within a gap form one episode
# ---------------------------------------------------------------------------
def read_chat_jsonl(path: Path, *, gap_minutes: int = 180) -> Iterator[Episode]:
    by_chat: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_chat[row["chat"]].append(row)
    for conversation, rows in sorted(by_chat.items()):
        rows.sort(key=lambda r: r["ts"])
        window: list[dict] = []
        for row in rows + [None]:  # type: ignore[list-item]
            if window and (row is None or dt.datetime.fromisoformat(row["ts"]) - dt.datetime.fromisoformat(window[-1]["ts"]) > dt.timedelta(minutes=gap_minutes)):
                first = dt.datetime.fromisoformat(window[0]["ts"])
                last = dt.datetime.fromisoformat(window[-1]["ts"])
                text = "\n".join(f"{r['from']}: {r['text']}" for r in window)
                yield Episode(id=f"chat:{conversation}@{window[0]['ts']}", source="chat", doc=f"chat:{conversation}",
                              refs=[f"chat:{conversation}@{r['ts']}" for r in window], title=f"Chat with {conversation}",
                              text=text, known_at=_iso(last), event_time=_iso(first), thread=f"chat:{conversation}",
                              people=sorted({r["from"].lower() for r in window} | {conversation.lower()}))
                window = []
            if row is not None:
                window.append(row)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def read_tasks_json(path: Path) -> Iterator[Episode]:
    for row in json.loads(path.read_text(encoding="utf-8")):
        done = bool(row.get("completed"))
        text = f"[{'x' if done else ' '}] {row['title']}\nProject: {row.get('project') or '-'}"
        if row.get("due"):
            text += f"\nDue: {dt.date.fromisoformat(row['due']).strftime('%A %d %B %Y')}"
        text += f"\nStatus: {'done ' + row['completed'] if done else 'open'}"
        if row.get("notes"):
            text += f"\nNotes: {row['notes']}"
        known = row["completed"] if done else row["created"]
        yield Episode(id=f"task:{row['id']}", source="task", doc=f"task:{row['id']}", refs=[f"task:{row['id']}"], title=row["title"],
                      text=text, known_at=_day_iso(known), event_time=_day_iso(row["due"]) if row.get("due") else None,
                      meta={"status": "done" if done else "open"})


def _parts(text: str, limit: int) -> list[str]:
    """Split text at paragraph, then line, then word boundaries into pieces of at most `limit` characters."""
    if len(text) <= limit:
        return [text]
    for sep in ("\n\n", "\n", " "):
        pieces, current = [], ""
        for chunk in text.split(sep):
            candidate = f"{current}{sep}{chunk}" if current else chunk
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                pieces.append(current)
            current = chunk
        pieces.append(current)
        if all(len(p) <= limit for p in pieces):
            return [p.strip() for p in pieces if p.strip()]
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def bounded(episodes: Iterable[Episode], limit: int = MAX_EPISODE_CHARS) -> Iterator[Episode]:
    for ep in episodes:
        parts = _parts(ep.text, limit)
        if len(parts) == 1:
            yield ep
            continue
        for k, text in enumerate(parts, 1):
            yield replace(ep, id=f"{ep.id}/{k}", title=f"{ep.title} (part {k} of {len(parts)})", text=text)


def read_sources(root: Path) -> Iterable[Episode]:
    """Read a directory laid out like LifeVault (vault/ plus sources/{email,calendar,chat,tasks}), or, when it has
    neither, treat the directory itself as a Markdown vault (a notes-app vault, a notes folder). Memories longer
    than MAX_EPISODE_CHARS come out as several parts."""
    yield from bounded(_read_sources(root))


def _read_sources(root: Path) -> Iterable[Episode]:
    if not (root / "vault").is_dir() and not (root / "sources").is_dir():
        yield from read_vault(root)
        return
    if (root / "vault").is_dir():
        yield from read_vault(root / "vault")
    sources = root / "sources"
    if (sources / "email").is_dir():
        yield from read_email_dir(sources / "email")
    for ics in sorted((sources / "calendar").glob("*.ics")) if (sources / "calendar").is_dir() else []:
        yield from read_ics(ics)
    for chat in sorted((sources / "chat").glob("*.jsonl")) if (sources / "chat").is_dir() else []:
        yield from read_chat_jsonl(chat)
    for tasks in sorted((sources / "tasks").glob("*.json")) if (sources / "tasks").is_dir() else []:
        yield from read_tasks_json(tasks)
