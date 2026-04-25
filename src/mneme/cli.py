from __future__ import annotations

import argparse, json
from pathlib import Path
from .core import DEFAULT_HINTS, generate_thought, ingest_vault, save_thought, walk_graph
from .render import render_card


def parse_hints(value: str | None):
    return DEFAULT_HINTS if not value else [p.strip() for p in value.split(",") if p.strip()]


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(prog="mneme", description="Graph-based memory paths for AI agents"); sub=parser.add_subparsers(dest="cmd", required=True)
    p=sub.add_parser("ingest"); p.add_argument("--vault",required=True,type=Path); p.add_argument("--db",required=True,type=Path); p.add_argument("--hints"); p.add_argument("--max-notes",type=int)
    p=sub.add_parser("thought"); p.add_argument("--db",required=True,type=Path); p.add_argument("--out",required=True,type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5)
    p=sub.add_parser("run-once"); p.add_argument("--vault",required=True,type=Path); p.add_argument("--db",required=True,type=Path); p.add_argument("--out",required=True,type=Path); p.add_argument("--hints"); p.add_argument("--hops",type=int,default=5); p.add_argument("--max-notes",type=int)
    args=parser.parse_args(argv)
    if args.cmd == "ingest":
        print(json.dumps(ingest_vault(args.vault,args.db,parse_hints(args.hints),args.max_notes), indent=2, ensure_ascii=False)); return
    stats = ingest_vault(args.vault,args.db,parse_hints(args.hints),args.max_notes) if args.cmd == "run-once" else {}
    path=walk_graph(args.db,hops=args.hops,hints=parse_hints(args.hints)); generated=generate_thought(args.db,path); image=render_card(generated,args.out); thought_id=save_thought(args.db,generated,str(image))
    print(json.dumps({"id":thought_id,"stats":stats,"title":generated["title"],"insight":generated["insight"],"action":generated["action"],"path":[n.get("name") for n in generated["path"]],"image":str(image),"db":str(args.db)}, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
