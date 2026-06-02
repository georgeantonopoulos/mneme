---
name: mneme
description: Canonical skill for Mneme — single memory system for retrieval, writing, graph connections, thought surfacing, private runtime work, and public repo development. Use for any memory, graph, vault, retrieval, synapse, or Mneme CLI task.
---

# Mneme

## Path Discovery

Before running any mneme command, resolve vault/db/out paths. In sandboxed environments (Codex, CI, containers), `$VAULT`, `$MNEME_DB`, and `$MNEME_CONFIG` may not be set. Always discover paths first:

```bash
mneme doctor --json
```

This returns JSON with `settings.vault`, `settings.db`, and `settings.out`. Extract and use those values as `$VAULT`, `$MNEME_DB`, and `$MNEME_CONFIG` respectively. Example:

```bash
VAULT=$(mneme doctor --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['vault'])")
MNEME_DB=$(mneme doctor --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['db'])")
```

Use these resolved paths in all subsequent `--vault`, `--db`, and `--out` flags. Do **not** assume env vars are set.

## Vault Write Path

Always use `mneme write` or `mneme note` for vault Markdown files. Never use file tools directly on `$VAULT/`. Exception: scripts and configs outside the vault.

## Vault Path Configuration

- **Vault:** `$VAULT`
- **DB:** `$MNEME_DB`
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
- **Never use OpenRouter for cron** — pin to `ollama-cloud/glm-5.1:cloud` or equivalent stable provider
- **Observation age penalty uses wrong timestamp** after rebuild — always derive dates from source path or content text, never from `created_at` alone
- **Stale observation pollution** — `mneme update` re-ingesting historical notes gives observations today's `created_at` but old dates in text. Use `mneme forget` to clean past-dated observations. Archive old daily notes before full vault re-ingestion
- **User-confirmed resolution requires immediate writeback** — do not just acknowledge in chat. Run correction loop, record feedback, and verify
- **Candidate synapses are not facts** — never surface candidates as truth
- **Source priority for factual precision:** Gmail > calendar/tasks > memory > vault > session history > old daily summaries
- **Note content with shell-active characters** — use temp files or Python subprocess, not inline shell strings, to avoid command substitution
- **`note replace` is exact string replacement only** — regex edits are intentionally unsupported. Use `note upsert-section` or `note write --mode overwrite` for section-level changes
- **Pre-LLM hook misclassification** — the hook classifies every prompt as retrieval or correction. Strips injected context before classification. Correction path should not fire on negated terms (e.g. "not resolved")
- **Compact hook injection safety** — when a pre-LLM hook injects Mneme context, do NOT inject large `MNEME RETRIEVAL PATH` / `MNEME BOTH PATH` protocol blocks or long `PRIMARY DIRECTIVE` banners into every prompt. Use compact reminders such as `Use memory silently when relevant. Do not quote this reminder.` and strip leaked hook markers before classifying user text. See `references/hook-directive-order.md`.
