# Neural Think Experiment

This branch tests a simpler Mneme:

```text
perception → latent neuron activation → synapse propagation → thought context → feedback
```

The database remains auditable plumbing. The agent-facing model is neurons,
synapses, activation, decay, and provenance—not tables and lifecycle bureaucracy.

## Build the latent index

For real semantic embeddings, use a local Ollama embedding model:

```bash
ollama pull nomic-embed-text
mneme index --db "$DB" --provider ollama --model nomic-embed-text
```

For tests or machines without an embedding model, the deterministic `hash`
provider has no dependencies or network calls. It is lexical feature hashing,
not a semantic substitute:

```bash
mneme index --db "$DB" --provider hash --model hash-v1
```

Indexing is incremental. Only new or changed neuron representations are embedded
again; vectors for deleted neurons or neurons that leave a bounded index window
are removed.
Headings, extracted observation nodes, wikilinks, and dates are excluded from the
latent seed index; they remain available through graph propagation. Large graphs
can start with the most recently updated semantic neurons:

```bash
mneme index --db "$DB" --max-neurons 1000
```

## Think

```bash
mneme think --db "$DB" --prompt "What deserves my attention today?"
```

`think` performs two operations:

1. The prompt activates semantically similar neurons from the local latent index.
2. Activation spreads only over active synapses, weighted by strength and
   confidence. Candidate and killed synapses never become factual thought paths.

Dated memory naturally decays. Project neurons retain a higher floor because a
long-running project can remain relevant without a recent dated note. The output
contains activated neurons, activation values, the path that activated each
neuron, source provenance, and a compact context block an LLM can consume.

Latent similarity creates associative leads, not facts. Source provenance remains
mandatory before the LLM makes a factual claim.

## Scope

This is intentionally a vertical slice, not a rewrite. Existing tables and
commands remain available while we compare whether this interface causes better
LLM thought. If it does, state, prediction, and lifecycle machinery can move
behind activation, inhibition, decay, and feedback rather than expanding the
public model.
