# Agent-brain architecture

Mneme gives an agent one local memory loop:

```text
sense → score → retrieve / surface → explain → feedback
```

## Perception

Configured senses normalize Markdown, Gmail, Calendar, Tasks, sessions, and other sources into `sense_events`. Ingestion turns them into nodes, observations, and evidence-backed edges.

```bash
mneme sense list
mneme sense run all --json
mneme update
```

## Recall

Two paths share the same evidence:

- `retrieve` builds a compact prompt-time context pack.
- `surface` and `tick` find memories that deserve attention without a direct query.

```bash
mneme retrieve --prompt "What matters now?"
mneme tick --surface --json
mneme surface --limit 3 --json
```

Every result carries score factors, provenance, truth policy, and suppression rules. Killed edges remain silent. Candidate edges remain tentative.

## Association

The local neuron index adds semantic association without replacing the graph:

```bash
mneme index --db "$DB" --provider ollama --model nomic-embed-text
mneme think --db "$DB" --prompt "What connects to this?"
```

Latent similarity chooses where to look. Active synapses and source evidence determine what can be said.

## Current truth

The world model holds durable state, deterministic predictions, contradictions, and externally verifiable actions. It survives graph rebuilds without pretending every observation is current truth.

```bash
mneme agent preflight --db "$DB" --prompt "$PROMPT"
mneme state conflicts --db "$DB"
mneme world tick --db "$DB" --dry-run
```

## Learning pressure

Feedback changes future recall without rewriting history:

```bash
mneme explain THOUGHT_ID --json
mneme feedback THOUGHT_ID --accept --json
mneme feedback THOUGHT_ID --deny --json
mneme forget --db "$DB" --days-threshold 30 --dry-run
```

The result is not a database pretending to think. It is a cautious memory substrate: local, inspectable, and able to show its work.
