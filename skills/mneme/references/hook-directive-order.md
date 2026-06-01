# Hook Directive-Order Reference

When a pre-LLM hook injects a Mneme `path` (e.g. `retrieval`, `correction`, `both`)
into the agent's context, the injection must be ordered so the user's request
always wins.

## The bug pattern

Symptom: an LLM-backed agent stops responding to the user mid-turn and instead
runs a Mneme writeback / correction loop. The user sees silence, the model
"completes" successfully, and the original request is lost.

Mechanism: the hook appends a multi-step Mneme protocol block to the system
prompt. At the end of the block it labels the current path
(e.g. "MNEME BOTH PATH — also answer the user's request after writeback").
The trailing "after writeback" causes a strong instruction-following model to
treat the entire user turn as a Mneme task and skip the actual request.

## The fix pattern

The injected context for any non-`silent` path MUST begin with a primary
directive banner that explicitly overrides any "do Mneme writeback first"
language that may appear later in the same block.

### Template (Python)

```python
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

def build_injected_context(path: str, user_message: str) -> str:
    """Return the pre-LLM context block for a given Mneme path.

    `path` is one of: "retrieval", "correction", "both", "silent".
    The directive banner is prepended to retrieval/correction/both blocks
    and is idempotent against turn-2 re-injection.
    """
    if path == "silent":
        return ""
    label = {
        "retrieval": "RETRIEVAL PATH",
        "correction": "CORRECTION PATH",
        "both": "BOTH PATH (correction + retrieval active)",
    }[path]
    protocol = build_protocol_block(label, path)
    # Idempotency: don't double-prepend the directive on re-injection.
    if PRIMARY_DIRECTIVE_HEAD not in user_message:
        return f"{PRIMARY_DIRECTIVE_PREFIX}\n\n{protocol}"
    return protocol

def build_protocol_block(label: str, path: str) -> str:
    """Build the per-path Mneme protocol block (1-step retrieval,
    8-step correction, or both stacked). Implementation varies by host."""
    raise NotImplementedError
```

### Why this works

1. The banner appears before any path header or protocol step, so the model
   sees "answer the user first" as the first instruction in the injected
   block.
2. The banner explicitly names and overrides the conflicting language,
   which closes the loop on instruction-following models that try to
   resolve contradictions by following the longer/more-recent instruction.
3. The idempotency check (`PRIMARY_DIRECTIVE_HEAD not in user_message`)
   prevents the banner from being added twice on turn-2 re-injection, which
   would otherwise inflate token cost without changing behaviour.

## When NOT to apply this

- `path == "silent"` — no banner needed; the hook should output nothing
  and the model should respond only if the user-facing channel expects it.
- Retrieval-only paths where the user's request IS a retrieval query
  (e.g. "what do I have on Project Phoenix?"). In that case the banner is
  redundant but still safe to include.

## Testing the invariant

The invariant under test: "given a BOTH-classified user message, the
first non-empty line of the injected context is the primary directive
banner, not the path header."

See `tests/test_hook_directive_order.py` for a fixture-based test using
a fictional retrieval/correction example.
