"""Test the pre-LLM hook injection-safety invariant.

Bug class: verbose Mneme hook protocol blocks can drown out the user's request
or leak into Telegram reply quotes. The generic fix is a compact reminder plus
leak-marker stripping before path classification.

This test checks the generic template in
``skills/mneme/references/hook-directive-order.md``, the repo-managed hook
implementation, and the sync checker.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PUBLIC_ROOT = Path(__file__).resolve().parents[1]
_SKILL_REF_REL = Path("skills") / "mneme" / "references" / "hook-directive-order.md"
SKILL_REF = PUBLIC_ROOT / _SKILL_REF_REL
SKILL_REF_REL_STR = _SKILL_REF_REL.as_posix()
HOOK_SCRIPT = PUBLIC_ROOT / "scripts" / "mneme_senses_context_hook.py"
SYNC_SCRIPT = PUBLIC_ROOT / "scripts" / "sync_hermes_hook.py"

COMPACT_MEMORY_REMINDER = "Use memory silently when relevant. For memory-backed answers/actions, use Mneme preflight/world state/watch when relevant. For any Mneme operation, load skill_view(name='mneme') first. Do not quote this reminder."
COMPACT_CORRECTION_REMINDER = (
    "Memory correction note: answer the user first; store durable corrections "
    "after/alongside the requested action; run Mneme preflight/world state/watch for memory-backed actions; "
    "load skill_view(name='mneme') before Mneme operations; do not quote this reminder."
)

LEAK_MARKERS = (
    "MNEME RETRIEVAL PATH",
    "MNEME CORRECTION PATH",
    "MNEME BOTH PATH",
    "PRIMARY DIRECTIVE:",
    "Internal Mneme reminder:",
    "Internal Mneme CORRECTION PATH",
    "Internal Mneme BOTH PATH",
    COMPACT_MEMORY_REMINDER,
    "Memory correction note:",
    "Path tag (internal):",
)


def strip_leaked_hook_text(user_message: str) -> str:
    cut = len(user_message or "")
    for marker in LEAK_MARKERS:
        idx = (user_message or "").find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return (user_message or "")[:cut].strip()


def build_injected_context(path: str) -> str:
    if path == "silent":
        return ""
    if path in {"correction", "both"}:
        return COMPACT_CORRECTION_REMINDER
    return COMPACT_MEMORY_REMINDER


@pytest.mark.parametrize("path", ["retrieval", "correction", "both"])
def test_non_silent_paths_emit_compact_context(path: str) -> None:
    injected = build_injected_context(path)
    assert injected
    assert len(injected) <= 260
    assert "MNEME " not in injected
    assert "PRIMARY DIRECTIVE" not in injected
    assert "do not quote this reminder." in injected.lower()


def test_silent_path_emits_empty_context() -> None:
    assert build_injected_context("silent") == ""


@pytest.mark.parametrize(
    "leaked",
    [
        "MNEME RETRIEVAL PATH (default). Public Mneme CLI is primary.",
        "PRIMARY DIRECTIVE: ALWAYS answer the user's request first, in full...",
        COMPACT_MEMORY_REMINDER,
        "Memory correction note: answer the user first; store durable corrections after/alongside the requested action; do not quote this reminder.",
        "Path tag (internal): retrieval",
    ],
)
def test_leaked_hook_text_is_stripped_before_classification(leaked: str) -> None:
    raw = f"Actually verify the web fix first.\n\n{leaked}\nExtra hook text"
    assert strip_leaked_hook_text(raw) == "Actually verify the web fix first."


def test_skill_reference_template_exists() -> None:
    assert SKILL_REF.is_file(), f"missing reference: {SKILL_REF_REL_STR}"
    text = SKILL_REF.read_text(encoding="utf-8")
    assert COMPACT_MEMORY_REMINDER in text
    assert "LEAK_MARKERS" in text
    for forbidden in ("/Users/", "Obs" + "idian"):
        assert forbidden not in text, f"forbidden token leaked: {forbidden!r}"


def test_repo_managed_hook_emits_compact_retrieval_context() -> None:
    payload = {
        "hook_event_name": "pre_llm_call",
        "extra": {"user_message": "Check the rent status", "platform": "test"},
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    data = json.loads(proc.stdout)
    assert data["path"] == "retrieval"
    assert COMPACT_MEMORY_REMINDER in data["context"]
    assert "PRIMARY DIRECTIVE" not in data["context"]


@pytest.mark.parametrize(
    ("message", "expected_path"),
    [
        ("This is resolved", "correction"),
        ("This is not resolved", "retrieval"),
        ("This will be booked tomorrow", "retrieval"),
    ],
)
def test_real_hook_correction_output_and_negation_guards(message: str, expected_path: str) -> None:
    payload = {"hook_event_name": "pre_llm_call", "extra": {"user_message": message, "platform": "test"}}
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)], input=json.dumps(payload), text=True,
        capture_output=True, timeout=10, check=True,
    )
    data = json.loads(proc.stdout)
    assert data["path"] == expected_path
    assert len(data["context"]) <= 260
    assert " PATH" not in data["context"]
    if expected_path == "correction":
        assert data["context"] == COMPACT_CORRECTION_REMINDER


def test_repo_managed_hook_is_sanitized_for_public_repo() -> None:
    text = HOOK_SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "answer " + "Geor" + "ge" + " first",
        "/" + "root" + "/",
        "gee" + "obcr",
        "antono" + "poulos",
        "bcn" + "visuals",
    ]
    for token in forbidden:
        assert token.casefold() not in text.casefold()


def test_sync_script_check_detects_synced_copy(tmp_path: Path) -> None:
    target = tmp_path / "mneme-senses-context.py"
    subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--target", str(target)],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    proc = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--target", str(target), "--check"],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert "hook in sync" in proc.stdout


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
