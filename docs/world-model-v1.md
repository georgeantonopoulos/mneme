# Mneme World Model v1

Mneme's world-model layer is durable state above the rebuildable graph. The graph
continues to hold nodes, edges, observations, sense events, and retrieval cache
data that can be regenerated from local files and senses. World-model rows hold
current assertions, future predictions, and external action records that must
remain meaningful when graph IDs disappear during rebuilds.

## Invariants

- Rebuild durability is the founding rule: default ingest, update, and soft
  forget paths must not delete world-model rows. Only an explicit scoped
  `mneme://` forget may cascade into the world-model tables.
- Assertions reuse existing claim validation. A current assertion should only be
  written from the same confirmed/evidence-backed path that can produce active
  research claims; candidate graph observations do not become durable state.
- Predictions are deterministic. They use structured criteria over stored
  `sense_events` and linked `observations`, never prose interpretation or LLM
  judgment. Unevaluable criteria should be rejected or marked unverifiable.
- Public core remains local-first and LLM-free. World-model transitions are pure
  functions of stored rows and clock time.

## Tables

`world_state_assertions` stores the current durable belief layer. Rows denormalize
subject name, predicate, object value/name, evidence text, and source path so they
survive graph churn. Graph IDs are optional hints only. Supersession should mark
older rows `superseded` or `contradicted`; deletion is reserved for explicit
scoped forgets.

`world_predictions` stores expected future observations. `match_json` carries
machine-checkable fields such as `sense_type`, optional `source_id`, title/text
terms, observation windows, and a score threshold. `predict check` and
`world tick` should evaluate these fields against stored sense events and
observations.

`world_actions` records external side effects once producers exist. It is a
ledger for actions outside the graph, not a duplicate of `edge_debug_log`.
Side-effectful actions need a provider reference or tool call handle before they
can be considered durable.

## Phase Order

1. Add schema and lifecycle guardrails.
2. Add state assertion writers by reusing existing research/claim paths.
3. Add deterministic prediction add/due/check logic.
4. Add `world tick` as composition: run graph tick, check due predictions, and
   return a single JSON report.
5. Feed world-model rows into retrieval/preflight without duplicating graph
   evidence.
6. Wire action recording once a public producer exists.

This order keeps the merge surface small: schema and guardrail tests can land
before assertion and prediction producers, while later lanes can build on stable
table names and lifecycle behavior.
