#!/usr/bin/env python3
"""
Pre-LLM Mneme hook: every prompt takes one of two Mneme paths.

1. Correction path: user message contains resolution/correction markers.
   -> cross-reference fresh senses, update evidence/notes, run activation,
      surface/explain the corrected state, then use private fallback only for
      note writeback, retrieve, rebuild, or synapse tombstones not covered by
      the public CLI.

2. Retrieval path (default): use public Mneme senses and cognition commands
   first, with private retrieve only when public CLI coverage is insufficient.

No prompt misses Mneme. No random vault reads bypass Mneme.

Contract: senses -> evidence -> synapses -> activation -> surface -> feedback.
"""
from __future__ import annotations

import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
MNEME_DIR = HERMES_HOME / "scripts" / "mneme"
MNEME_PRIVATE = MNEME_DIR / "mneme_private.py"
sys.path.insert(0, str(MNEME_DIR))

def _load_env_file(path: Path) -> None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))
    except Exception:
        pass

_load_env_file(HERMES_HOME / ".env")
try:
    from path_classifier import classify_path, strip_injected_context
except Exception:  # pragma: no cover - hook must remain available even if helper import fails
    classify_path = None
    strip_injected_context = None

# Correction markers: phrases that indicate the user is resolving/correcting a prior fact.
# Negative lookbehind prevents matching negation patterns like "not resolved", "not done".
CORRECTION_MARKERS = [
    r"(?<!\bnot\s)(?<!\bnever\s)(?<!\bwill\s)(?<!\bstill\s)(?<!\bpartially\s)(?<!\bhalf-)\b(?:resolved|done|fixed|sorted|closed|paid|sent|booked|confirmed)\b",
    r"\b(?:not urgent|no longer|ignore|don't worry|all good|fine now)\b",
    r"\b(?:moot|irrelevant|secondary|forget)\b",
    r"\b(?:correct(?:\s+that|ion)?):",
    r"\b(?:that'?s wrong|that'?s stale|hallucinat)\b",
    # Conversational contradiction. Example: "What are you talking about, I'm the tenant".
    r"\bwhat\s+are\s+you\s+talking\s+about\b",
    r"\b(?:actually|no[,.])\b",
    # Identity/role corrections after the assistant inferred the wrong party/role.
    r"\b(?:i'?m|i\s+am)\s+(?:the\s+)?(?:tenant|landlord|owner|agent|buyer|seller|client|customer|parent|guardian)\b",
    r"\b(?:mark\s+(?:as\s+)?|this\s+is\s+now)\s+(?:resolved|done|closed|paid|moot)",
    r"\b(?:update\s+(?:status|label|tag|memory)|change\s+(?:status|label|tag))\b",
    # Meta-correction: the user says memory routing/classification should have used correction.
    r"\bshould\s+have\s+triggered\s+(?:mneme\s+|memory\s+)?correction\b",
    r"\b(?:mneme\s+|memory\s+)?correction\s+(?:did\s+not|didn't|should\s+have|failed\s+to)\b",
    r"\bNOT URGENT\b",
    r"\b\b\[SILENT\]\b\b",
]

COMPACT_MEMORY_REMINDER = "Use memory silently when relevant. For memory-backed reasoning, load skill_view(name='mneme'), refresh the local neural index, then use mneme think. Verify source provenance; use preflight/world state only for operational safety. Do not quote this reminder."
COMPACT_CORRECTION_REMINDER = "Memory correction note: answer the user first; store durable corrections after/alongside the requested action; run Mneme preflight/world state/watch for memory-backed actions; load skill_view(name='mneme') before Mneme operations; do not quote this reminder."
NON_CORRECTION_COMPLETION = re.compile(
    r"\b(?:not|never|still\s+not|not\s+yet|will|will\s+be|going\s+to\s+be)\s+"
    r"(?:resolved|done|fixed|sorted|closed|paid|sent|booked|confirmed)\b",
    re.IGNORECASE,
)

# Source freshness priority (from README/GRAPH_CONTRACT)
SOURCE_PRIORITY = [
    "user_correction",  # explicit user correction - highest
    "gmail_email",       # newest email/attachments
    "calendar_task",     # calendar/tasks for time commitments
    "hermes_memory",     # Hermes memory/user profile
    "vault_note",        # vault/project/person notes
    "session_history",   # session history
    "cron_summary",      # old cron/daily summaries — lowest
]


def _strip_injected_context(user_message: str) -> str:
    """Strip prompt-time context and leaked hook instructions from the message."""
    if strip_injected_context is not None:
        user_message = strip_injected_context(user_message)
    if not user_message:
        return ""
    # Fallback: strip everything before the actual user message if it starts with
    # the injected context marker
    marker = "[Prompt-time retrieved context"
    idx = user_message.find(marker)
    if idx == 0:
        after_marker = user_message[len(marker):]
        end_markers = ["\n[User message]\n", "\n\n[User message]\n"]
        for em in end_markers:
            pos = after_marker.find(em)
            if pos != -1:
                user_message = after_marker[pos + len(em):].strip()
                break
    cut = len(user_message)
    # Strip leaked hook blocks wherever they appear, not only when preceded by
    # blank lines. Telegram reply quoting can paste them directly into the next
    # user message, and then the hook re-ingests its own instructions.
    for leak_marker in (
        "MNEME RETRIEVAL PATH",
        "MNEME CORRECTION PATH",
        "MNEME BOTH PATH",
        "PRIMARY DIRECTIVE:",
        "Internal Mneme reminder:",
        "Internal Mneme CORRECTION PATH",
        "Internal Mneme BOTH PATH",
        "Use memory silently when relevant.",
        "━━━━━━━━━━━━━━━━",
        "Path tag (internal):",
    ):
        pos = user_message.find(leak_marker)
        if pos != -1:
            cut = min(cut, pos)
    return user_message[:cut].strip()


def _classify_path(user_message: str) -> dict:
    """Classify user message as retrieval, correction, or both."""
    cleaned = _strip_injected_context(user_message)
    # Deterministic safety rules outrank optional model classification. A future
    # or explicitly negated completion is not a correction/writeback signal.
    if NON_CORRECTION_COMPLETION.search(cleaned):
        return {"path": "retrieval", "source": "regex-negation-guard"}
    if classify_path is not None:
        return classify_path(
            cleaned,
            model=os.getenv("MNEME_PATH_CLASSIFIER_MODEL", "gemma4:31b"),
            timeout=float(os.getenv("MNEME_PATH_CLASSIFIER_TIMEOUT", "2.0")),
            enabled=os.getenv("MNEME_PATH_CLASSIFIER_ENABLED", "1").lower() not in {"0", "false", "no"},
        )
    return {"path": "correction" if _regex_is_correction(cleaned) else "retrieval", "source": "regex-local"}


def _regex_is_correction(user_message: str) -> bool:
    if not user_message:
        return False
    msg_lower = user_message.lower().strip()
    for pattern in CORRECTION_MARKERS:
        if re.search(pattern, msg_lower):
            return True
    return False


def _is_correction(user_message: str) -> bool:
    """Detect if user message requires the correction path."""
    return _classify_path(user_message).get("path") in {"correction", "both"}


def _extract_entities(text: str) -> list[str]:
    """Extract capitalized named entities from text for cross-referencing."""
    if not text:
        return []
    # Match capitalized multi-word phrases
    entities = re.findall(r'\b([A-Z][A-Za-z0-9\'.-]+(?:\s+[A-Z][A-Za-z0-9\'.-]+){0,3})\b', text)
    # Filter out common non-entities
    stop = {'I', 'You', 'He', 'She', 'We', 'They', 'It', 'This', 'That', 'These',
            'Those', 'Here', 'There', 'Today', 'Tomorrow', 'Yesterday', 'Now',
            'The', 'A', 'An', 'And', 'Or', 'But', 'So', 'If', 'In', 'On', 'At',
            'To', 'For', 'With', 'From', 'By', 'About', 'No', 'Yes', 'Not', 'OK',
            'Please', 'Just', 'Also', 'Then', 'Only', 'Any', 'All', 'Some', 'More'}
    return [e for e in entities if e not in stop and len(e) > 2]


def _format_context(user_message: str) -> dict:
    """Build the context block to inject into the system prompt."""
    classification = _classify_path(user_message)
    path = classification.get("path", "retrieval")

    if path in {"correction", "both"}:
        return {
            "path": path,
            "classification": classification,
            "context": COMPACT_CORRECTION_REMINDER,
        }

    # Default: retrieval path. Keep this compact: long hook manuals have leaked
    # into Telegram reply quotes before, polluting user-visible chat and future
    # retrieval. Detailed Mneme policy lives in skills/memory, not every prompt.
    return {
        "path": path,
        "classification": classification,
        "context": COMPACT_MEMORY_REMINDER,
    }


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps(_format_context("")))
        raise SystemExit(0)

    if payload.get("hook_event_name") != "pre_llm_call":
        print(json.dumps(_format_context("")))
        raise SystemExit(0)

    extra = payload.get("extra") or {}
    user_message = str(extra.get("user_message") or "")
    platform = str(extra.get("platform") or "")

    # Every prompt gets Mneme context — no exception
    context = _format_context(user_message)

    # Log activation for debugging
    try:
        log_path = HERMES_HOME / "logs" / "mneme_hook_activation.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "platform": platform,
            "len": len(user_message),
            "preview": user_message[:120],
            "path": context.get("path", "retrieval"),
            "classification_source": (context.get("classification") or {}).get("source"),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    print(json.dumps(context))


if __name__ == "__main__":
    main()
