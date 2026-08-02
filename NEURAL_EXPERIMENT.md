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
are removed. The bounded candidate set is selected before evidence aggregation,
so a no-op refresh does not scan and join the full graph.
Headings, extracted observation nodes, wikilinks, and dates are excluded from the
latent seed index; they remain available through graph propagation. Large graphs
can start with the most recently updated semantic neurons:

```bash
mneme index --db "$DB" --max-neurons 1000
```

Archived/merged duplicates, operator context, and control files such as
`AGENTS.md`, `SOUL.md`, and `*_OPS.md` are not recallable neurons. They are also
blocked from re-entering results through synapse propagation. This keeps retired
evidence and agent instructions out of user-memory retrieval.

## Think

```bash
mneme think --db "$DB" --prompt "What deserves my attention today?"
```

`think` performs five operations:

1. The prompt activates semantically similar neurons from the local latent index.
2. A bounded lexical rescue lane promotes strong exact entity/project matches
   without replacing the latent ranking. Lexical activation uses absolute IDF
   calibration and can add at most two extra seeds by default.
3. Action-oriented prompts separate intent words (`due`, `deadline`, `attention`,
   and similar terms) from subject anchors. Task neurons—including sensed
   `task:` sources—are preferred over people and background notes, and a subject
   anchor prevents generic deadline-related projects from flooding the seed set.
   Neutral associative prompts retain the requested latent seed count.
4. Activation spreads only over active synapses, weighted by strength and
   confidence. Candidate and killed synapses never become factual thought paths.
5. Returned neurons are hydrated with compact, source-backed evidence from their
   observations, positive active edges, and matching sensed-event metadata.
   Sensed sources use the latest deterministically ordered ingestion revision,
   and every evidence excerpt is size-bounded.

Dated memory naturally decays. Calendar events use structured GWS start/end
metadata rather than ingestion time, so elapsed events lose activation even when
their source URL contains no date. Timestamped events are normalized to UTC for
decay while all-day events retain their declared date. Project neurons retain a
higher floor because a long-running project can remain relevant without a recent
dated note. The
output contains activated neurons, activation values, latent/lexical/synaptic
signals, compact evidence excerpts, source provenance, and context an LLM can
consume.

Latent similarity creates associative leads, not facts. Source provenance remains
mandatory before the LLM makes a factual claim.

One embedding is a lossy associative fingerprint, not a reversible copy of a
note. Latent activation identifies where to look; evidence hydration supplies
dates, amounts, descriptions, and relationship evidence from the stored sources.

## Scope

This is intentionally a vertical slice, not a rewrite. Existing tables and
commands remain available while we compare whether this interface causes better
LLM thought. If it does, state, prediction, and lifecycle machinery can move
behind activation, inhibition, decay, and feedback rather than expanding the
public model.
