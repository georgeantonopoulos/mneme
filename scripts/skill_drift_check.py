#!/usr/bin/env python3
"""Check that a private Mneme skill has not drifted from the public skill.

The public skill is the source of reusable behaviour. Private deployments may
append local-only guidance, but that guidance must live in one clearly fenced
section so private facts do not leak upstream and public fixes are not lost.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_SKILL = ROOT / "skills" / "mneme" / "SKILL.md"
DEFAULT_PRIVATE_SECTION = "## Private Runtime Additions"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip() + "\n"


def check_drift(public_skill: Path, private_skill: Path, private_section: str = DEFAULT_PRIVATE_SECTION) -> list[str]:
    public = _read(public_skill)
    private = _read(private_skill)

    if private == public:
        return []

    marker = f"\n{private_section}\n"
    if marker not in private:
        return [
            f"private skill diverges from public skill without fenced section {private_section!r}",
            "expected either exact equality or public skill followed by the private section",
        ]

    before, _sep, _after = private.partition(marker)
    before = before.rstrip() + "\n"
    if before != public:
        return [
            "private skill changed public-controlled content before the private section",
            "move local-only guidance below the private section or upstream the generic public change",
        ]

    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check public/private Mneme skill drift")
    parser.add_argument("--public-skill", type=Path, default=DEFAULT_PUBLIC_SKILL)
    parser.add_argument(
        "--private-skill",
        type=Path,
        default=os.environ.get("MNEME_PRIVATE_SKILL_PATH"),
        help="Private skill path, or set MNEME_PRIVATE_SKILL_PATH. If omitted, the check is skipped.",
    )
    parser.add_argument("--private-section", default=DEFAULT_PRIVATE_SECTION)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    public_skill = args.public_skill.expanduser()
    private_skill = Path(args.private_skill).expanduser() if args.private_skill else None

    if private_skill is None:
        print("skill drift check skipped: set MNEME_PRIVATE_SKILL_PATH or pass --private-skill")
        return 0
    if not public_skill.exists():
        print(f"public skill not found: {public_skill}", file=sys.stderr)
        return 2
    if not private_skill.exists():
        print(f"private skill not found: {private_skill}", file=sys.stderr)
        return 2

    failures = check_drift(public_skill, private_skill, private_section=args.private_section)
    if failures:
        print("skill drift check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("skill drift check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
