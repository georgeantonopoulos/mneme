# Neural memory

Mneme treats memory as a local nervous system:

```text
perception → neuron activation → synapse propagation → thought → feedback
```

The SQLite graph remains auditable plumbing. Agents work with neurons, synapses, activation, decay, and provenance.

## Build the index

Use a local Ollama embedding model for semantic association:

```bash
ollama pull nomic-embed-text
mneme index --db "$DB" --provider ollama --model nomic-embed-text
```

For deterministic tests, use lexical feature hashing:

```bash
mneme index --db "$DB" --provider hash --model hash-v1
```

Hash mode has no model dependency, but it is not semantic retrieval.

Indexing is incremental. Mneme hashes each neuron's name, type, source, observations, and active-synapse evidence. New or changed neurons are embedded; unchanged vectors are reused; removed neurons leave the index.

For large graphs, start with the newest semantic neurons:

```bash
mneme index --db "$DB" --max-neurons 1000
```

Mneme bounds the candidate set before evidence aggregation, so no-op refreshes stay fast.

## Think

```bash
mneme think --db "$DB" --prompt "What deserves attention?"
```

`think` follows a small path:

1. Activate semantically similar neurons.
2. Rescue strong exact entity and project matches through a capped lexical lane.
3. Prefer current tasks for action-oriented prompts without letting generic deadlines flood the result.
4. Spread activation through positive **active** synapses only.
5. Hydrate the winners with compact source evidence.

Calendar memories decay from their event time, not ingestion time. Long-running projects keep a higher floor. Sensed sources use the latest deterministic revision.

## Boundaries

- Headings, dates, wikilinks, and extracted observation nodes do not seed the latent index; graph propagation can still reach them.
- Archives, merged duplicates, operator context, `AGENTS.md`, `HEARTBEAT.md`, `SOUL.md`, `USER.md`, and `*_OPS.md` cannot seed or re-enter retrieval.
- Candidate and killed synapses never propagate.
- Evidence excerpts and counts are bounded.
- Activation is an associative lead, not a factual claim.

One embedding is a lossy fingerprint. It tells Mneme where to look. Provenance tells the agent what it may trust.

## Rollout check

A working deployment proves the complete loop:

1. Build the real embedding index.
2. Run the same index command again; a healthy no-op reports `indexed: 0`.
3. Run a representative `mneme think` query and inspect sources and activation reasons.
4. Ingest one change and confirm only changed neurons are embedded.
5. Compare current/actionable quality as well as topical relevance.

Index freshness is not source freshness. New evidence must be sensed before it can change a neuron.
