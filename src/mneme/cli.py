from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
from . import md_edit
from .core import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_HINTS,
    activate_candidate_edges,
    configured_senses,
    create_config,
    dismiss_thought_task,
    doctor,
    explain_edge,
    explain_thought,
    generate_proactive_thought,
    ingest_sense_events,
    ingest_vault,
    list_thought_candidates,
    list_thought_tasks,
    load_config,
    record_feedback,
    record_thought_reminder,
    record_thought_writeback,
    save_thought,
    surface_thoughts,
    tick,
    update_thought_task,
    update_vault,
    weaken_edge,
    write_note,
    write_research_resolution,
)
from .dedup import run_dedup
from .render import render_card
from .onboarding import run_onboarding
from .runtime import default_config_path, load_runtime_config, resolve_hints, resolve_path
from .senses.gws import GwsSense
from .senses.markdown import MarkdownSense
from .senses.registry import available_senses, build_sense_from_config
from .source_packets import store_packet


# Dedup command defaults
SIMILARITY_THRESHOLD = 0.75
CONTENT_OVERLAP_THRESHOLD = 0.6


def parse_hints(value: str | None):
    return DEFAULT_HINTS if not value else [p.strip() for p in value.split(",") if p.strip()]


def path_from_config(args, name: str, required: bool = True) -> Path | None:
    return resolve_path(args, name, required=required)


def hints_from_args(args):
    return resolve_hints(args)


def emit(result, *, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if isinstance(result, list):
            for item in result:
                print(_human_line(item))
        elif isinstance(result, dict):
            for key, value in result.items():
                print(f"{key}: {value}")
        else:
            print(result)


def _human_line(item: dict) -> str:
    if "activation_score" in item:
        return f"{item['id']}  score={item['activation_score']:.2f}  {item.get('title') or item.get('suggested_action')}"
    if {"id", "type", "enabled"} <= set(item):
        return f"{item['id']}  {item['type']}  enabled={item['enabled']}  configured={item.get('configured', True)}  last_run={item.get('last_run_at') or '-'}"
    return json.dumps(item, ensure_ascii=False)


def sense_entries_from_args(args) -> list[dict]:
    if args.sense_type == "md":
        vault = args.vault or path_from_config(args, "vault")
        return [{"id": "vault", "type": "md", "enabled": True, "config": {"path": str(vault), "follow_symlinks": args.follow_symlinks}}]
    if args.sense_type == "gws":
        return [{"id": "gws", "type": "gws", "enabled": True, "config": {"email": args.email, "calendar": args.calendar, "tasks": args.tasks, "query": args.query}}]
    if args.sense_type == "hermes_sessions":
        return [{"id": "hermes-sessions", "type": "hermes_sessions", "enabled": True, "config": {"path": "/root/.hermes/sessions", "limit": args.limit}}]
    cfg_path = getattr(args, "config", None) or DEFAULT_CONFIG_PATH
    cfg = load_runtime_config(Path(cfg_path))
    return [entry for entry in configured_senses(cfg) if entry.get("enabled", True)]


def run_sense_entries(args, entries: list[dict]) -> dict:
    db_path = path_from_config(args, "db", required=not args.dry_run)
    import sqlite3

    conn = None if args.dry_run else sqlite3.connect(db_path)
    all_stats = {"events": 0, "nodes": 0, "observations": 0, "edges": 0, "by_sense": {}, "by_event_type": {}, "dry_run": bool(args.dry_run), "db": str(db_path) if db_path else None}
    for entry in entries:
        sense = build_sense_from_config(entry)
        if args.dry_run:
            if isinstance(sense, GwsSense):
                all_stats["by_sense"][sense.sense_id] = sense.dry_run(limit=args.limit)
            else:
                all_stats["by_sense"][sense.sense_id] = {"sense_id": sense.sense_id, "sense_type": sense.sense_type, "would_collect": True}
            continue
        stats = ingest_sense_events(conn, sense.collect(limit=args.limit), hints=hints_from_args(args))
        for key in ("events", "nodes", "observations", "edges"):
            all_stats[key] += stats[key]
        all_stats["by_sense"].update(stats["by_sense"])
        for event_type, count in stats["by_event_type"].items():
            all_stats["by_event_type"][event_type] = all_stats["by_event_type"].get(event_type, 0) + count
    if conn is not None:
        conn.commit()
        conn.close()
    return all_stats


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(prog="mneme", description="Graph-based memory paths for AI agents"); parser.add_argument("--config", type=Path, default=default_config_path(), help="Config path (default: $MNEME_CONFIG or ~/.config/mneme/config.json)"); sub=parser.add_subparsers(dest="cmd", required=True)
    p=sub.add_parser("init", help="Create a Mneme config file"); p.add_argument("--vault",required=True,type=Path); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--force",action="store_true",help="Overwrite an existing config")
    p=sub.add_parser("setup", help="Interactive onboarding: vault, senses, classifier model, and Hermes env hints"); p.add_argument("--force",action="store_true",help="Overwrite an existing config")
    sub.add_parser("doctor", help="Validate config, vault, and output paths")
    p=sub.add_parser("ingest"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--hints"); p.add_argument("--max-notes",type=int); p.add_argument("--append",action="store_true",help="Append/update instead of rebuilding the graph; can retain stale private data"); p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked Markdown files that resolve inside the vault")
    p=sub.add_parser("update", help="Synchronize graph tables from the current vault while preserving thought history"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--hints"); p.add_argument("--max-notes",type=int); p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked Markdown files that resolve inside the vault")
    p=sub.add_parser("write", help="Safely create, append, or overwrite a Markdown note inside a vault"); p.add_argument("--vault",type=Path); p.add_argument("--path",required=True,help="Relative .md path inside the vault"); p.add_argument("--mode",choices=["create","append","overwrite"],default="create"); p.add_argument("--content",help="Markdown content; omit to read from stdin")
    note=sub.add_parser("note", help="Path-safe Markdown note editor"); note_sub=note.add_subparsers(dest="note_cmd", required=True)
    p=note_sub.add_parser("read", help="Read a note, optionally limited to one heading"); p.add_argument("path"); p.add_argument("--vault",type=Path); p.add_argument("--heading"); p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("write", help="Create, append, or overwrite a note atomically"); p.add_argument("path"); p.add_argument("--vault",type=Path); p.add_argument("--mode",choices=["create","append","overwrite"],default="append"); p.add_argument("--content",help="Markdown content; omit to read from stdin"); p.add_argument("--dry-run",action="store_true"); p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("replace", help="Exact string replacement with optional dry-run diff"); p.add_argument("path"); p.add_argument("--vault",type=Path); p.add_argument("--find",required=True); p.add_argument("--replace",required=True); p.add_argument("--all",action="store_true",dest="replace_all"); p.add_argument("--dry-run",action="store_true"); p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("upsert-section", help="Replace or append a Markdown heading section"); p.add_argument("path"); p.add_argument("--vault",type=Path); p.add_argument("--heading",required=True); p.add_argument("--content",required=True); p.add_argument("--level",type=int,default=2); p.add_argument("--dry-run",action="store_true"); p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("add-bullet", help="Add a deduped bullet under a heading"); p.add_argument("path"); p.add_argument("--vault",type=Path); p.add_argument("--heading",required=True); p.add_argument("--bullet",required=True); p.add_argument("--dry-run",action="store_true"); p.add_argument("--force",action="store_true")
    p=sub.add_parser("resolve", help="Write a research-resolution JSON payload to Markdown and weighted graph edges"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--file",type=Path,help="JSON payload file; omit to read JSON from stdin"); p.add_argument("--active-threshold",type=float,default=0.9)
    p=sub.add_parser("candidates", help="List scored proactive thought candidates"); p.add_argument("--db",type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5); p.add_argument("--limit",type=int,default=5)
    p=sub.add_parser("promote-candidates", help="Explicitly activate candidate edges after review; default only promotes validated research candidates"); p.add_argument("--db",type=Path); p.add_argument("--mode",choices=["validated-only","all"],default="validated-only"); p.add_argument("--dry-run",action="store_true")
    packet=sub.add_parser("packet", help="Create sanitized untrusted source packets"); packet_sub=packet.add_subparsers(dest="packet_cmd", required=True)
    p=packet_sub.add_parser("create", help="Persist raw source data and sanitized packet metadata"); p.add_argument("--packet-dir",type=Path,default=Path(os.environ.get("MNEME_PACKET_DIR", ".mneme/source_packets"))); p.add_argument("--source",required=True); p.add_argument("--kind",default="source"); p.add_argument("--raw-path",type=Path); p.add_argument("--text"); p.add_argument("--text-path",type=Path,help="Read extracted untrusted text from a file instead of argv"); p.add_argument("--metadata-json",default="{}"); p.add_argument("--json",action="store_true")
    sense=sub.add_parser("sense", help="List and run source senses"); sense_sub=sense.add_subparsers(dest="sense_cmd", required=True)
    p=sense_sub.add_parser("list", help="List configured and available senses"); p.add_argument("--json", action="store_true")
    p=sense_sub.add_parser("run", help="Collect one or all senses and ingest normalized events"); p.add_argument("sense_type", choices=["md","gws","hermes_sessions","all"]); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--hints"); p.add_argument("--limit",type=int); p.add_argument("--follow-symlinks",action="store_true"); p.add_argument("--email",action=argparse.BooleanOptionalAction,default=True); p.add_argument("--calendar",action=argparse.BooleanOptionalAction,default=True); p.add_argument("--tasks",action=argparse.BooleanOptionalAction,default=True); p.add_argument("--query"); p.add_argument("--dry-run",action="store_true"); p.add_argument("--json", action="store_true")
    p=sub.add_parser("tick", help="Run the cognition pulse and update thought candidates"); p.add_argument("--db",type=Path); p.add_argument("--hints"); p.add_argument("--sense",choices=["all","md","gws","hermes_sessions"]); p.add_argument("--surface",action="store_true"); p.add_argument("--limit",type=int,default=100); p.add_argument("--json", action="store_true")
    p=sub.add_parser("surface", help="Surface current proactive thought candidates"); p.add_argument("--db",type=Path); p.add_argument("--limit",type=int,default=1); p.add_argument("--json", action="store_true")
    p=sub.add_parser("feedback", help="Record feedback for a surfaced thought candidate"); p.add_argument("thought_id"); p.add_argument("--db",type=Path); group=p.add_mutually_exclusive_group(required=True); group.add_argument("--accept",action="store_true"); group.add_argument("--deny",action="store_true"); group.add_argument("--snooze"); group.add_argument("--kill",action="store_true"); group.add_argument("--acted",action="store_true"); group.add_argument("--already-done",action="store_true"); group.add_argument("--too-obvious",action="store_true"); group.add_argument("--good-but-later",action="store_true"); p.add_argument("--reason"); p.add_argument("--json", action="store_true")
    p=sub.add_parser("explain", help="Explain why a thought candidate surfaced"); p.add_argument("thought_id"); p.add_argument("--db",type=Path); p.add_argument("--json", action="store_true")
    task=sub.add_parser("task", help="List or explicitly update thought lifecycle tasks"); task_sub=task.add_subparsers(dest="task_cmd", required=True)
    p=task_sub.add_parser("list", help="List thought lifecycle tasks"); p.add_argument("--db",type=Path); p.add_argument("--status")
    p=task_sub.add_parser("update", help="Explicitly set a thought task status"); p.add_argument("task_id"); p.add_argument("--db",type=Path); p.add_argument("--status",required=True,choices=["open","acted","resolved","learned","dismissed"]); p.add_argument("--evidence",default="")
    p=task_sub.add_parser("writeback", help="Mark a thought task acted via note/writeback"); p.add_argument("task_id"); p.add_argument("--db",type=Path); p.add_argument("--target",required=True); p.add_argument("--evidence",default="")
    p=task_sub.add_parser("reminder", help="Mark a thought task resolved by a reminder/task/calendar item"); p.add_argument("task_id"); p.add_argument("--db",type=Path); p.add_argument("--reminder-id",required=True); p.add_argument("--evidence",default="")
    p=task_sub.add_parser("dismiss", help="Explicitly dismiss a thought task"); p.add_argument("task_id"); p.add_argument("--db",type=Path); p.add_argument("--reason",required=True)
    p=sub.add_parser("thought"); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5)
    p=sub.add_parser("explain-edge"); p.add_argument("edge_id"); p.add_argument("--db",required=True,type=Path)
    p=sub.add_parser("weaken-edge", help="Reduce edge strength after negative feedback without killing"); p.add_argument("edge_id"); p.add_argument("--db",required=True,type=Path); p.add_argument("--reason",default="User dismissed surfaced proposal"); p.add_argument("--factor",type=float,default=0.5); p.add_argument("--floor",type=float,default=0.0)
    p=sub.add_parser("run-once"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5); p.add_argument("--max-notes",type=int); p.add_argument("--append",action="store_true",help="Append/update instead of rebuilding the graph; can retain stale private data"); p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked markdown files that resolve inside the vault")
    p=sub.add_parser("dedup", help="Merge duplicate vault nodes by synapse strength"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--backup-dir",type=Path); p.add_argument("--title-threshold",type=float,default=SIMILARITY_THRESHOLD); p.add_argument("--content-threshold",type=float,default=CONTENT_OVERLAP_THRESHOLD); p.add_argument("--dry-run",action="store_true"); p.add_argument("--auto",action="store_true"); p.add_argument("--json",action="store_true")
    args=parser.parse_args(argv)
    if args.cmd == "init":
        if args.config.exists() and not args.force:
            raise SystemExit(f"config already exists: {args.config}; pass --force to overwrite")
        print(json.dumps(create_config(args.config,args.vault,args.db,args.out,parse_hints(args.hints) if args.hints else None), indent=2, ensure_ascii=False)); return
    if args.cmd == "setup":
        try:
            result = run_onboarding(args.config, force=args.force)
        except FileExistsError as exc:
            raise SystemExit(str(exc)) from None
        print(result["summary"]); return
    if args.cmd == "doctor":
        print(json.dumps(doctor(args.config), indent=2, ensure_ascii=False)); return
    if args.cmd == "ingest":
        print(json.dumps(ingest_vault(path_from_config(args,"vault"),path_from_config(args,"db"),hints_from_args(args),args.max_notes,rebuild=not args.append,follow_symlinks=args.follow_symlinks), indent=2, ensure_ascii=False)); return
    if args.cmd == "update":
        print(json.dumps(update_vault(path_from_config(args,"vault"),path_from_config(args,"db"),hints_from_args(args),args.max_notes,follow_symlinks=args.follow_symlinks), indent=2, ensure_ascii=False)); return
    if args.cmd == "write":
        content = args.content if args.content is not None else sys.stdin.read()
        print(json.dumps(write_note(path_from_config(args,"vault"),args.path,content,mode=args.mode), indent=2, ensure_ascii=False)); return
    if args.cmd == "note":
        try:
            vault = path_from_config(args,"vault")
            if args.note_cmd == "read":
                result = md_edit.read_note(vault,args.path,heading=args.heading,force=args.force)
            elif args.note_cmd == "write":
                content = args.content if args.content is not None else sys.stdin.read()
                result = md_edit.write_note(vault,args.path,content,mode=args.mode,dry_run=args.dry_run,force=args.force)
            elif args.note_cmd == "replace":
                result = md_edit.replace_exact(vault,args.path,args.find,args.replace,replace_all=args.replace_all,dry_run=args.dry_run,force=args.force)
            elif args.note_cmd == "upsert-section":
                result = md_edit.upsert_section(vault,args.path,args.heading,args.content,level=args.level,dry_run=args.dry_run,force=args.force)
            elif args.note_cmd == "add-bullet":
                result = md_edit.add_bullet(vault,args.path,args.heading,args.bullet,dry_run=args.dry_run,force=args.force)
            else:
                raise ValueError(f"unknown note command: {args.note_cmd}")
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc), "command": "note"}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2, ensure_ascii=False)); return
    if args.cmd == "resolve":
        payload = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        print(json.dumps(write_research_resolution(path_from_config(args,"vault"),path_from_config(args,"db"),payload,active_threshold=args.active_threshold), indent=2, ensure_ascii=False)); return
    if args.cmd == "explain-edge":
        print(json.dumps(explain_edge(args.db,args.edge_id), indent=2, ensure_ascii=False)); return
    if args.cmd == "weaken-edge":
        print(json.dumps(weaken_edge(args.db, args.edge_id, reason=args.reason, factor=args.factor, floor=args.floor), indent=2, ensure_ascii=False)); return
    if args.cmd == "candidates":
        print(json.dumps(list_thought_candidates(path_from_config(args,"db"), limit=args.limit, hops=args.hops, hints=hints_from_args(args)), indent=2, ensure_ascii=False)); return
    if args.cmd == "promote-candidates":
        print(json.dumps(activate_candidate_edges(path_from_config(args,"db"), mode=args.mode, dry_run=args.dry_run), indent=2, ensure_ascii=False)); return
    if args.cmd == "packet":
        if args.packet_cmd == "create":
            metadata = json.loads(args.metadata_json)
            if args.text is not None and args.text_path is not None:
                raise SystemExit("provide only one of --text or --text-path")
            text = args.text if args.text is not None else (args.text_path.read_text(encoding="utf-8", errors="replace") if args.text_path else (args.raw_path.read_text(encoding="utf-8", errors="replace") if args.raw_path else sys.stdin.read()))
            result = store_packet(packet_dir=args.packet_dir, source=args.source, kind=args.kind, raw_path=args.raw_path, text=text, metadata=metadata)
            emit(result, as_json=args.json)
            return
    if args.cmd == "sense":
        if args.sense_cmd == "list":
            cfg = load_runtime_config(args.config)
            configured = configured_senses(cfg)
            configured_ids = {entry.get("id") for entry in configured}
            result = [
                {"id": entry.get("id"), "type": entry.get("type"), "enabled": bool(entry.get("enabled", True)), "configured": True, "last_run_at": None}
                for entry in configured
            ]
            for sense_type in available_senses():
                if sense_type not in configured_ids and not any(entry.get("type") == sense_type for entry in configured):
                    result.append({"id": sense_type, "type": sense_type, "enabled": False, "configured": False, "last_run_at": None})
            emit(result, as_json=args.json); return
        emit(run_sense_entries(args, sense_entries_from_args(args)), as_json=args.json); return
    if args.cmd == "tick":
        if args.sense:
            class SenseArgs: pass
            sense_args = SenseArgs()
            sense_args.sense_type = args.sense
            sense_args.vault = None
            sense_args.db = args.db
            sense_args.config = args.config
            sense_args.hints = args.hints
            sense_args.limit = args.limit
            sense_args.follow_symlinks = False
            sense_args.email = sense_args.calendar = sense_args.tasks = True
            sense_args.query = None
            sense_args.dry_run = False
            run_sense_entries(sense_args, sense_entries_from_args(sense_args))
        result = tick(path_from_config(args,"db"), hints=hints_from_args(args), limit=args.limit)
        if args.surface:
            result["surface"] = surface_thoughts(path_from_config(args,"db"), limit=1)
        emit(result, as_json=args.json); return
    if args.cmd == "surface":
        emit(surface_thoughts(path_from_config(args,"db"), limit=args.limit), as_json=args.json); return
    if args.cmd == "feedback":
        if args.accept: feedback_type = "accept"; snooze = None
        elif args.deny: feedback_type = "deny"; snooze = None
        elif args.snooze: feedback_type = "snooze"; snooze = args.snooze
        elif args.kill: feedback_type = "kill"; snooze = None
        elif args.acted: feedback_type = "acted"; snooze = None
        elif args.already_done: feedback_type = "already_done"; snooze = None
        elif args.too_obvious: feedback_type = "too_obvious"; snooze = None
        else: feedback_type = "good_but_later"; snooze = None
        emit(record_feedback(path_from_config(args,"db"), args.thought_id, feedback_type, reason=args.reason, snooze=snooze), as_json=args.json); return
    if args.cmd == "explain":
        emit(explain_thought(path_from_config(args,"db"), args.thought_id), as_json=args.json); return
    if args.cmd == "task":
        db_path = path_from_config(args,"db")
        try:
            if args.task_cmd == "list":
                result = list_thought_tasks(db_path, status=args.status)
            elif args.task_cmd == "update":
                result = update_thought_task(db_path, args.task_id, args.status, evidence=args.evidence)
            elif args.task_cmd == "writeback":
                result = record_thought_writeback(db_path, args.task_id, target=args.target, evidence=args.evidence)
            elif args.task_cmd == "reminder":
                result = record_thought_reminder(db_path, args.task_id, reminder_id=args.reminder_id, evidence=args.evidence)
            elif args.task_cmd == "dismiss":
                result = dismiss_thought_task(db_path, args.task_id, reason=args.reason)
            else:
                raise ValueError(f"unknown task command: {args.task_cmd}")
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc), "command": "task"}, indent=2, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2, ensure_ascii=False)); return
    if args.cmd == "dedup":
        result = run_dedup(args)
        if not result.get("ok", False):
            raise SystemExit(1)
        return
    db_path = path_from_config(args,"db")
    out_path = path_from_config(args,"out", required=args.cmd in {"thought", "run-once"})
    stats = ingest_vault(path_from_config(args,"vault"),db_path,hints_from_args(args),args.max_notes,rebuild=not args.append,follow_symlinks=args.follow_symlinks) if args.cmd == "run-once" else {}
    generated=generate_proactive_thought(db_path,hints=hints_from_args(args),hops=args.hops); image=render_card(generated,out_path); thought_id=save_thought(db_path,generated,str(image))
    print(json.dumps({"id":thought_id,"stats":stats,"title":generated["title"],"insight":generated["insight"],"action":generated["action"],"why_now":generated.get("why_now"),"score":generated.get("score"),"contract":generated.get("contract"),"path":[n.get("name") for n in generated["path"]],"image":str(image),"db":str(db_path)}, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
