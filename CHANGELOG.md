# Changelog

## [Unreleased]

### Added — World Model P0 hardening

- `mneme alias add/merge/ls` for canonical world-model subject aliases. `merge` rewrites existing assertions and recomputes current/superseded pointers.
- Action verification loop: side-effectful `mneme action record` payloads with a `verify` block and explicit `sense_type` spawn deterministic verification predictions linked back to `world_actions.prediction_id`.
- `mneme world watch` read-only pre-failure radar for open predictions due soon with no matching evidence; `world tick` includes these as `prediction_watch` attention items.
- `mneme eval retrieval` scored harness with hit@k, MRR, forbidden-rate, and composite score.

### Fixed

- `alias ls` CLI no longer shadows the module-level `sqlite3` import.

## [0.2.0] — 2026-07-04

### Added — World Model Layer

Mneme now has a durable world-model layer on top of the rebuildable graph. The graph remains the perception/index layer; the world model stores state that should survive graph churn.

- **`world_state_assertions`** — current, source-backed beliefs (subject/predicate/object + evidence + confidence). Reuses the same validation contract as active research edges. Promoted by `mneme resolve`, `remember_graph` assertions, and `mneme state backfill`.
- **`world_predictions`** — machine-checkable expectations about future sensed evidence. Checks are deterministic against stored `sense_events` and observations. Added via `mneme predict add` or embedded `predictions[]` in `mneme resolve` payloads. Transition: `open` → `confirmed` / `missed` / `unverifiable`.
- **`world_actions`** — external-side-effect ledger. Requires `external_ref` or `tool_call_id` for side-effectful actions. Recorded via `mneme action record`.

### Added — CLI Commands

- `mneme state list` — inspect current durable state assertions
- `mneme state explain ASSERTION_ID` — explain why an assertion exists
- `mneme state backfill` — promote active research edges to current assertions
- `mneme predict add` — add a deterministic prediction from a JSON file
- `mneme predict due` — list predictions due before a timestamp
- `mneme predict check --id PREDICTION_ID` — check a single prediction (supports `--dry-run`)
- `mneme world tick` — compose graph tick + prediction checks + attention report (supports `--dry-run`)
- `mneme action record` — record an external side effect in the action ledger
- `mneme agent preflight` — now returns world-model context items with `truth_policy` values

### Added — Documentation & Skills

- `docs/world-model-v1.md` — design notes for the world model layer
- `GRAPH_CONTRACT.md` — world model section documenting tables, relationship to graph, and lifecycle
- `skills/mneme/SKILL.md` — World Model Loop section with operational commands and rules
- `skills/mneme-agent-brain/SKILL.md` — world-model state checks, action ledger guidance, verification checklist, side-effect enforcement
- `skills/mneme-agent-brain/references/operator-flow.md` — world model check step (step 5), truth policy interpretation
- `skills/mneme-agent-brain/references/install-update.md` — dry-run verification with world tick
- `scripts/hermes_brain_ready.sh` — runs `mneme world tick --dry-run` in the readiness harness

### Added — Tests

- `test_world_model_schema.py` — schema creation, lifecycle guardrails
- `test_world_model_state.py` — assertion upsert, supersession, reassertion revival
- `test_world_model_predictions.py` — prediction add, due, check, deterministic matching
- `test_world_model_tick.py` — world tick composition, dry-run preservation
- `test_world_model_lifecycle.py` — rebuild durability, forget guardrails
- `test_world_model_actions_cli.py` — action ledger CLI, side-effect enforcement
- `test_world_model_plan_completion.py` — plan coverage validation
- `test_codex_review_fixes.py` — regression tests for review-identified issues

### Changed

- `mneme resolve` now dual-writes validated claims into `world_state_assertions` and accepts `predictions[]` in the payload.
- `remember_graph` creates assertions when claim validation passes; `dry_run=True` skips assertion writes.
- `mneme agent preflight` returns world-model context items and current assertions.
- Version bumped to `0.2.0`.
- Skill `mneme-agent-brain` version bumped to `1.1.0`.

### Fixed

- `world_tick(dry_run=True)` cleans up temp DB files (no `/tmp` leaks).
- `predict check --dry-run` and `check_due_predictions(dry_run=True)` skip DDL on graph-only DBs.
- `write_research_resolution` wraps SQLite work in try/except/finally with rollback.
- `remember_graph(dry_run=True)` skips assertion writes entirely.
- `list_assertions()` supports server-side `order_by` and `limit`; CLI exposes `--order-by` and `--limit` flags.
- `due_predictions()` compares parsed datetimes, not lexicographic strings.
- `delete_world_model_source()` cascades predictions via `source_action_id`.
- Reassertion revival uses `_is_explicit_reassertion()` criteria consistently.

## [0.1.1] — 2026-04-06

- Initial public alpha release.
- Markdown vault ingestion, SQLite graph storage, relationship ontology, edge evidence + audit logs.
- Retrieval-backed context, thought surfacing, SVG/PNG card rendering.
- Privacy-first rebuild defaults and scans.
- CLI commands: `init`, `ingest`, `update`, `run-once`, `retrieve`, `surface`, `thought`, `candidates`, `promote-candidates`, `resolve`, `remember add/remove`, `explain-edge`, `note read/write/replace/upsert-section/add-bullet`, `contract check`, `doctor`.
- Hermes-compatible skill bundle at `skills/mneme-agent-brain/`.
- Hook injection safety reference at `skills/mneme/references/hook-directive-order.md`.