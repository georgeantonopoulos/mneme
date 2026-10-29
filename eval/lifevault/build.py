#!/usr/bin/env python3
"""Build the LifeVault fixture from story.py + noise.py.

    python eval/lifevault/build.py            # writes eval/lifevault/data/
    python eval/lifevault/build.py --check    # fails if data/ is stale

Outputs, all fictional:
    data/vault/                 Markdown notes with YAML frontmatter, incl. Journal/
    data/sources/email/         one RFC 5322 .eml file per message
    data/sources/calendar/      one .ics calendar (with cancelled + rescheduled events)
    data/sources/chat/          chat export, JSON Lines
    data/sources/tasks/         task-app export, JSON
    data/questions.json         eval questions with gold evidence (from truth.py)
    data/manifest.json          counts and the fixture "now"
"""
from __future__ import annotations

import argparse
import datetime as dt
import filecmp
import json
import shutil
import sys
import tempfile
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

import noise  # noqa: E402
import story  # noqa: E402
import truth  # noqa: E402

LONDON = ZoneInfo("Europe/London")
PDF_PLACEHOLDER = b"%PDF-1.4\n% LifeVault fictional placeholder attachment\n%%EOF\n"


def _addr(value) -> str:
    if isinstance(value, tuple):
        return f"{value[0]} <{value[1]}>"
    return value


def _when(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=LONDON)


def _msgid(eid: str) -> str:
    return f"<{eid}@lifevault.example>"


def write_emails(root: Path) -> int:
    out = root / "sources" / "email"
    out.mkdir(parents=True)
    ordered = sorted(story.EMAILS, key=lambda e: (e["date"], e["id"]))
    thread_root: dict[str, str] = {}
    thread_prev: dict[str, list[str]] = {}
    for item in ordered:
        msg = EmailMessage()
        msg["Message-ID"] = _msgid(item["id"])
        msg["Date"] = format_datetime(_when(item["date"]))
        msg["From"] = _addr(item["from"])
        msg["To"] = _addr(item["to"])
        if item["cc"]:
            msg["Cc"] = ", ".join(_addr(c) for c in item["cc"])
        subject = item["subject"]
        thread = item["thread"]
        if thread in thread_root:
            msg["In-Reply-To"] = _msgid(thread_prev[thread][-1])
            msg["References"] = " ".join(_msgid(x) for x in thread_prev[thread])
        thread_root.setdefault(thread, item["id"])
        thread_prev.setdefault(thread, []).append(item["id"])
        msg["Subject"] = subject
        msg["X-LifeVault-Id"] = item["id"]
        msg["X-LifeVault-Thread"] = thread
        msg["X-LifeVault-Folder"] = item["folder"]
        if item["labels"]:
            msg["X-LifeVault-Labels"] = ",".join(item["labels"])
        msg.set_content(item["body"] + "\n")
        if item["html"]:
            msg.add_alternative(item["html"], subtype="html")
        for name in item["attachments"]:
            msg.add_attachment(PDF_PLACEHOLDER, maintype="application", subtype="pdf", filename=name)
        # Fixed MIME boundaries keep the build byte-for-byte reproducible.
        for n, part in enumerate(p for p in msg.walk() if p.is_multipart()):
            part.set_boundary(f"lifevault-{item['id']}-{n}")
        (out / f"{item['date'][:10]}_{item['id']}.eml").write_bytes(bytes(msg))
    return len(ordered)


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_time(value: str, all_day: bool) -> str:
    if all_day:
        return ";VALUE=DATE:" + value.replace("-", "")
    return ";TZID=Europe/London:" + dt.datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")


def write_calendar(root: Path) -> int:
    out = root / "sources" / "calendar"
    out.mkdir(parents=True)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LifeVault//Fictional fixture//EN", "X-WR-CALNAME:Nia"]
    for ev in sorted(story.EVENTS, key=lambda e: (e["start"], e["uid"])):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev['uid']}@lifevault.example",
            f"DTSTAMP:{ev['created'].replace('-', '')}T090000Z",
            f"CREATED:{ev['created'].replace('-', '')}T090000Z",
            "DTSTART" + _ics_time(ev["start"], ev["all_day"]),
            "DTEND" + _ics_time(ev["end"], ev["all_day"]),
            f"SUMMARY:{_ics_escape(ev['summary'])}",
        ]
        if ev["location"]:
            lines.append(f"LOCATION:{_ics_escape(ev['location'])}")
        if ev["desc"]:
            lines.append(f"DESCRIPTION:{_ics_escape(ev['desc'])}")
        lines += [f"STATUS:{ev['status']}", f"SEQUENCE:{ev['sequence']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    (out / "nia.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    return len(story.EVENTS)


def write_chats(root: Path) -> int:
    out = root / "sources" / "chat"
    out.mkdir(parents=True)
    rows = sorted(story.CHATS, key=lambda c: (c["ts"], c["chat"], c["text"]))
    with (out / "messages.jsonl").open("w", encoding="utf-8") as fh:
        for i, row in enumerate(rows):
            fh.write(json.dumps({"id": f"msg-{i:04d}", **row}, ensure_ascii=False) + "\n")
    return len(rows)


def write_tasks(root: Path) -> int:
    out = root / "sources" / "tasks"
    out.mkdir(parents=True)
    rows = sorted(story.TASKS, key=lambda t: (t["created"], t["id"]))
    (out / "tasks.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(rows)


def _frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(value)}]")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines + ["---", ""])


def write_vault(root: Path) -> int:
    out = root / "vault"
    count = 0
    for item in sorted(story.NOTES, key=lambda n: n["path"]):
        path = out / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"created": item["created"], "updated": item["updated"], "tags": item["tags"]}
        path.write_text(_frontmatter(meta) + item["body"] + "\n", encoding="utf-8")
        count += 1
    for day, lines in sorted(story.JOURNAL.items()):
        path = out / "Journal" / day[:4] / f"{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"# {day}\n\n" + "\n".join(f"- {line}" for line in lines)
        path.write_text(_frontmatter({"created": day, "updated": day, "tags": ["journal"]}) + body + "\n", encoding="utf-8")
        count += 1
    return count


def build(root: Path) -> dict:
    story.moving()
    story.halcyon()
    story.bramble()
    story.knee()
    story.ivy()
    story.tax()
    story.car()
    story.lisbon()
    story.pottery()
    story.social()
    noise.build_noise()
    root.mkdir(parents=True)
    counts = {
        "notes": write_vault(root),
        "emails": write_emails(root),
        "calendar_events": write_calendar(root),
        "chat_messages": write_chats(root),
        "tasks": write_tasks(root),
    }
    questions = truth.questions()
    truth.validate(questions, root)
    (root / "questions.json").write_text(json.dumps(questions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts["questions"] = len(questions)
    manifest = {"name": "lifevault", "persona": "Nia Okafor (fictional)", "now": story.NOW, "counts": counts}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(_same_tree(a / d, b / d) for d in cmp.common_dirs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=HERE / "data")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if --out differs from a fresh build")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "data"
        manifest = build(fresh)
        if args.check:
            ok = args.out.exists() and _same_tree(fresh, args.out)
            print("lifevault fixture up to date" if ok else "lifevault fixture is stale: run eval/lifevault/build.py")
            return 0 if ok else 1
        if args.out.exists():
            shutil.rmtree(args.out)
        shutil.copytree(fresh, args.out)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
