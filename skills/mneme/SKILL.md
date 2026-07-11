---
name: mneme
description: Canonical skill for Mneme — single memory system for retrieval, writing, graph connections, thought surfacing, private runtime work, and public repo development. Use for any memory, graph, vault, retrieval, synapse, or Mneme CLI task.
---

# Mneme

## Repo/Local Mirror Rule

The Mneme skill and Hermes hook must never diverge between repo and local runtime. Update repo assets first, then sync local copies and verify drift checks are clean:

```bash
diff -qr skills/mneme "$HERMES_HOME/skills/hermes-agent/mneme"
python scripts/sync_hermes_hook.py --check
```

Do not add private-only references, copied source files, incident logs, or operational scar tissue to the skill or hook directories. Archive custom/private operational detail into the vault instead.

## Path Discovery

Before running any mneme command, resolve config/vault/db/out paths. In sandboxed environments (Codex, CI, containers), `$VAULT`, `$MNEME_DB`, `$MNEME_OUT`, and `$MNEME_CONFIG` may not be set. Always discover paths first:

```bash
mneme doctor
```

This outputs JSON with top-level `config` plus `settings.vault`, `settings.db`, and `settings.out`. Map them to `$MNEME_CONFIG`, `$VAULT`, `$MNEME_DB`, and `$MNEME_OUT` respectively. Example:

```bash
VAULT=$(mneme doctor | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['vault'])")
MNEME_DB=$(mneme doctor | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['db'])")
MNEME_OUT=$(mneme doctor | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['out'])")
MNEME_CONFIG=$(mneme doctor | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['config'])")
```

Use these resolved paths in all subsequent `--vault`, `--db`, and `--out` flags. Do **not** assume env vars are set.

## Vault Write Path

Always use `mneme write` or `mneme note` for vault Markdown files. Never use file tools directly on `$VAULT/`. Exception: scripts and configs outside the vault.

## Vault Path Configuration

- **Vault:** `$VAULT`
- **DB:** `$MNEME_DB`
- **Output:** `$MNEME_OUT`
- **Config:** `$MNEME_CONFIG`

If `mneme write` fails with "path escapes vault root" or writes to the wrong directory:

```bash
mneme init --vault "$VAULT" --force
```

Verify: `mneme write --path memory/test.md --mode create --content "test"` should create `$VAULT/memory/test.md`.

## Retrieval Path (Default)

Sense-first loop for any task requiring memory/context:

```bash
mneme sense run all --json          # or targeted: mneme sense run md --json / mneme sense run gws --json
mneme tick --surface --json
mneme surface --limit 3 --json
mneme explain <thought_id> --json   # before treating a surfaced item as evidence
mneme forget --db "$MNEME_DB" --days-threshold <N>   # FIRST for stale/past-dated observations (non-destructive)
mneme feedback <thought_id> --accept|--deny|--snooze 7d|--kill --reason "..." --json   # after forget or for surfaced thought IDs
```

Never let killed edges drive answers. Candidate/pending facts must be visibly tentative.

## World Model Loop

Use the world model when an agent needs durable current state, explicit future expectations, or a pre-action safety check. The world model is vault-agnostic and lives in the same SQLite DB as the graph:

- `world_state_assertions`: current source-backed assertions that should survive graph rebuilds
- `world_predictions`: deterministic expectations about future sensed evidence
- `world_actions`: records of external side effects when a producer supplies a durable provider/tool handle

Before answering or acting on memory-backed context, run preflight and inspect the returned truth policies:

```bash
mneme agent preflight --db "$MNEME_DB" --prompt "$PROMPT"
```

Operational commands:

```bash
# inspect current durable state
mneme state list --db "$MNEME_DB" --status current
mneme state conflicts --db "$MNEME_DB"
mneme state explain ASSERTION_ID --db "$MNEME_DB"
mneme state backfill --db "$MNEME_DB" --dry-run

# manage deterministic expectations
mneme predict add --db "$MNEME_DB" --file /tmp/prediction.json
NOW=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
mneme predict due --db "$MNEME_DB" --before "$NOW"
mneme predict check --db "$MNEME_DB" --id PREDICTION_ID --dry-run
mneme world watch --db "$MNEME_DB" --lead 1d

# compose graph tick + prediction checks + attention report
mneme world tick --db "$MNEME_DB" --before "$NOW" --dry-run

# canonical entity aliases for world-model subjects
mneme alias add "the landlord" "St James" --db "$MNEME_DB"
mneme alias merge "the landlord" "St James" --db "$MNEME_DB" --dry-run
mneme alias ls --db "$MNEME_DB"

# scored retrieval regression harness
mneme eval retrieval --demo --min-score 0.9
```

Rules:

- Use `mneme resolve` for user-confirmed corrections and source-backed research; validated claims are dual-written into current world assertions.
- Include `predictions[]` in a `mneme resolve` payload when the research creates an expectation that later evidence should confirm, contradict, or fail to appear.
- Omit prediction IDs unless a stable external ID exists; Mneme derives deterministic content-hash IDs to avoid duplicate replay.
- Prefer `world tick --dry-run` during interactive use. Run mutating `world tick` only in explicit maintenance jobs or when the user asks to update prediction state.
- Treat `open_prediction`, `missed_prediction`, `unverifiable_prediction`, and `current_state_assertion` truth policies as operational state, not decorative metadata.
- Treat `lapsed_state_assertion` as retained audit evidence, not current authority. Use `retrieve --as-of` or `agent preflight --as-of` when replaying a historical decision; read-time validity must not silently mutate durable state.
- For expectations bounded by a real event, add `match_json.gate` with a deterministic `sense_type`, identifying source/event/terms, and `time_field` (`observed_at` or `metadata.<path>`). The resolved gate is an effective deadline: post-gate evidence cannot confirm it and an unresolved gate becomes unverifiable at configured expiry.
- Inspect `world.contradictions` and `evidence_conflict` attention before relying on current state. They preserve newly perceived disagreement without auto-overwriting current assertions; candidate challengers remain tentative until source-backed resolution or user confirmation.
- Mark genuinely single-valued assertions with `metadata.conflict_policy: "exclusive"` (or `metadata.cardinality: "one"`). Do not mark multi-valued predicates merely to force conflict alerts.
- If a prediction is linked to a `subject_assertion_id`, a miss weakens that assertion once. Do not manually apply a second confidence penalty.
- Do not use candidate graph edges as current truth when a conflicting current world assertion exists.
- `world_actions` rows for side-effectful actions must include an `external_ref` or `tool_call_id`; otherwise the action is not durable enough to trust.
- Use `mneme action record --db "$MNEME_DB" --file /tmp/action.json` after integrations create tasks, calendar events, drafts, reminders, cron jobs, or other external side effects. Include an optional `verify` block with explicit `sense_type` when the action should spawn a deterministic verification prediction.
- Use `mneme world watch --db "$MNEME_DB"` as a read-only radar for open predictions that are due soon but have no matching evidence yet; `world tick` also includes these as `prediction_watch` attention items.
- Use `mneme alias add/merge/ls` to collapse surface names onto canonical world-model subjects before or after assertions are written; `merge` rewrites stored assertions and recomputes current/superseded pointers.
- Use `mneme eval retrieval --demo --min-score 0.9` as the scored retrieval guardrail when scorer/world-model retrieval changes land.

### Auto-Pruning After Surfacing

After explaining a surfaced item, assess whether it is still an open loop. Apply feedback automatically:

- **Stale/past-dated observations** (nightly cron corrections already applied, past deadlines, resolved items with old dates): use `mneme forget --db "$MNEME_DB" --days-threshold <N>` first. This sets edge strength to 0 for observations older than N days without deleting nodes/observations. Prefer `forget` over `kill` for age-related cleanup — it is non-destructive and reversible.
- **Resolved corrections with no date anchor** (corrections that were applied but lack an observation date): use `mneme feedback <thought_id> --kill --reason "resolved: <why>" --json` only after `forget` has been tried.
- **Standing preferences** (ongoing user preferences, not time-bound): snooze with `mneme feedback <thought_id> --snooze 7d --reason "standing preference: will re-surface if still relevant" --json`
- **Open/active items**: keep surfaced, apply `--accept` or `--deny` based on relevance

**Pruning priority: `forget` → `feedback --kill` → `kill-synapse` (private fallback, last resort).**

Never leave surfaced items un-acked. Every surfaced thought must receive feedback within the same retrieval cycle to prevent stale items from re-surfacing.

## Correction Pipeline (Critical)

When the user makes a direct correction, immediately use `mneme resolve --file <json>` with `certainty=user_confirmed` and `source_type=user_confirmed`. This creates active edges at strength 1.0 that bypass candidate filtering.

**Do NOT rely on vault writeback + sense cycles alone** — they get scored as `kind=fact` with a 0.18x path penalty and need multiple cycles to surface.

JSON payload format for `mneme resolve`:

```json
{
  "title": "Correction Title",
  "slug": "correction-slug",
  "claims": [
    {
      "subject": "Entity Name",
      "predicate": "relation",
      "object": "corrected value",
      "confidence": 1.0,
      "certainty": "user_confirmed",
      "evidence": "User directly corrected: ...",
      "source_type": "user_confirmed"
    }
  ],
  "sources_checked": ["user_direct_correction", "vault_note_path"]
}
```

After resolving:
1. Refresh senses: `mneme sense run all --json`
2. Re-surface: `mneme tick --surface --json`, `mneme surface --limit 3 --json`
3. Record thought-level feedback: `mneme feedback <thought_id> --already-done|--deny|--kill --reason "..." --json`

## Problem: `mneme remember add` Silently Creates 0 Nodes

`mneme remember add` requires the `nodes[]` array in the payload. Observations must reference node refs from the same payload. Passing just `{"kind":"correction","text":"..."}` creates nothing — no nodes, no edges, no observations. This is a silent failure.

**Use `mneme resolve` for corrections instead**, or include a `nodes[]` array with `mneme remember add`.

Mnemonic payload aliases accepted by current code: node objects may use `label` as an alias for `name`, and observations may use `node_ref` or `node_id` as aliases for `node`. Prefer the canonical schema in examples: `nodes[].name` and `observations[].node`.

## Kind=correction Scoring

As of commit 4fc5c59, observations with `kind=correction` get +8.0 authority boost and default score 9.0 in `extract_observations/scoring`. The MEMORY.md path penalty (0.18x) is waived for `source_type=user_confirmed`.

## Private Fallback

When the public CLI does not cover an operation, use the private runtime script:

```bash
python3 mneme_private.py retrieve --prompt "..." --budget 2500 --max-items 8
python3 mneme_private.py note read <vault-relative-path>
python3 mneme_private.py note write <vault-relative-path> --mode create --content "..."
python3 mneme_private.py note upsert-section <vault-relative-path> --heading "..." --content "..."
python3 mneme_private.py kill-synapse <id> --reason "..."
python3 mneme_private.py rebuild
```

Use private fallback ONLY when:
- Public CLI does not cover the operation (note read/write/upsert for private vault)
- Targeted graph surgery on stale synapses that did not surface as thoughts AND have no date in observation text
- Bulk operations not yet in public CLI

Prefer public `mneme forget` for bulk age-based forgetting before private `kill-synapse`.

## DB Flags on Public CLI

All public CLI commands accept `--db` to specify the database:

```bash
mneme sense run all --db "$MNEME_DB" --json
mneme tick --surface --db "$MNEME_DB" --json
mneme surface --limit 3 --db "$MNEME_DB" --json
mneme explain <id> --db "$MNEME_DB" --json
mneme feedback <id> --accept --db "$MNEME_DB" --json
mneme remember add --db "$MNEME_DB" --file /tmp/mneme-memory.json
mneme resolve --file payload.json --db "$MNEME_DB"
mneme forget --db "$MNEME_DB" --days-threshold 30
```

## Vault Notes via `mneme note`

```bash
mneme note read <vault-relative-path> --vault "$VAULT"
mneme note write <vault-relative-path> --vault "$VAULT" --mode append --content "..."
mneme note upsert-section <vault-relative-path> --vault "$VAULT" --heading "Status" --content "..."
```

For private vault operations not covered by public CLI:

```bash
python3 mneme_private.py note upsert-section <path> --heading "..." --content "..."
```

## Forgetting

```bash
mneme forget --db "$MNEME_DB" --days-threshold 30 --dry-run  # preview
mneme forget --db "$MNEME_DB" --days-threshold 30            # apply
```

`mneme forget` sets edge strength to 0 and marks related thought candidates as resolved. It never deletes nodes/observations. The `tick()` function auto-skips observations with dates older than the threshold.

## Brain / Consolidation Commands

```bash
mneme consolidate --db "$DB" --label-provider ollama --label-model qwen2.5:0.5b-instruct
mneme brain label --db "$DB" --max-clusters 25 --max-nodes 50 --max-synapses 50 --max-relationships 25 --label-provider ollama --label-model qwen2.5:0.5b-instruct
mneme brain report --db "$DB"
mneme retrieve --db "$DB" --prompt "..." --max-items 8
```

## Public Repo Development

Source code lives at `./src/mneme/`. Always run tests before committing:

```bash
cd . && python -m pytest tests/ -x -q
```

Push to `georgeantonopoulos/mneme` on GitHub. No personal info in commits.

Pre-commit gate for public repo:

```bash
cd .
python -m pytest tests/ -x -q
python scripts/privacy_scan.py
bash -n scripts/install.sh
python -m mneme.cli run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out
```

## Synapse Discipline

Synapses are typed, auditable claims — not decorative graph lines.

- Default status is `candidate`. Promote to `active` only when evidence is explicit, source-backed, and confidence/strength justify it.
- If a user correction narrows scope, kill over-broad synapses and write a guardrail note.
- Candidate wording must be tentative. Do not surface candidates as facts.

## Research Writeback

When research resolves facts:

```bash
mneme resolve --file payload.json --json
```

Rules:
- confirmed/certain + confidence >= 0.90 + non-empty evidence → active synapse
- pending/unsupported/lower-confidence → candidate
- candidates must not drive thought cards or retrieval as truth

## Pitfalls

- **`mneme remember add` silently creates 0 nodes** if you omit `nodes[]` — use `mneme resolve` for corrections, or include a `nodes[]` array
- **Vault-only corrections get 0.18x path penalty** — use `mneme resolve` with `source_type=user_confirmed` instead
- **`obsidian-cli edit` silently fails** on lines with pipe characters
- **`obsidian-cli daily:write` does NOT exist** — use `daily:create` or `daily:append`
- **`mneme forget` before private graph surgery** — use `mneme forget --db <path> --days-threshold 30` for bulk cleanup of past-dated observations before resorting to `kill-synapse`
- **Don't escalate suppressed MEMORY.md items** — if an item was suppressed/snoozed, do not re-escalate it
- **Never use OpenRouter for cron** — pin to `ollama-cloud/glm-5.2:cloud` or equivalent stable provider
- **Observation age penalty uses wrong timestamp** after rebuild — always derive dates from source path or content text, never from `created_at` alone
- **Stale observation pollution** — `mneme update` re-ingesting historical notes gives observations today's `created_at` but old dates in text. Use `mneme forget` to clean past-dated observations. Archive old daily notes before full vault re-ingestion
- **User-confirmed resolution requires immediate writeback** — do not just acknowledge in chat. Run correction loop, record feedback, and verify
- **Candidate synapses are not facts** — never surface candidates as truth
- **Source priority for factual precision:** Gmail > calendar/tasks > memory > vault > session history > old daily summaries
- **Note content with shell-active characters** — use temp files or Python subprocess, not inline shell strings, to avoid command substitution
- **`note replace` is exact string replacement only** — regex edits are intentionally unsupported. Use `note upsert-section` or `note write --mode overwrite` for section-level changes
- **Pre-LLM hook misclassification** — the hook classifies every prompt as retrieval or correction. Strips injected context before classification. Correction path should not fire on negated terms (e.g. "not resolved")
- **Compact hook injection safety** — when a pre-LLM hook injects Mneme context, do NOT inject large `MNEME RETRIEVAL PATH` / `MNEME BOTH PATH` protocol blocks or long `PRIMARY DIRECTIVE` banners into every prompt. Use the repo-managed `scripts/mneme_senses_context_hook.py`, install/check it with `python scripts/sync_hermes_hook.py --check`, and strip leaked hook markers before classifying user text. See `references/hook-directive-order.md`.
