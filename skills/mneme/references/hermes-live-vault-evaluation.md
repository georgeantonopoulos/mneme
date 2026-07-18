# Hermes + Live Vault Evaluation

Use this protocol after retrieval, world-model, temporal-validity, ingestion, consolidation, or thought-surfacing changes.

## Safety boundary

1. Resolve paths with `mneme doctor`.
2. Refresh the live database only when the user asked for a live-vault test, using `mneme sense run <sense>`.
3. Create a SQLite-consistent snapshot with SQLite's backup mechanism.
4. Run consolidation, labeling, repeated probes, synthetic fixtures, and mutating experiments on the snapshot.
5. State exactly what touched the live database.

## Integration checks

- Mneme/Hermes contract passes.
- Hook and skill mirrors are in sync.
- Snapshot passes `PRAGMA integrity_check`.
- Preflight, retrieval, surface, and dry-run world tick emit valid structured output.
- Dry-run paths do not alter prediction or assertion lifecycle state.

These checks establish execution reliability only.

## Prompt battery

Probe at least five classes that reflect the vault:

1. Broad current obligations, deadlines, and unresolved risks.
2. Upcoming travel or scheduled events.
3. School, forms, payments, or administrative deadlines.
4. Property, household, invoices, or accounts.
5. Current project/business work and next actions.

Inspect at least the top five retrieval results and top three surfaced thoughts for each prompt.

## Score dimensions separately

### Topical relevance

Does the result concern the requested domain? A past flight can be topically relevant to travel.

### Current/actionable relevance

Would a competent operator act on this now? Completed delivery, refund, departed flight, paid bill, and expired registration windows should usually fail this dimension even when historically accurate.

Do not collapse these dimensions into one score. Report both, along with examples of lifecycle leakage.

## Temporal and world-model coverage

Measure:

- Current and superseded assertion counts.
- Current assertions with `valid_until`.
- Assertions expired at evaluation time.
- Open, confirmed, missed, and unverifiable prediction counts.
- Event-gated prediction count and whether any real gates resolve.
- Contradiction count.

A feature can pass unit/integration tests yet have no live effect. Zero `valid_until` coverage means lapse logic is dormant. Zero gated predictions means event-gate effectiveness is not yet dogfooded.

Inspect whether preflight's world assertions are prompt-ranked. A generic recent-current list can contaminate otherwise good retrieval.

## Graph and thought health

Report:

- Nodes, observations, and edges.
- Candidate/active/killed edge percentages.
- Orphan-node percentage.
- Unknown predicate/relation warning volume.
- Brain-label requested, successful, and fallback counts.
- Thought-title specificity and repeated generic titles.

Treat all-fallback labels as failed semantic labeling, regardless of provider metadata.

## Interpretation

A useful report distinguishes:

1. Engineering reliability.
2. Topical retrieval quality.
3. Current/actionable precision.
4. Thought-surfacing quality.
5. Live coverage of newly added features.

The highest-value fix is often temporal enrichment and lifecycle closure at write time—not another scorer adjustment. Derive `valid_until`, supersede completed/open states, emit structured event gates from real senses, and prompt-rank world assertions before injection.
