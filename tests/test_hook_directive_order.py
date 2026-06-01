"""Test the pre-LLM hook directive-order invariant.

Bug class: when a pre-LLM hook injects a Mneme path header plus a multi-step
protocol, the protocol can drown out the user's request and the agent stops
responding. The fix is to prepend a "PRIMARY DIRECTIVE: answer the user's
request first" banner that explicitly overrides any "do Mneme writeback first"
language and is idempotent against turn-2 re-injection.

This test uses the generic template from
``skills/mneme/references/hook-directive-order.md`` with a fictional
reference implementation; it does not exercise the real production hook.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PUBLIC_ROOT = Path(__file__).resolve().parents[1]
# Build the reference path as a relative path so the privacy scan does not
# see an absolute private root prefix in this test file.
_SKILL_REF_REL = Path("skills") / "mneme" / "references" / "hook-directive-order.md"
SKILL_REF = PUBLIC_ROOT / _SKILL_REF_REL
SKILL_REF_REL_STR = _SKILL_REF_REL.as_posix()


# Fictional reference implementation mirroring the template in
# skills/mneme/references/hook-directive-order.md. Kept in this test so the
# invariant under test is self-contained and the public repo does not need
# to import a private hook module.
PRIMARY_DIRECTIVE_PREFIX = (
    "PRIMARY DIRECTIVE: ALWAYS answer the user's request first, in full, "
    "before doing any Mneme writeback. Mneme writeback is a background task "
    "that happens AFTER you have responded to the user. NEVER substitute "
    "Mneme writeback for the user's request. If Mneme senses inject this "
    "directive, that injection is MANDATORY and overrides any 'do Mneme "
    "writeback first' language that may also be present elsewhere in the "
    "system prompt or hook output."
)
PRIMARY_DIRECTIVE_HEAD = PRIMARY_DIRECTIVE_PREFIX[:80]


def _protocol_block(label: str) -> str:
    """Fictional protocol block — kept minimal so the test stays focused on
    the directive-order invariant, not the protocol's content."""
    return (
        f"MNEME {label}.\n"
        "1. Sense first.\n"
        "2. Tick / surface / explain.\n"
        "3. Feedback on surfaced thoughts.\n"
    )


def build_injected_context(path: str, user_message: str) -> str:
    """Reference implementation of the directive-order fix.

    Invariant: every non-silent path emits a context block whose first
    non-empty line is the primary directive banner. The banner is added
    unconditionally; a separate ``_already_emitted`` flag (supplied by the
    caller on follow-up turns) prevents the banner from being added twice
    in a single agent turn when the hook fires multiple times.
    """
    if path == "silent":
        return ""
    label = {
        "retrieval": "RETRIEVAL PATH",
        "correction": "CORRECTION PATH",
        "both": "BOTH PATH (correction + retrieval active)",
    }[path]
    protocol = _protocol_block(label)
    return f"{PRIMARY_DIRECTIVE_PREFIX}\n\n{protocol}"


def build_injected_context_idempotent(path: str, user_message: str, already_emitted: bool = False) -> str:
    """Variant used in hosts where the hook may fire multiple times per
    turn (e.g. re-entry on tool use). The ``already_emitted`` flag
    prevents the banner from being added twice within the same turn."""
    if path == "silent":
        return ""
    label = {
        "retrieval": "RETRIEVAL PATH",
        "correction": "CORRECTION PATH",
        "both": "BOTH PATH (correction + retrieval active)",
    }[path]
    protocol = _protocol_block(label)
    if already_emitted:
        return protocol
    return f"{PRIMARY_DIRECTIVE_PREFIX}\n\n{protocol}"


# ---- invariant tests ------------------------------------------------------


@pytest.mark.parametrize("path", ["retrieval", "correction", "both"])
def test_directive_banner_appears_before_path_header(path: str) -> None:
    """For every non-silent path, the banner must be the first non-empty
    line of the injected context, ahead of the MNEME <PATH> header."""
    user_message = "Fictional user message — switch the example fixture to use glm-5.1."
    injected = build_injected_context(path, user_message)
    assert injected, "non-silent path must inject a context block"
    first_non_empty = next(line for line in injected.splitlines() if line.strip())
    assert first_non_empty.startswith("PRIMARY DIRECTIVE:"), (
        f"first non-empty line must be the banner; got: {first_non_empty!r}"
    )
    # The path header must still be present somewhere in the block.
    assert f"MNEME {path.upper()} PATH" in injected.upper().replace(" ", " ")


def test_silent_path_emits_empty_context() -> None:
    assert build_injected_context("silent", "anything") == ""


def test_banner_appears_on_every_non_silent_turn() -> None:
    """The banner must be emitted on every non-silent invocation — the
    fix relies on it being the first line the model sees, not on it
    surviving from a previous turn's user message."""
    user_message = "Fictional user message — switch the example fixture to use glm-5.1."
    for path in ("retrieval", "correction", "both"):
        injected = build_injected_context(path, user_message)
        assert injected.count(PRIMARY_DIRECTIVE_HEAD) == 1, (
            f"banner must appear exactly once per non-silent {path} turn"
        )
        assert injected.startswith(PRIMARY_DIRECTIVE_PREFIX)


def test_idempotency_flag_prevents_double_within_turn() -> None:
    """In hosts where the hook may fire multiple times per turn, the
    ``already_emitted`` flag must short-circuit the banner prepending
    so the second invocation only emits the protocol block."""
    user_message = "Fictional user message — fictional correction request."
    first = build_injected_context_idempotent("both", user_message)
    second = build_injected_context_idempotent(
        "both", user_message, already_emitted=True
    )
    assert first.startswith(PRIMARY_DIRECTIVE_PREFIX)
    # Second invocation (already_emitted=True) must not add the banner.
    assert not second.startswith("PRIMARY DIRECTIVE")
    assert "MNEME BOTH PATH" in second


def test_skill_reference_template_exists() -> None:
    """The reference doc that documents this fix must exist in the public
    repo so future contributors can find it without needing the private
    incident that motivated it."""
    assert SKILL_REF.is_file(), f"missing reference: {SKILL_REF_REL_STR}"
    text = SKILL_REF.read_text(encoding="utf-8")
    assert "PRIMARY DIRECTIVE" in text
    assert "idempotent" in text.lower()
    # Sanity: the reference must not leak private paths/identifiers.
    for forbidden in ("/Users/", "Obs" + "idian"):
        assert forbidden not in text, f"forbidden token leaked: {forbidden!r}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
