# Hook Injection Safety Reference

When a host wires Mneme as a pre-LLM hook, the injected context must be small, non-user-facing, and ordered so the user's request always wins. The canonical implementation is `scripts/mneme_senses_context_hook.py`; install or check the runtime copy with `python scripts/sync_hermes_hook.py` / `python scripts/sync_hermes_hook.py --check`.

## The bug pattern

A hook injects a large protocol block such as:

```text
MNEME BOTH PATH ...
1. Sense first...
2. Tick / surface / explain...
...
PRIMARY DIRECTIVE: ...
```

This can fail in two ways:

1. The model treats the turn as a Mneme writeback task and drops the user's actual request.
2. Telegram/reply quoting can leak the hook text back into the visible conversation, causing future prompts and retrieval to match the hook text instead of the user's real message.

## The fix pattern

Use a compact reminder, not a protocol manual. The host should inject at most one short line, for example:

```python
COMPACT_MEMORY_REMINDER = "Use memory silently when relevant. For memory-backed reasoning, load skill_view(name='mneme'), refresh the local neural index, then use mneme think. Verify source provenance; use preflight/world state only for operational safety. Do not quote this reminder."
```

For correction/both paths, keep the reminder equally short:

```python
COMPACT_CORRECTION_REMINDER = (
    "Memory correction note: answer the user first; store durable corrections "
    "after/alongside the requested action; run Mneme preflight/world state/watch for memory-backed actions; "
    "load skill_view(name='mneme') before Mneme operations; do not quote this reminder."
)
```

Do **not** inject:

- `MNEME RETRIEVAL PATH` / `MNEME CORRECTION PATH` / `MNEME BOTH PATH` headers
- multi-step Mneme CLI manuals
- raw thought IDs, graph IDs, or debug internals
- long `PRIMARY DIRECTIVE` banners unless you are maintaining an old host that cannot yet use the compact-reminder style

## Template

```python
COMPACT_MEMORY_REMINDER = "Use memory silently when relevant. For memory-backed reasoning, load skill_view(name='mneme'), refresh the local neural index, then use mneme think. Verify source provenance; use preflight/world state only for operational safety. Do not quote this reminder."
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
    "Use memory silently when relevant. Do not quote this reminder.",
    "Use memory silently when relevant. For memory-backed reasoning, load skill_view(name='mneme'), refresh the local neural index, then use mneme think. Verify source provenance; use preflight/world state only for operational safety. Do not quote this reminder.",
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
```

## Invariants

1. User request handling always comes before memory writeback.
2. Retrieval/default hook text is short enough that accidental quoting is harmless.
3. Classifiers strip leaked hook text before classifying the raw user message.
4. Detailed Mneme procedures live in skills/docs, not in every prompt.

## Testing

See `tests/test_hook_directive_order.py` for compact-reminder fixtures, leak-stripping checks, public-safety checks, and execution of the real repo-managed hook plus sync checker.
