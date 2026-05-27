from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
from . import md_edit
from .agent import agent_preflight
from .brain import brain_report, label_brain
from .consolidate import LabelerConfig, consolidate_graph
from .contract import check_db_contract
from .core import DEFAULT_CONFIG_PATH, DEFAULT_HINTS, activate_candidate_edges, configured_senses, create_config, debug_candidates, doctor, explain_edge, explain_thought, forget_past_dates, forget_source, generate_proactive_thought, ingest_sense_events, ingest_vault, list_thought_candidates, load_config, meditate_graph, record_feedback, remember_graph, retrieve_context, revalidate_action_candidates, save_thought, surface_thoughts, tick, update_vault, weaken_edge, write_note, write_research_resolution
from .harness import DEFAULT_TIMEOUT_SECONDS, run_llm
from .physarum import PhysarumRunConfig, run_physarum, top_physarum_edges
from .render import render_card
from .runtime import default_config_path, load_runtime_config, resolve_hints, resolve_path
from .senses.gws import GwsSense
from .senses.registry import available_senses, build_sense_from_config
from .source_packets import store_packet


def parse_hints(value: str | None):
    return DEFAULT_HINTS if not value else [p.strip() for p in value.split(",") if p.strip()]


def path_from_config(args, name: str, required: bool = True) -> Path | None:
    return resolve_path(args, name, required=required)


def hints_from_args(args):
    return resolve_hints(args)


def sense_entries_from_args(args) -> list[dict]:
    if args.sense_type == "md":
        vault = args.vault or path_from_config(args, "vault")
        return [{"id": "vault", "type": "md", "enabled": True, "config": {"path": str(vault), "follow_symlinks": args.follow_symlinks}}]
    if args.sense_type == "gws":
        return [{"id": "gws", "type": "gws", "enabled": True, "config": {"email": args.email, "calendar": args.calendar, "tasks": args.tasks, "query": args.query}}]
    if args.sense_type == "hermes_sessions":
        return [{"id": "hermes-sessions", "type": "hermes_sessions", "enabled": True, "config": {"path": os.path.expanduser("~/.hermes/sessions"), "limit": args.limit}}]
    if args.sense_type == "notion":
        return [{"id": "notion", "type": "notion", "enabled": True, "config": {"database_id": args.database_id, "token": args.token}}]
    cfg = load_runtime_config(getattr(args, "config", None) or DEFAULT_CONFIG_PATH)
    return [entry for entry in configured_senses(cfg) if entry.get("enabled", True)]


def run_sense_entries(args, entries: list[dict]) -> dict:
    import sqlite3

    db_path = path_from_config(args, "db", required=not args.dry_run)
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


def labeler_from_args(args) -> LabelerConfig:
    return LabelerConfig(
        provider=getattr(args, "label_provider", None),
        model=getattr(args, "label_model", None),
        command=getattr(args, "label_command", None),
        timeout=getattr(args, "label_timeout", DEFAULT_TIMEOUT_SECONDS),
        max_clusters=getattr(args, "label_max_clusters", 25),
    )


def add_labeler_args(p) -> None:
    p.add_argument("--label-provider",help="Optional label provider, for example 'ollama' or any label used with --label-command")
    p.add_argument("--label-model",help="Model name for provider-backed labelling, for example qwen3:1.7b")
    p.add_argument("--label-command",help="Custom command used by the harness for labelling; prompt is sent on stdin unless {prompt} is present")
    p.add_argument("--label-timeout",type=int,default=DEFAULT_TIMEOUT_SECONDS)


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(prog="mneme", description="Graph-based memory paths for AI agents")
    parser.add_argument("--config", type=Path, default=default_config_path(), help="Config path (default: $MNEME_CONFIG or ~/.config/mneme/config.json)")
    sub=parser.add_subparsers(dest="cmd", required=True)
    p=sub.add_parser("init", help="Create a Mneme config file")
    p.add_argument("--vault",required=True,type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--out",type=Path)
    p.add_argument("--hints")
    p.add_argument("--force",action="store_true",help="Overwrite an existing config")
    sub.add_parser("doctor", help="Validate config, vault, and output paths")
    p=sub.add_parser("ingest")
    p.add_argument("--vault",type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--max-notes",type=int)
    p.add_argument("--append",action="store_true",help="Append/update instead of rebuilding the graph; can retain stale private data")
    p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked Markdown files that resolve inside the vault")
    p=sub.add_parser("update", help="Synchronize graph tables from the current vault while preserving thought history")
    p.add_argument("--vault",type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--max-notes",type=int)
    p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked Markdown files that resolve inside the vault")
    p=sub.add_parser("write", help="Safely create, append, or overwrite a Markdown note inside a vault")
    p.add_argument("--vault",type=Path)
    p.add_argument("--path",required=True,help="Relative .md path inside the vault")
    p.add_argument("--mode",choices=["create","append","overwrite"],default="create")
    p.add_argument("--content",help="Markdown content; omit to read from stdin")
    note=sub.add_parser("note", help="Path-safe Markdown note editor")
    note_sub=note.add_subparsers(dest="note_cmd", required=True)
    p=note_sub.add_parser("read", help="Read a note, optionally limited to one heading")
    p.add_argument("path")
    p.add_argument("--vault",type=Path)
    p.add_argument("--heading")
    p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("write", help="Create, append, or overwrite a note atomically")
    p.add_argument("path")
    p.add_argument("--vault",type=Path)
    p.add_argument("--mode",choices=["create","append","overwrite"],default="append")
    p.add_argument("--content",help="Markdown content; omit to read from stdin")
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("replace", help="Exact string replacement with optional dry-run diff")
    p.add_argument("path")
    p.add_argument("--vault",type=Path)
    p.add_argument("--find",required=True)
    p.add_argument("--replace",required=True)
    p.add_argument("--all",action="store_true",dest="replace_all")
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("upsert-section", help="Replace or append a Markdown heading section")
    p.add_argument("path")
    p.add_argument("--vault",type=Path)
    p.add_argument("--heading",required=True)
    p.add_argument("--content",required=True)
    p.add_argument("--level",type=int,default=2)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--force",action="store_true")
    p=note_sub.add_parser("add-bullet", help="Add a deduped bullet under a heading")
    p.add_argument("path")
    p.add_argument("--vault",type=Path)
    p.add_argument("--heading",required=True)
    p.add_argument("--bullet",required=True)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--force",action="store_true")
    p=sub.add_parser("resolve", help="Write a research-resolution JSON payload to Markdown and weighted graph edges")
    p.add_argument("--vault",type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--file",type=Path,help="JSON payload file; omit to read JSON from stdin")
    p.add_argument("--active-threshold",type=float,default=0.9)
    p=sub.add_parser("candidates", help="List scored proactive thought candidates")
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--hops",type=int,default=5)
    p.add_argument("--limit",type=int,default=5)
    p=sub.add_parser("debug-candidates", help="Explain scored candidates, including suppressed items when requested")
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--hops",type=int,default=5)
    p.add_argument("--limit",type=int,default=20)
    p.add_argument("--include-skipped",action="store_true")
    p=sub.add_parser("retrieve", help="Build a prompt-time context pack from local graph evidence")
    p.add_argument("--db",type=Path)
    p.add_argument("--prompt",help="Prompt text; omit to read from stdin")
    p.add_argument("--budget",type=int,default=2500)
    p.add_argument("--max-items",type=int,default=8)
    p.add_argument("--hints")
    p.add_argument("--no-candidates",action="store_true",help="Exclude candidate edges from retrieval context")
    contract=sub.add_parser("contract", help="Validate Mneme graph and output contract invariants")
    contract_sub=contract.add_subparsers(dest="contract_cmd", required=True)
    p=contract_sub.add_parser("check", help="Fail when graph contract invariants are violated")
    p.add_argument("--db",type=Path)
    agent=sub.add_parser("agent", help="Agent-facing Mneme runtime entrypoints")
    agent_sub=agent.add_subparsers(dest="agent_cmd", required=True)
    p=agent_sub.add_parser("preflight", help="Return prompt-safe context, surfaced thoughts, and mandatory contract rules")
    p.add_argument("--db",type=Path)
    p.add_argument("--prompt",help="Prompt text; omit to read from stdin")
    p.add_argument("--budget",type=int,default=2500)
    p.add_argument("--max-items",type=int,default=8)
    p.add_argument("--surface-limit",type=int,default=5)
    p.add_argument("--hints")
    p.add_argument("--no-candidates",action="store_true",help="Exclude candidate edges from retrieval context")
    packet=sub.add_parser("packet", help="Create sanitized untrusted source packets")
    packet_sub=packet.add_subparsers(dest="packet_cmd", required=True)
    p=packet_sub.add_parser("create", help="Persist raw source data and sanitized packet metadata")
    p.add_argument("--packet-dir",type=Path,default=Path(os.environ.get("MNEME_PACKET_DIR", ".mneme/source_packets")))
    p.add_argument("--source",required=True)
    p.add_argument("--kind",default="source")
    p.add_argument("--raw-path",type=Path)
    p.add_argument("--text")
    p.add_argument("--text-path",type=Path,help="Read extracted untrusted text from a file instead of argv")
    p.add_argument("--metadata-json",default="{}")
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("surface", help="Surface thought cards from the same scored retrieval and brain labels")
    p.add_argument("--db",type=Path)
    p.add_argument("--prompt",help="Prompt text; omit for hint-led surfacing")
    p.add_argument("--limit",type=int,default=5)
    p.add_argument("--hops",type=int,default=5)
    p.add_argument("--hints")
    p.add_argument("--no-candidates",action="store_true",help="Exclude candidate synapses from thought surfacing")
    p.add_argument("--json",action="store_true")
    sense=sub.add_parser("sense", help="List and run source senses")
    sense_sub=sense.add_subparsers(dest="sense_cmd", required=True)
    p=sense_sub.add_parser("list", help="List configured and available senses")
    p.add_argument("--json",action="store_true")
    p=sense_sub.add_parser("run", help="Collect one or all senses and ingest normalized events")
    p.add_argument("sense_type", choices=["md","gws","notion","hermes_sessions","all"])
    p.add_argument("--vault",type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--limit",type=int)
    p.add_argument("--follow-symlinks",action="store_true")
    p.add_argument("--email",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--calendar",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--tasks",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--query")
    p.add_argument("--database-id", help="Notion database id for the notion sense")
    p.add_argument("--token", help="Notion API token for the notion sense; prefer NOTION_TOKEN env/config to avoid shell-history exposure")
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("tick", help="Run the cognition pulse and update thought candidates")
    p.add_argument("--db",type=Path)
    p.add_argument("--hints")
    p.add_argument("--sense",choices=["all","md","gws","notion","hermes_sessions"])
    p.add_argument("--surface",action="store_true")
    p.add_argument("--limit",type=int,default=100)
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("feedback", help="Record feedback for a surfaced thought candidate")
    p.add_argument("thought_id")
    p.add_argument("--db",type=Path)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--accept",action="store_true")
    group.add_argument("--deny",action="store_true")
    group.add_argument("--snooze")
    group.add_argument("--kill",action="store_true")
    group.add_argument("--acted",action="store_true")
    group.add_argument("--already-done",action="store_true")
    group.add_argument("--too-obvious",action="store_true")
    group.add_argument("--good-but-later",action="store_true")
    p.add_argument("--reason")
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("explain", help="Explain why a thought candidate surfaced")
    p.add_argument("thought_id")
    p.add_argument("--db",type=Path)
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("consolidate", help="Create graph clusters and node roles for retrieval")
    p.add_argument("--db",type=Path)
    p.add_argument("--iterations",type=int,default=12)
    p.add_argument("--min-cluster-size",type=int,default=2)
    add_labeler_args(p)
    p.add_argument("--label-max-clusters",type=int,default=25)
    brain=sub.add_parser("brain", help="Hermes-ready working-brain labelling and reports")
    brain_sub=brain.add_subparsers(dest="brain_cmd", required=True)
    p=brain_sub.add_parser("label", help="Label clusters, nodes, synapses, and relationship types through the harness")
    p.add_argument("--db",type=Path)
    p.add_argument("--targets",default="cluster,node,synapse,relationship")
    p.add_argument("--max-clusters",type=int,default=25)
    p.add_argument("--max-nodes",type=int,default=50)
    p.add_argument("--max-synapses",type=int,default=50)
    p.add_argument("--max-relationships",type=int,default=25)
    add_labeler_args(p)
    p=brain_sub.add_parser("report", help="Summarize latest brain labels and obvious quality risks")
    p.add_argument("--db",type=Path)
    p.add_argument("--limit",type=int,default=20)
    p=sub.add_parser("promote-candidates", help="Explicitly activate candidate edges after review; default only promotes validated research candidates")
    p.add_argument("--db",type=Path)
    p.add_argument("--mode",choices=["validated-only","all"],default="validated-only")
    p.add_argument("--dry-run",action="store_true")
    remember=sub.add_parser("remember", help="Add or remove scoped agent memory without editing vault notes")
    remember_sub=remember.add_subparsers(dest="remember_cmd", required=True)
    p=remember_sub.add_parser("add", help="Add a mneme:// scoped memory payload to the graph")
    p.add_argument("--db",type=Path)
    p.add_argument("--file",type=Path,help="JSON payload file; omit to read JSON from stdin")
    p.add_argument("--dry-run",action="store_true")
    p=remember_sub.add_parser("remove", help="Remove all graph rows for a mneme:// scoped memory source")
    p.add_argument("--db",type=Path)
    p.add_argument("--source-path",required=True)
    p.add_argument("--dry-run",action="store_true")
    p=sub.add_parser("thought")
    p.add_argument("--db",type=Path)
    p.add_argument("--out",type=Path)
    p.add_argument("--hints")
    p.add_argument("--hops",type=int,default=5)
    p=sub.add_parser("explain-edge")
    p.add_argument("edge_id")
    p.add_argument("--db",required=True,type=Path)
    p=sub.add_parser("weaken-edge", help="Reduce edge strength after negative feedback without killing")
    p.add_argument("edge_id")
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("--reason",default="User dismissed surfaced proposal")
    p.add_argument("--factor",type=float,default=0.5)
    p.add_argument("--floor",type=float,default=0.0)
    p=sub.add_parser("forget", help="Mneme's version of forgetting — set edge weights to 0 for past-dated observations without deleting")
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("--days-threshold",type=int,default=30,help="Forget observations with dates older than this many days (default: 30)")
    p.add_argument("--dry-run",action="store_true",help="Show what would be forgotten without applying changes")
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("meditate", help="Run a creative dreaming pass over random graph walks; mostly silent unless useful")
    p.add_argument("--db",type=Path)
    p.add_argument("--iterations",type=int,default=10)
    p.add_argument("--walks",type=int,default=6)
    p.add_argument("--random-seed",type=int)
    p.add_argument("--model")
    p.add_argument("--reflection-provider",help="Provider label for LLM reflection; omit for deterministic fallback")
    p.add_argument("--reflection-command",help="Custom reflection command. Prompt is sent on stdin unless {prompt} appears")
    p.add_argument("--reflection-timeout",type=int,default=120)
    p.add_argument("--min-surface-score",type=float,default=0.72)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--json",action="store_true")
    bridge=sub.add_parser("bridge", help="Bridge private action candidates to live senses before surfacing")
    bridge_sub=bridge.add_subparsers(dest="bridge_cmd", required=True)
    p=bridge_sub.add_parser("revalidate", help="Use current sense packets to revalidate meditation action candidates")
    p.add_argument("--db",type=Path)
    p.add_argument("--sense",choices=["all","gws","notion","md","hermes_sessions"],default="all")
    p.add_argument("--limit",type=int,default=25)
    p.add_argument("--candidate-limit",type=int,default=20)
    p.add_argument("--min-match-score",type=float,default=0.34)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--json",action="store_true")
    harness=sub.add_parser("harness", help="Minimal provider-neutral agent harness")
    harness_sub=harness.add_subparsers(dest="harness_cmd", required=True)
    p=harness_sub.add_parser("run", help="Run a prompt through a provider command")
    p.add_argument("prompt", nargs="?", help="Prompt text; omit to read from stdin")
    p.add_argument("--provider", default="echo", help="Built-in provider name, or any label when --command is supplied")
    p.add_argument("--command", help="Command to run; use {prompt} for argv prompts, otherwise stdin is used")
    p.add_argument("--cwd", type=Path, help="Working directory for the provider command")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    physarum=sub.add_parser("physarum", help="Run structure-only Physarum-style graph-flow experiments")
    physarum_sub=physarum.add_subparsers(dest="physarum_cmd", required=True)
    p=physarum_sub.add_parser("run", help="Run a Physarum-style flow over the graph without changing edge status")
    p.add_argument("--db",type=Path)
    p.add_argument("--iterations",type=int,default=80)
    p.add_argument("--terminals",type=int,default=24)
    p.add_argument("--paths-per-iteration",type=int,default=12)
    p.add_argument("--decay",type=float,default=0.92)
    p.add_argument("--reinforcement",type=float,default=1.0)
    p.add_argument("--relation-penalty",type=float,default=1.0)
    p.add_argument("--hub-penalty",type=float,default=0.35)
    p.add_argument("--seed",type=int,default=13)
    p=physarum_sub.add_parser("top", help="Show top reinforced edges from a Physarum run")
    p.add_argument("run_id")
    p.add_argument("--db",type=Path)
    p.add_argument("--limit",type=int,default=20)
    p=sub.add_parser("run-once")
    p.add_argument("--vault",type=Path)
    p.add_argument("--db",type=Path)
    p.add_argument("--out",type=Path)
    p.add_argument("--hints")
    p.add_argument("--hops",type=int,default=5)
    p.add_argument("--max-notes",type=int)
    p.add_argument("--append",action="store_true",help="Append/update instead of rebuilding the graph; can retain stale private data")
    p.add_argument("--follow-symlinks",action="store_true",help="Follow symlinked markdown files that resolve inside the vault")
    args=parser.parse_args(argv)
    if args.cmd == "init":
        if args.config.exists() and not args.force:
            raise SystemExit(f"config already exists: {args.config}; pass --force to overwrite")
        print(json.dumps(create_config(args.config,args.vault,args.db,args.out,parse_hints(args.hints) if args.hints else None), indent=2, ensure_ascii=False))
        return
    if args.cmd == "doctor":
        print(json.dumps(doctor(args.config), indent=2, ensure_ascii=False))
        return
    if args.cmd == "ingest":
        print(json.dumps(ingest_vault(path_from_config(args,"vault"),path_from_config(args,"db"),hints_from_args(args),args.max_notes,rebuild=not args.append,follow_symlinks=args.follow_symlinks), indent=2, ensure_ascii=False))
        return
    if args.cmd == "update":
        print(json.dumps(update_vault(path_from_config(args,"vault"),path_from_config(args,"db"),hints_from_args(args),args.max_notes,follow_symlinks=args.follow_symlinks), indent=2, ensure_ascii=False))
        return
    if args.cmd == "write":
        content = args.content if args.content is not None else sys.stdin.read()
        print(json.dumps(write_note(path_from_config(args,"vault"),args.path,content,mode=args.mode), indent=2, ensure_ascii=False))
        return
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
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if args.cmd == "resolve":
        payload = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        print(json.dumps(write_research_resolution(path_from_config(args,"vault"),path_from_config(args,"db"),payload,active_threshold=args.active_threshold), indent=2, ensure_ascii=False))
        return
    if args.cmd == "explain-edge":
        print(json.dumps(explain_edge(args.db,args.edge_id), indent=2, ensure_ascii=False))
        return
    if args.cmd == "weaken-edge":
        print(json.dumps(weaken_edge(args.db, args.edge_id, reason=args.reason, factor=args.factor, floor=args.floor), indent=2, ensure_ascii=False))
        return
    if args.cmd == "forget":
        print(json.dumps(forget_past_dates(args.db, days_threshold=args.days_threshold, dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return
    if args.cmd == "meditate":
        result = meditate_graph(path_from_config(args,"db"), iterations=args.iterations, walks=args.walks, random_seed=args.random_seed, model=args.model, creative=True, min_surface_score=args.min_surface_score, dry_run=args.dry_run, reflection_provider=args.reflection_provider, reflection_command=args.reflection_command, reflection_timeout=args.reflection_timeout)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result.get("user_message") or "[SILENT]")
        return
    if args.cmd == "bridge":
        if args.bridge_cmd == "revalidate":
            class SenseArgs:
                pass
            sense_args = SenseArgs()
            sense_args.sense_type = args.sense
            sense_args.vault = None
            sense_args.db = args.db
            sense_args.config = args.config
            sense_args.hints = None
            sense_args.limit = args.limit
            sense_args.follow_symlinks = False
            sense_args.email = sense_args.calendar = sense_args.tasks = True
            sense_args.query = None
            sense_args.database_id = None
            sense_args.token = None
            sense_args.dry_run = True
            entries = sense_entries_from_args(sense_args)
            events = []
            for entry in entries:
                sense = build_sense_from_config(entry)
                events.extend(list(sense.collect(limit=args.limit)))
            result = revalidate_action_candidates(path_from_config(args,"db"), events=events, candidate_limit=args.candidate_limit, min_match_score=args.min_match_score, dry_run=args.dry_run)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("[SILENT]" if result.get("revalidated", 0) == 0 else json.dumps(result, ensure_ascii=False))
            return
    if args.cmd == "candidates":
        print(json.dumps(list_thought_candidates(path_from_config(args,"db"), limit=args.limit, hops=args.hops, hints=hints_from_args(args)), indent=2, ensure_ascii=False))
        return
    if args.cmd == "debug-candidates":
        print(json.dumps(debug_candidates(path_from_config(args,"db"), limit=args.limit, hops=args.hops, hints=hints_from_args(args), include_skipped=args.include_skipped), indent=2, ensure_ascii=False))
        return
    if args.cmd == "retrieve":
        prompt = args.prompt if args.prompt is not None else sys.stdin.read()
        print(json.dumps(retrieve_context(path_from_config(args,"db"), prompt, budget=args.budget, max_items=args.max_items, hints=hints_from_args(args), include_candidates=not args.no_candidates), indent=2, ensure_ascii=False))
        return
    if args.cmd == "contract":
        if args.contract_cmd == "check":
            report = check_db_contract(path_from_config(args,"db"))
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            if report.status != "pass":
                raise SystemExit(1)
            return
    if args.cmd == "agent":
        if args.agent_cmd == "preflight":
            prompt = args.prompt if args.prompt is not None else sys.stdin.read()
            result = agent_preflight(
                path_from_config(args,"db"),
                prompt,
                budget=args.budget,
                max_items=args.max_items,
                surface_limit=args.surface_limit,
                hints=hints_from_args(args),
                include_candidates=not args.no_candidates,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if result["contract"]["status"] != "pass":
                raise SystemExit(1)
            return
    if args.cmd == "packet":
        if args.packet_cmd == "create":
            metadata = json.loads(args.metadata_json)
            if args.text is not None and args.text_path is not None:
                raise SystemExit("provide only one of --text or --text-path")
            text = args.text if args.text is not None else (args.text_path.read_text(encoding="utf-8", errors="replace") if args.text_path else (args.raw_path.read_text(encoding="utf-8", errors="replace") if args.raw_path else sys.stdin.read()))
            print(json.dumps(store_packet(packet_dir=args.packet_dir, source=args.source, kind=args.kind, raw_path=args.raw_path, text=text, metadata=metadata), indent=2, ensure_ascii=False))
            return
    if args.cmd == "surface":
        print(json.dumps(surface_thoughts(path_from_config(args,"db"), args.prompt, limit=args.limit, hops=args.hops, hints=hints_from_args(args), include_candidates=not args.no_candidates), indent=2, ensure_ascii=False))
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
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        print(json.dumps(run_sense_entries(args, sense_entries_from_args(args)), indent=2, ensure_ascii=False))
        return
    if args.cmd == "tick":
        if args.sense:
            class SenseArgs:
                pass
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
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if args.cmd == "feedback":
        if args.accept:
            feedback_type = "accept"; snooze = None
        elif args.deny:
            feedback_type = "deny"; snooze = None
        elif args.snooze:
            feedback_type = "snooze"; snooze = args.snooze
        elif args.kill:
            feedback_type = "kill"; snooze = None
        elif args.acted:
            feedback_type = "acted"; snooze = None
        elif args.already_done:
            feedback_type = "already_done"; snooze = None
        elif args.too_obvious:
            feedback_type = "too_obvious"; snooze = None
        else:
            feedback_type = "good_but_later"; snooze = None
        print(json.dumps(record_feedback(path_from_config(args,"db"), args.thought_id, feedback_type, reason=args.reason, snooze=snooze), indent=2, ensure_ascii=False))
        return
    if args.cmd == "explain":
        print(json.dumps(explain_thought(path_from_config(args,"db"), args.thought_id), indent=2, ensure_ascii=False))
        return
    if args.cmd == "consolidate":
        labeler = labeler_from_args(args)
        print(json.dumps(consolidate_graph(path_from_config(args,"db"), iterations=args.iterations, min_cluster_size=args.min_cluster_size, labeler=labeler), indent=2, ensure_ascii=False))
        return
    if args.cmd == "brain":
        db_path = path_from_config(args,"db")
        if args.brain_cmd == "label":
            targets = [part.strip() for part in args.targets.split(",") if part.strip()]
            print(json.dumps(label_brain(db_path, labeler=labeler_from_args(args), targets=targets, max_clusters=args.max_clusters, max_nodes=args.max_nodes, max_synapses=args.max_synapses, max_relationships=args.max_relationships), indent=2, ensure_ascii=False))
            return
        if args.brain_cmd == "report":
            print(json.dumps(brain_report(db_path, limit=args.limit), indent=2, ensure_ascii=False))
            return
    if args.cmd == "promote-candidates":
        print(json.dumps(activate_candidate_edges(path_from_config(args,"db"), mode=args.mode, dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return
    if args.cmd == "remember":
        db_path = path_from_config(args,"db")
        if args.remember_cmd == "add":
            payload = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
            print(json.dumps(remember_graph(db_path, payload, dry_run=args.dry_run), indent=2, ensure_ascii=False))
            return
        if args.remember_cmd == "remove":
            print(json.dumps(forget_source(db_path, args.source_path, dry_run=args.dry_run), indent=2, ensure_ascii=False))
            return
    if args.cmd == "harness":
        prompt = args.prompt if args.prompt is not None else sys.stdin.read()
        result = run_llm(prompt, provider=args.provider, command=args.command, cwd=args.cwd, timeout=args.timeout)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    if args.cmd == "physarum":
        db_path = path_from_config(args,"db")
        if args.physarum_cmd == "run":
            cfg = PhysarumRunConfig(iterations=args.iterations, terminals=args.terminals, paths_per_iteration=args.paths_per_iteration, decay=args.decay, reinforcement=args.reinforcement, relation_penalty=args.relation_penalty, hub_penalty=args.hub_penalty, seed=args.seed)
            print(json.dumps(run_physarum(db_path, cfg), indent=2, ensure_ascii=False))
            return
        if args.physarum_cmd == "top":
            print(json.dumps(top_physarum_edges(db_path, args.run_id, args.limit), indent=2, ensure_ascii=False))
            return
    db_path = path_from_config(args,"db")
    out_path = path_from_config(args,"out", required=args.cmd in {"thought", "run-once"})
    stats = ingest_vault(path_from_config(args,"vault"),db_path,hints_from_args(args),args.max_notes,rebuild=not args.append,follow_symlinks=args.follow_symlinks) if args.cmd == "run-once" else {}
    generated=generate_proactive_thought(db_path,hints=hints_from_args(args),hops=args.hops)
    image=render_card(generated,out_path)
    thought_id=save_thought(db_path,generated,str(image))
    print(json.dumps({"id":thought_id,"stats":stats,"title":generated["title"],"insight":generated["insight"],"action":generated["action"],"why_now":generated.get("why_now"),"score":generated.get("score"),"path":[n.get("name") for n in generated["path"]],"image":str(image),"db":str(db_path)}, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
