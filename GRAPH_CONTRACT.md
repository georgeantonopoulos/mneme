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
