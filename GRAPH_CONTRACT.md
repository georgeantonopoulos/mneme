# Mneme Graph Contract

This contract maps the public Mneme graph model to the private dogfood synapse
runtime without including private vault data. It is the compatibility target for
ingest, writeback, validation, retrieval, and thought generation.

## Object Mapping

| Concept | Public Mneme | Private Runtime | Contract |
|---|---|---|---|
| Source note | `nodes` row with `type='note'` or folder-derived type | `nodes` row plus `sources` provenance | A note/node is a source container, not a factual claim by itself. |
| Evidence item | `observations` row | `observations` row | Evidence text is bounded and source-path backed. |
| Relationship | `edges` row | `synapses` row | A relationship is traversable only when its status and type rules allow it. |
| Relationship type | `relationship_types.id` | `relationship_types.id` | Type metadata defines category, inverse, validation need, symmetry, and transitivity. |
| Audit trail | `edge_debug_log` | `synapse_debug_log` | Creation, validation, rejection, and kill events must keep rationale and actor. |
| Thought path | `thoughts` over active edges | `thoughts` over active synapses | Thought generation must avoid killed edges and should demote graph plumbing. |

## Status Mapping

| Status | Public Meaning | Private Meaning | Traversable For Thoughts |
|---|---|---|---|
| `active` | Accepted for graph walks. | Accepted synapse. | Yes. |
| `candidate` | Stored for review or weak evidence. | Stored, unvalidated synapse. | No, except diagnostic candidate review. |
| `rejected` | Evidence was considered and declined. | Decayed or declined candidate. | No. |
| `killed` | User/agent correction tombstone. | Permanent tombstone that blocks re-creation. | Never. |

## Relationship Categories

| Category | Examples | Promotion Rule |
|---|---|---|
| `reference` | `links_to`, `linked_from` | May be active as navigation, but must not be treated as semantic truth. |
| `structure` | `has_heading` | Active as document structure only. |
| `extraction` | `mentions_date`, `mentions_email` | Active as extraction/provenance only. |
| `observation` | `has_fact`, `has_risk`, `has_blocked`, `has_done` | Active as source-contained observations, not entity-to-entity facts. |
| `candidate` | `co_mentioned_candidate` | Must remain candidate until validated by evidence or user confirmation. |
| `semantic_pending` | `requested_activity` | Represents unresolved/pending state; do not promote to resolved semantic fact. |
| `semantic` | `belongs_to`, `part_of`, `located_in`, `attends_activity`, family relations | Requires explicit evidence or confirmed research writeback before active use. |

## Promotion Rules

1. Deterministic ingest may create source-contained observation edges as `active` because they represent provenance from a note to its own evidence.
2. Deterministic ingest should keep navigation, structure, extraction, semantic, and co-mention relationships as `candidate` unless the source is explicit user confirmation or validated research writeback.
3. Research writeback may promote a semantic claim to `active` only when it has evidence text, confirmed/certain wording, and confidence at or above the configured threshold.
4. `killed` edges/synapses are tombstones. Rebuilds and re-ingests must preserve them or restore them from a verified backup before activation can proceed.
5. Durable validated `active` edges/synapses (for example research/writeback or user-confirmed claims) must survive rebuilds; deterministic vault/ingest edges may be recalculated to avoid stale private content.
6. Retrieval and thought generation may show candidates as candidates, but must not phrase them as resolved facts.
7. Corrective guardrails are stronger than stale observations. If a later source says an old task/claim was stale, wrong, hallucinated, or must not be mentioned without fresh evidence, proactive thought/candidate selection must not resurrect the old item as an open loop.
8. Dismissal feedback should weaken, not automatically delete, a surfaced relationship. If a user declines a proposed thought/action, reduce the relevant edge/synapse strength and record the feedback event; kill/tombstone only when the feedback or evidence says the relationship is false.
9. Open-task discovery must distinguish “source-contained observation exists” from “task is currently live”. Old daily-note rows, imported tracker rows, and candidate edges require fresh confirming evidence before an agent says they are still open, overdue, requested, or stalled.
10. Suppression controls recall, not perception. Newly ingested evidence that disagrees with explicitly single-valued current world state must remain visible as an auditable contradiction review item. It must not auto-promote or silently disappear. Cardinality must be declared (`conflict_policy: exclusive` or `cardinality: one`), not guessed from predicate wording.

## World Model Layer

The world model is a durable layer above the rebuildable graph. It does not replace the graph; it stores state that should survive graph churn.

### Tables

| Table | Purpose | Producer |
|---|---|---|
| `world_state_assertions` | Current, source-backed beliefs (subject/predicate/object + evidence + confidence). Reuses the same claim validation as active research edges. | `mneme resolve` / `remember_graph` assertions; `mneme state backfill` promotion. |
| `world_predictions` | Machine-checkable expectations about future sensed evidence. Checks are deterministic against `sense_events` and observations — no LLM judgement. Optional event gates make the earliest matching sensed event an effective deadline. | `mneme predict add`; `predictions[]` in `mneme resolve` payloads. |
| `world_actions` | External-side-effect ledger. Requires `external_ref` or `tool_call_id` for side-effectful actions. | `mneme action record`; integration producers. |

### Relationship To The Graph

- The graph remains the perception/index layer: it can be rebuilt from Markdown and senses.
- World-model rows reference graph evidence by `source_path` and optional `source_edge_id`, but graph IDs are hints only. World-model rows survive graph rebuilds.
- Assertions reuse the same validation contract as active research edges: a current assertion should only come from confirmed/evidence-backed claims at or above the active threshold.
- Retrieval/preflight can include world-model rows with explicit `truth_policy` values: `current_state_assertion`, `open_prediction`, `missed_prediction`, `unverifiable_prediction`.
- Current world-model assertions outrank candidate graph edges when they conflict.
- Canonical entity aliases (`entity_aliases`) collapse surface names onto one world-state subject before assertion IDs are computed; `merge_subject` can retroactively rewrite stored assertions and recompute current/superseded pointers.

### Lifecycle

- Default `ingest`, `update`, and soft `forget` paths must not delete world-model rows.
- Only an explicit scoped `mneme://` forget cascades into world-model tables.
- Predictions transition deterministically: `open` → `confirmed` / `missed` / `unverifiable` based on stored evidence and clock time.
- A missed prediction linked to `subject_assertion_id` weakens that assertion's confidence once.
- `world tick` and agent preflight report read-only state/evidence contradictions. Candidate challengers stay tentative; historical superseded/contradicted/killed assertion edges do not re-alert.

## Compatibility Invariants

These invariants are the minimum bar for keeping public Mneme aligned with private dogfood runtimes while preserving privacy:

1. **Evidence before belief:** every durable relationship must have bounded evidence and source provenance. A node name or co-mention is not enough.
2. **Candidates stay tentative:** candidate edges may be stored, inspected, and explained, but user-facing retrieval must label them as tentative and thought generation must not treat them as facts.
3. **Tombstones survive:** killed edges are guardrails. Rebuilds, re-ingests, migrations, and candidate promotion must not recreate a killed relationship unless a later explicit correction supersedes the tombstone.
4. **Dismissal weakens by default:** “not useful” feedback reduces priority; it does not imply the underlying relationship is false. Kill only when feedback or source evidence says the claim is wrong.
5. **Freshness is source-derived:** age/decay logic should derive dates from source paths or source text when possible. Rebuild timestamps are operational metadata, not evidence freshness.
6. **Open loops need current evidence:** old TODOs, cron summaries, daily notes, and generated drafts are historical evidence. Treat them as live obligations only after a fresh source or explicit lifecycle event confirms them.
7. **Temporal authority is evaluated at read time:** once `valid_until` has elapsed, retrieval/preflight must label the row `lapsed_state_assertion` and remove current-state authority without silently mutating or deleting audit history.
8. **Event gates are evidence, not guesses:** a prediction gate must resolve deterministically from stored `sense_events`; evidence observed after the resolved gate cannot satisfy the prediction, and an unresolved gate becomes `unverifiable` at configured expiry.
9. **Lifecycle is explicit:** close or update thought/task state through feedback, writeback, reminder, dismissal, or source-specific evidence. Do not infer closure solely from prose words in unrelated text.
10. **Generated artifacts are private by default:** SQLite databases, cards, logs, and session-derived outputs can contain source snippets and must stay out of public commits.
11. **Private incidents become fictional fixtures:** public tests should encode generic failure modes with invented names, paths, and source packets, never copied private evidence.
