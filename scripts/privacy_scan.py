#!/usr/bin/env python3
"""Public-repo privacy and artifact scan for Mneme.

This script is intentionally generic. Projects can add comma-separated custom
terms via MNEME_FORBIDDEN_TERMS without storing those private terms in the repo.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".hermes-synced-skills", "dist", "build"}
SKIP_SUFFIXES = {".pyc"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".sqlite", ".db"}
ALLOWED_BINARY_ASSETS = {Path("assets/mneme-header.png")}

ARTIFACT_PATTERNS = ["*.sqlite", "*.sqlite-*", "*.db", "*.pyc", "__pycache__", "thought_*.svg", "thought_*.png", "out"]
BASE_PATTERNS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("absolute_private_path", re.compile(r"(/root/|/home/[^/]+/|C:\\\\Users\\\\)", re.I)),
    ("secret_like_assignment", re.compile(r"(api[_-]?key|secret|token|password|credential)\s*[:=]\s*[\"']?[^\"'\s]{6,}", re.I)),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("common_token_prefix", re.compile(r"\b(ghp|gho|ghu|ghs|github_pat|sk-[A-Za-z0-9]|xox[baprs]-)[A-Za-z0-9_\-]{12,}", re.I)),
]


def iter_files():
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        yield path


def scan_artifacts() -> list[str]:
    failures: list[str] = []
    for pattern in ARTIFACT_PATTERNS:
        for path in ROOT.rglob(pattern):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            rel = path.relative_to(ROOT)
            if rel in ALLOWED_BINARY_ASSETS:
                continue
            failures.append(f"generated artifact: {rel}")
    return failures


def scan_text() -> list[str]:
    patterns = list(BASE_PATTERNS)
    custom = [term.strip() for term in os.environ.get("MNEME_FORBIDDEN_TERMS", "").split(",") if term.strip()]
    for term in custom:
        patterns.append(("custom_forbidden_term", re.compile(re.escape(term), re.I)))

    failures: list[str] = []
    for path in iter_files():
        if path.suffix.lower() in BINARY_SUFFIXES | SKIP_SUFFIXES:
            continue
        text = path.read_text(errors="ignore")
        for label, pattern in patterns:
            for match in pattern.finditer(text):
                rel = path.relative_to(ROOT)
                snippet = match.group(0)[:120].replace("\n", " ")
                # Allow the scanner to describe its own generic regex categories.
                if rel == Path("scripts/privacy_scan.py") and label in {"absolute_private_path", "secret_like_assignment", "private_key_block", "common_token_prefix"}:
                    continue
                failures.append(f"{label}: {rel}: {snippet}")
    return failures


def main() -> int:
    failures = scan_artifacts() + scan_text()
    if failures:
        print("Privacy scan failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("privacy scan ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
