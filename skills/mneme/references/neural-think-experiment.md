# Neural Think Experiment

## Trigger

Use this reference when Mneme work starts expanding public tables, policies, lifecycle fields, or narrow commands instead of improving associative thought; or when evaluating local latent indexing for an LLM-facing memory graph.

## Proven vertical slice

The smallest useful architecture is:

1. Build an incremental local embedding index over semantic neurons (`note`, `entity`, `email`, `project`, `person`, etc.). Exclude extraction scaffolding such as headings, dates, wikilinks, and observation nodes from latent seeding; keep them reachable through graph propagation.
2. Embed the prompt locally (the experiment used Ollama `nomic-embed-text`, 768 dimensions). Keep a deterministic signed feature-hash provider for tests/offline fallback, but label it accurately as lexical rather than semantic.
3. Seed the highest-cosine neurons.
4. Spread activation for a small number of hops through active synapses only, weighted by strength and confidence. Candidate and killed synapses must never propagate — reduced-weight candidate propagation was tried and reverted because it risks turning tentative associations into factual thought paths.
5. Apply source-derived temporal decay to dated memories. Never use rebuild/index time as evidence freshness. Preserve a higher floor for undated long-running projects, but treat that as a heuristic requiring evaluation.
6. Return a compact LLM packet: activated neuron, activation value, source path, latent-vs-synaptic reason, traversed relation/evidence, and the warning that activation is an associative lead rather than a fact.

Agent-facing commands should stay conceptually small (`index`, `think`, then eventually `explain`, `reinforce`, `suppress`, `sleep/consolidate`). Existing relational tables may remain hidden plumbing during migration.

## Evaluation pattern

Compare latent thought against existing lexical retrieval on prompts with intentionally different vocabulary from the target source. A successful probe used the concept “focused effort create commercial growth”: lexical retrieval returned unrelated logs and predictions, while latent activation found the Sequency marketing project and action pack despite no shared product vocabulary.

Also test ordinary current-work prompts against a SQLite-consistent local-vault snapshot. Score separately:

- semantic/topical association;
- current/actionable precision;
- useful synaptic propagation;
- provenance completeness;
- killed-synapse suppression;
- index build/update cost.

A real embedding win does not solve lifecycle leakage. Old projects and completed tasks may still activate; handle this with decay, inhibition, completion evidence, and feedback-driven plasticity rather than exposing another administrative subsystem.

## Implementation pitfalls

- Batch embedding requests can exceed model context limits because a neuron's aggregated evidence is large. Bound the neuron text before embedding and surface HTTP response details on failure.
- Full-graph indexing can be unnecessarily expensive. Index semantic seed neurons and let activation reach lower-level extraction nodes through synapses. Support incremental content hashes and a bounded recent-neuron experiment mode.
- `SenseEvent.text` and graph observations are not interchangeable; index what ingestion actually persisted.
- An embedding model is optional infrastructure, not a core network dependency. Core operation and tests must remain local and deterministic.
- Do not mistake cosine similarity for truth. Killed edges must never fire, candidate edges must never propagate (reduced-weight candidate propagation was tried and reverted), and source provenance must survive every hop.
- Do not publish or push an experimental public branch without explicit approval; a local branch and commit are enough for evaluation.

## Session evidence

The experiment branch `experiment/neural-think` used a local 500-neuron Ollama index and passed the full test suite. The durable lesson is the architecture and evaluation method above, not that branch name, commit, model installation state, or snapshot path.
