"""Test the pre-LLM hook injection-safety invariant.

Bug class: verbose Mneme hook protocol blocks can drown out the user's request
or leak into Telegram reply quotes. The generic fix is a compact reminder plus
leak-marker stripping before path classification.

This test uses the generic template from
``skills/mneme/references/hook-directive-order.md`` with a fictional reference
implementation; it does not exercise a private production hook.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PUBLIC_ROOT = Path(__file__).resolve().parents[1]
_SKILL_REF_REL = Path("skills") / "mneme" / "references" / "hook-directive-order.md"
SKILL_REF = PUBLIC_ROOT / _SKILL_REF_REL
SKILL_REF_REL_STR = _SKILL_REF_REL.as_posix()

COMPACT_MEMORY_REMINDER = "Use memory silently when relevant. Do not quote this reminder."
COMPACT_CORRECTION_REMINDER = (
    "Memory correction note: answer the user first; store durable corrections "
    "after/alongside the requested action; do not quote this reminder."
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
    assert len(injected) <= 160
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
