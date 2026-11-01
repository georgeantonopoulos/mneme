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
import sqlite3
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
MAX_EPISODE_CHARS = 900  # longer memories are split into parts, so reading and answering always see all of them
SHORT_NOTE_CHARS = MAX_EPISODE_CHARS  # a note up to this long stays whole; a longer one splits at its headings
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
def _note_time(value: str | None) -> str | None:
    """A frontmatter date or date-time. A bare date means that day (noon); an unreadable value gives None."""
    if not value:
        return None
    try:
        if len(value) > 10:
            return _iso(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        return _day_iso(value)
    except ValueError:
        return None


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            meta[key.strip()] = value
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
        known_at = _note_time(meta.get("updated") or meta.get("created")) or _iso(
            dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc))
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
    # Unfold continuation lines (RFC 5545: a line break then a space or tab); read_text already turned CRLF into \n.
    text = re.sub(r"\n[ \t]", "", path.read_text(encoding="utf-8"))
    for block in text.split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        # Components nested in an event (VALARM reminders) carry their own SUMMARY or DESCRIPTION: drop them.
        block = re.sub(r"^BEGIN:([A-Z-]+)$.*?^END:\1$", "", block, flags=re.M | re.S)
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key = line.split(":", 1)[0].split(";")[0]
            fields[key] = line if key in ("DTSTART", "DTEND", "CREATED", "DTSTAMP") else line.split(":", 1)[1]
        unescape = lambda s: s.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")  # noqa: E731
        uid = fields.get("UID", "").split("@")[0]
        # An edited occurrence of a recurring event shares its UID; RECURRENCE-ID tells the occurrences apart.
        ident = uid + (f"@{fields['RECURRENCE-ID'].strip()}" if fields.get("RECURRENCE-ID") else "")
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
        yield Episode(id=f"event:{ident}", source="event", doc=f"event:{uid}", refs=[f"event:{ident}"], title=summary, text=body,
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
    structured = (root / "vault").is_dir() or any((root / "sources" / kind).is_dir() for kind in ("email", "calendar", "chat", "tasks"))
    if not structured:  # an ordinary notes folder, even one that happens to hold a folder called "sources"
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


# ---------------------------------------------------------------------------
# The graph database of earlier Mneme versions
# ---------------------------------------------------------------------------
def _stamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _iso(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def read_graph_db(path: Path) -> Iterator[Episode]:
    """Memories from the SQLite graph of earlier Mneme versions, read-only. Every record becomes an ordinary
    memory for the mind to perceive: world-state assertions (current and superseded), the action ledger,
    predictions, aliases, validated or killed relationships, and what the email and calendar senses observed.
    Left out: relationships drawn from wikilinks (the notes themselves hold them), unvalidated candidate
    relationships, and temporary ``mneme://`` memories, which must stay removable as one unit."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).expanduser()}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def rows(sql: str):
        return conn.execute(sql).fetchall()

    # Anything from a mneme:// source can be forgotten in the graph as one unit, so none of it is copied here.
    kept = "COALESCE({}, '') NOT LIKE 'mneme://%'"

    def episode(kind: str, rid: str, title: str, lines: list[str], known: str | None, *, event: str | None = None,
                meta: dict | None = None) -> Episode | None:
        known_at = _stamp(known)
        if not known_at:
            return None
        text = "\n".join(line for line in lines if line)
        return Episode(id=f"{kind}:{rid}", source=kind, doc=f"graph:{kind}", refs=[f"{kind}:{rid}"], title=title[:120],
                       text=text, known_at=known_at, event_time=_stamp(event), meta=meta or {})

    found: list[Episode | None] = []
    if "world_state_assertions" in tables:
        for r in rows(f"SELECT * FROM world_state_assertions WHERE {kept.format('source_path')} ORDER BY created_at, id"):
            value = r["object_name"] or r["object_value"]
            found.append(episode("state", r["id"], f"{r['subject_name']} {r['predicate']} {value}", [
                f"Recorded state ({r['state_type']}, {r['status']}): {r['subject_name']} {r['predicate']} {value}.",
                f"Valid from {r['valid_from']}" + (f" until {r['valid_until']}" if r["valid_until"] else "") if r["valid_from"] else "",
                f"Evidence: {r['evidence_text']}", f"Source: {r['source_path']}"], r["updated_at"] or r["created_at"],
                event=r["valid_from"], meta={"status": r["status"]}))
    if "world_actions" in tables:
        for r in rows(f"SELECT * FROM world_actions WHERE {kept.format('source_path')} ORDER BY created_at, id"):
            found.append(episode("action", r["id"], r["title"], [
                f"Action by {r['actor']}: {r['title']} ({r['action_type']}, status {r['status']}).",
                f"Side effects: {r['side_effect_level']}, reversibility: {r['reversibility']}.",
                f"Reference: {r['external_ref']}" if r["external_ref"] else ""], r["created_at"], event=r["created_at"]))
    if "world_predictions" in tables:
        temporary = []  # a prediction goes with the temporary assertion or action it hangs off
        if "world_state_assertions" in tables:
            temporary.append("COALESCE(subject_assertion_id, '') IN (SELECT id FROM world_state_assertions WHERE source_path LIKE 'mneme://%')")
        if "world_actions" in tables:
            temporary.append("COALESCE(source_action_id, '') IN (SELECT id FROM world_actions WHERE source_path LIKE 'mneme://%')")
        where = f"WHERE NOT ({' OR '.join(temporary)})" if temporary else ""
        for r in rows(f"SELECT * FROM world_predictions {where} ORDER BY created_at, id"):
            found.append(episode("prediction", r["id"], r["title"], [
                f"Expected: {r['title']} (status {r['status']}).",
                f"Check after {r['check_after']}, expires {r['expires_at']}.",
                f"Outcome: {r['outcome_summary']}" if r["outcome_summary"] else ""], r["updated_at"] or r["created_at"],
                event=r["check_after"], meta={"status": r["status"]}))
    if "entity_aliases" in tables:
        for r in rows("SELECT * FROM entity_aliases ORDER BY created_at, alias_norm"):
            found.append(episode("alias", r["alias_norm"], f"{r['alias_name']} = {r['canonical_name']}",
                                 [f"'{r['alias_name']}' is another name for '{r['canonical_name']}' ({r['source']})."],
                                 r["updated_at"] or r["created_at"]))
    if {"edges", "nodes"} <= tables:
        for r in rows("SELECT e.*, a.name AS src_name, b.name AS dst_name FROM edges e JOIN nodes a ON a.id = e.src_id "
                      "JOIN nodes b ON b.id = e.dst_id WHERE e.status IN ('active', 'killed') "
                      f"AND COALESCE(e.source_type, 'vault') != 'vault' AND {kept.format('e.source_path')} "
                      f"AND {kept.format('a.source_path')} AND {kept.format('b.source_path')} ORDER BY e.created_at, e.id"):
            relation = r["relation"].replace("_", " ")
            claim = (f"{r['src_name']} {relation} {r['dst_name']}" if r["status"] == "active"
                     else f"It is false that {r['src_name']} {relation} {r['dst_name']}: this relationship was marked wrong.")
            found.append(episode("relation", r["id"], f"{r['src_name']} {relation} {r['dst_name']}",
                                 [claim + ".", f"Evidence: {r['evidence_text']}" if r["evidence_text"] else "",
                                  f"Source: {r['source_path']}" if r["source_path"] else ""], r["updated_at"] or r["created_at"],
                                 meta={"status": r["status"]}))
    if {"observations", "nodes"} <= tables:
        sensed: dict[str, list[sqlite3.Row]] = {}
        for r in rows("SELECT o.*, n.name AS node_name FROM observations o JOIN nodes n ON n.id = o.note_id "
                      f"WHERE o.sense_event_id IS NOT NULL AND {kept.format('o.source_path')} AND {kept.format('n.source_path')} "
                      "ORDER BY o.created_at, o.id"):
            sensed.setdefault(r["note_id"], []).append(r)
        for note_id, obs in sensed.items():
            found.append(episode("sensed", note_id, obs[0]["node_name"], [f"- {o['text']}" for o in obs],
                                 obs[-1]["created_at"], meta={"source": obs[0]["source_path"]}))
    conn.close()
    yield from bounded(e for e in found if e is not None)
