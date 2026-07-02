# Mneme Operator Flow

This reference is the Hermes-facing runbook for Mneme as an agent brain.

## 1. Prepare Paths

Use explicit paths in automation:

```bash
export VAULT=/path/to/vault
export DB=/tmp/mneme.sqlite
export PROMPT="what should the agent remember here?"
```

Do not commit private vault paths or generated SQLite files.

## 2. Refresh The Graph

For day-to-day syncs, prefer `update` because it removes stale graph rows while preserving thought history:

```bash
mneme update --vault "$VAULT" --db "$DB"
```

Use `ingest --append` only for deliberate append-only experiments.

## 3. Build The Working Brain

Run structure-first consolidation, then model-backed labelling:

```bash
mneme consolidate --db "$DB" --label-provider "$MNEME_LABEL_PROVIDER" --label-model "$MNEME_LABEL_MODEL"
mneme brain label --db "$DB" --targets cluster,node,synapse,relationship --label-provider "$MNEME_LABEL_PROVIDER" --label-model "$MNEME_LABEL_MODEL"
mneme brain report --db "$DB"
```

If Hermes supplies its own labeller, set:

```bash
export MNEME_LABEL_PROVIDER=hermes
export MNEME_LABEL_COMMAND="hermes label --json"
```

The label command receives a prompt on stdin and should return JSON with:

```json
{
  "labels": ["short label"],
  "summary": "brief explanation",
  "intent": "retrieval routing",
  "ignore": false
}
```

## 4. Agent Preflight

Before using Mneme memory in an answer or action, run the contract preflight:

```bash
mneme agent preflight --db "$DB" --prompt "$PROMPT"
```

Use only the returned context and surfaced thoughts. If `contract.status` is not `pass`, do not use Mneme memory as factual grounding.

## 5. World Model Check

Before acting on memory-backed context, inspect durable state and due predictions. Keep interactive checks dry-run unless the task explicitly requires updating prediction status:

```bash
mneme state list --db "$DB" --status current
NOW=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
mneme predict due --db "$DB" --before "$NOW"
mneme world tick --db "$DB" --before "$NOW" --dry-run
```

Interpretation rules:

- `current_state_assertion` is durable state and can outrank candidate graph edges.
- `open_prediction` is an expected future observation; do not treat it as confirmed fact.
- `missed_prediction` means the expected evidence did not arrive in time; inspect linked assertions before relying on them.
- `unverifiable_prediction` means the DB lacks the sensed evidence needed to check the expectation.
- Side-effectful `world_actions` need a provider reference or tool-call handle before they should be trusted as a durable action record.

When research or a user-confirmed correction creates a future expectation, write it as a prediction. Prefer embedding `predictions[]` in the same `mneme resolve` payload as the claims. For standalone expectations, use `mneme predict add --file prediction.json`.

When an integration performs a real side effect, record it in the action ledger:

```bash
mneme action record --db "$DB" --file action.json
```

The payload must include `external_ref` or `tool_call_id` for side-effectful actions.

## 6. Retrieve Context

Use retrieval for prompt-time context:

```bash
mneme retrieve --db "$DB" --prompt "$PROMPT" --max-items 8
```

Read `truth_policy` before treating a synapse as factual:

- `source_contained_observation`: a source note directly contains the observation.
- `active_validated_claim`: an active relationship can guide reasoning.
- `candidate_only`: a possible relationship; review before trusting.
- `killed`: excluded from retrieval.
- `current_state_assertion`: durable world-model state.
- `open_prediction`, `missed_prediction`, `unverifiable_prediction`: expectation state, not factual confirmation.

## 7. Surface Thoughts

Use surface for proactive thought candidates from the same retrieval path:

```bash
mneme surface --db "$DB" --prompt "$PROMPT" --limit "${MNEME_SURFACE_LIMIT:-5}"
```

Prefer surfaced thoughts when deciding what to inspect next. Use rendered `mneme thought` cards only when a visual card is the desired output.

## 8. Add Temporary Graph Memory

Use `mneme://` memory for tests and agent working state:

```bash
cat >/tmp/mneme-memory.json <<'JSON'
{
  "source_path": "mneme://test/hermes-validation",
  "nodes": [
    {"ref": "task", "type": "task", "name": "Hermes validation"}
  ],
  "observations": [
    {"node": "task", "kind": "fact", "text": "Hermes validation should surface.", "score": 5}
  ]
}
JSON

mneme remember add --db "$DB" --file /tmp/mneme-memory.json
mneme surface --db "$DB" --prompt "Hermes validation"
mneme remember remove --db "$DB" --source-path mneme://test/hermes-validation
```

The remove command refuses non-`mneme://` sources by design.

## 9. Full Readiness Check

Run the repo script when available:

```bash
MNEME_BRAIN_DEPTH=smoke scripts/hermes_brain_ready.sh "$DB" "$PROMPT"
```

Depth presets:

- `smoke`: tiny proof set for quick CI or install checks.
- `default`: normal working brain.
- `deep`: all discovered clusters plus broader active frontier.
- `full`: every eligible target, for small DBs or long runs.

The script is successful only if contract check, preflight, retrieval, surfaced thought output, and `mneme world tick --dry-run` all work. The world tick check proves prediction checking and world-model attention reporting without mutating state.

## 10. Privacy Gate

Before committing:

```bash
python3 scripts/privacy_scan.py
git diff --check
```

Also search changed files for private path strings, private vault names, generated DBs, and thought images.
