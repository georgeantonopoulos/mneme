#!/usr/bin/env python3
"""Sync the repo-managed Mneme pre-LLM hook into a Hermes install.

The canonical hook implementation lives in this repository at
`scripts/mneme_senses_context_hook.py`. Runtime deployments should copy that file
verbatim to `$HERMES_HOME/agent-hooks/mneme-senses-context.py` instead of editing
the local hook by hand.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "scripts" / "mneme_senses_context_hook.py"


def default_target() -> Path:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    return hermes_home / "agent-hooks" / "mneme-senses-context.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync/check the repo-managed Mneme Hermes hook")
    ap.add_argument("--target", type=Path, default=default_target(), help="runtime hook path")
    ap.add_argument("--check", action="store_true", help="only verify target matches source")
    args = ap.parse_args(argv)

    if not SOURCE.is_file():
        print(f"missing source hook: {SOURCE}", file=sys.stderr)
        return 2

    target = args.target.expanduser()
    if args.check:
        if not target.is_file():
            print(f"missing target hook: {target}", file=sys.stderr)
            return 1
        if not filecmp.cmp(SOURCE, target, shallow=False):
            print(f"hook drift: {target} differs from {SOURCE}", file=sys.stderr)
            return 1
        print(f"hook in sync: {target}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, target)
    target.chmod(0o755)
    print(f"synced {SOURCE} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
