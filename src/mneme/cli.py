from __future__ import annotations

import argparse, json, sys
from pathlib import Path
from . import md_edit
from .core import DEFAULT_CONFIG_PATH, DEFAULT_HINTS, activate_candidate_edges, create_config, doctor, explain_edge, generate_proactive_thought, ingest_vault, list_thought_candidates, load_config, save_thought, update_vault, write_note, write_research_resolution
from .render import render_card


def parse_hints(value: str | None):
    return DEFAULT_HINTS if not value else [p.strip() for p in value.split(",") if p.strip()]


def path_from_config(args, name: str, required: bool = True) -> Path | None:
    value = getattr(args, name, None)
    if value is not None:
        return value
    cfg_path = getattr(args, "config", None) or DEFAULT_CONFIG_PATH
    if Path(cfg_path).exists():
        cfg = load_config(Path(cfg_path))
        if cfg.get(name):
            return Path(cfg[name]).expanduser()
    if required:
        raise SystemExit(f"missing --{name}; provide it or run `mneme init --{name} ...`")
    return None


def hints_from_args(args):
    if getattr(args, "hints", None):
        return parse_hints(args.hints)
    cfg_path = getattr(args, "config", None) or DEFAULT_CONFIG_PATH
    if Path(cfg_path).exists():
        return load_config(Path(cfg_path)).get("hints", DEFAULT_HINTS)
    return DEFAULT_HINTS


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(prog="mneme", description="Graph-based memory paths for AI agents"); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Config path (default: ~/.config/mneme/config.json)"); sub=parser.add_subparsers(dest="cmd", required=True)
    p=sub.add_parser("init", help="Create a Mneme config file"); p.add_argument("--vault",required=True,type=Path); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--force",action="store_true",help="Overwrite an existing config")
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
    p=sub.add_parser("thought"); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5)
    p=sub.add_parser("explain-edge"); p.add_argument("edge_id"); p.add_argument("--db",required=True,type=Path)
    p=sub.add_parser("run-once"); p.add_argument("--vault",type=Path); p.add_argument("--db",type=Path); p.add_argument("--out",type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5); p.add_argument("--max-notes",type=int); p.add_argument("--append",action="store_true",help="Append/update instead of rebuilding the graph; can retain stale private data"); p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked markdown files that resolve inside the vault")
    args=parser.parse_args(argv)
    if args.cmd == "init":
        if args.config.exists() and not args.force:
            raise SystemExit(f"config already exists: {args.config}; pass --force to overwrite")
        print(json.dumps(create_config(args.config,args.vault,args.db,args.out,parse_hints(args.hints) if args.hints else None), indent=2, ensure_ascii=False)); return
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
    if args.cmd == "candidates":
        print(json.dumps(list_thought_candidates(path_from_config(args,"db"), limit=args.limit, hops=args.hops, hints=hints_from_args(args)), indent=2, ensure_ascii=False)); return
    if args.cmd == "promote-candidates":
        print(json.dumps(activate_candidate_edges(path_from_config(args,"db"), mode=args.mode, dry_run=args.dry_run), indent=2, ensure_ascii=False)); return
    db_path = path_from_config(args,"db")
    out_path = path_from_config(args,"out", required=args.cmd in {"thought", "run-once"})
    stats = ingest_vault(path_from_config(args,"vault"),db_path,hints_from_args(args),args.max_notes,rebuild=not args.append,follow_symlinks=args.follow_symlinks) if args.cmd == "run-once" else {}
    generated=generate_proactive_thought(db_path,hints=hints_from_args(args),hops=args.hops); image=render_card(generated,out_path); thought_id=save_thought(db_path,generated,str(image))
    print(json.dumps({"id":thought_id,"stats":stats,"title":generated["title"],"insight":generated["insight"],"action":generated["action"],"why_now":generated.get("why_now"),"score":generated.get("score"),"path":[n.get("name") for n in generated["path"]],"image":str(image),"db":str(db_path)}, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
