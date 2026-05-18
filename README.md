# Mneme

![Mneme — graph memory for AI agents](assets/mneme-header_v002.png)

**Mneme** is a local-first graph memory layer for AI agents.

It turns Markdown notes into an inspectable SQLite memory graph: notes become nodes, links/tasks/bullets become evidence-backed edges and observations, and agents can use the graph to generate thought paths, audit why relationships exist, or build prompt-time context packs.

> Mneme (Μνήμη) means memory.

## Current status

Mneme is an **alpha** public package. The public repository contains the sanitized, reusable core:

- Markdown vault ingestion
- SQLite graph storage
- relationship ontology seeding
- edge evidence + debug/audit logs
- retrieval-backed context and thought surfacing
- thought-path generation and rendered cards
- SVG/PNG thought-card rendering
- privacy-first rebuild defaults and scans
- CLI commands for ingestion, retrieval, thought surfacing, scoped graph memory, research resolution writeback, and edge explanation

The private dogfood runtime is also exploring active synapse validation, graph workbench UX, and prompt-time retrieval. Those patterns are documented below as design direction, but only shipped public CLI commands are listed in the CLI section.

The shared public/private graph semantics are documented in [GRAPH_CONTRACT.md](GRAPH_CONTRACT.md), including edge/synapse status mapping and promotion rules.

The repo also includes a Hermes-compatible skill bundle at
`skills/mneme-agent-brain/`. Install or point Hermes at that
directory when an agent should operate Mneme as a working brain. The skill
contains the `SKILL.md` entrypoint, a detailed operator runbook, and a smoke
helper that delegates to `scripts/hermes_brain_ready.sh`.

## What it does

- Ingests Markdown notes from a vault/folder.
- Extracts notes, wikilinks, headings, tasks, dates, email-like strings, and high-signal observations.
- Stores nodes, edges, observations, generated thoughts, relationship types, and edge debug logs in SQLite.
- Distinguishes **reference/structural edges** from **semantic claims** through a seeded relationship ontology.
- Records why an edge exists: source path, evidence text, confidence, extraction rule, and later validation/audit events.
- Performs biased graph walks over unresolved, risky, recent, or connected items.
- Renders compact thought cards as SVG, with optional PNG conversion via ImageMagick.
- Provides a CLI suitable for cron jobs, local agent runtimes, and private graph workbenches.

## Mental model

Mneme treats memory as an auditable graph:

```text
Markdown notes
  -> nodes / observations / evidence-backed edges
  -> SQLite graph + audit log
  -> graph walks, explanations, workbench APIs, or prompt context
```

A line between two nodes is not automatically a fact. Mneme separates:

- **Reference edges** — e.g. `links_to`, created from explicit Markdown wikilinks. Useful for navigation, but not proof of a real-world relationship.
- **Extraction edges** — e.g. `mentions_date`, `mentions_email`, created from text patterns.
- **Observation edges** — e.g. `has_fact`, `has_risk`, `has_blocked`, created from scored bullets/tasks.
- **Semantic relationships** — e.g. `belongs_to`, `located_in`, `part_of`, `father_of`. These are marked as requiring validation before an agent treats them as real-world claims.

This keeps the graph useful without letting weak co-occurrence or casual links become hallucinated truth.

## Privacy model

Mneme is local-first:

- No network calls in the public core
- No telemetry
- No required LLM dependency
- No cloud database
- SQLite stays wherever you put it

Important: generated SQLite databases, JSON output, SVG/PNG cards, and logs can contain snippets from your notes. Do **not** commit generated databases, private cards, logs, or real vault content to public repositories.

Privacy-focused defaults:

- `ingest` and `run-once` rebuild graph tables by default, so stale private nodes/edges are removed when a DB is reused.
- Symlinked Markdown files are skipped by default to avoid reading files outside the vault.
- Generated cards named `thought_*.svg` / `thought_*.png` and SQLite files are blocked by the included privacy scan.
- Public examples are intentionally small and fictional.

## Backup and restore policy

Mneme stores meaningful memory state in SQLite, so backup is part of the workflow, not an afterthought.

Public Mneme remains local-first and does not make cloud calls by default. For any private deployment that runs scheduled thought cards, validation, migrations, or rebuilds:

1. Take a SQLite-consistent snapshot before risky work. Use SQLite's backup API or `.backup`; do not rely on copying a live SQLite file as the only backup.
2. Include a manifest with integrity data: creation time, source DB path, checksums, and counts such as edges/synapses by status.
3. Compress and encrypt the backup before it leaves the machine.
4. Verify decryptability and `PRAGMA integrity_check` before considering the backup valid.
5. Keep local encrypted backups and a restore script that makes a safety copy before replacing the live DB.
6. If the user wants Google Drive backup, use Google Workspace/Drive tooling such as `gws drive +upload` first. Use rclone or other remotes only as fallback.
7. Never print, commit, or send the backup passphrase. If the encrypted backup is stored off-box, the passphrase must be stored separately somewhere safe or cloud restore will be impossible after machine loss.

A private deployment can schedule this as: snapshot -> manifest/checksum -> encrypt -> verify -> upload to Drive -> periodically test restore verification.

## Install

One-command install/update on Linux/macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/georgeantonopoulos/mneme/main/scripts/install.sh | bash
```

Manual install from a checkout:

```bash
git clone <this-repository-url>
cd mneme
python -m pip install -e .
```

Requirements:

- Python 3.10+
- Optional: ImageMagick (`convert` or `magick`) for PNG output. Without it, Mneme writes SVG cards.

### Install / update notes

The installer creates/updates the `mneme` CLI. After installation, check the Markdown editor commands with:

```bash
mneme note --help
```

The package includes the graph memory engine and a small path-safe Markdown editor; there is no separate editor plugin to install.

## Quick start

Configure Mneme once, validate it, then use short commands:

```bash
mneme init --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
mneme doctor
mneme update
mneme candidates
mneme promote-candidates --dry-run
mneme retrieve --prompt "what should the agent remember here?"
mneme surface --prompt "what should surface now?"
mneme thought
```

Research results can be written back as evidence packs plus weighted graph edges:

```bash
mneme resolve --file research-resolution.json
```

You can keep multiple configs if needed:

```bash
mneme --config /tmp/project-mneme.json init --vault ./examples/vault --db /tmp/project.sqlite --out /tmp/project_out
mneme --config /tmp/project-mneme.json run-once
```

Or run one-off commands with explicit paths:

```bash
mneme run-once --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
```

The command prints JSON with the generated title, thought path, and image path. Agent runtimes can use that image as a proactive visual memory nudge.

## CLI

### Create and validate config

```bash
mneme init --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
mneme doctor
```

Default config path is `~/.config/mneme/config.json`. Pass `--config /path/to/config.json` before the subcommand to use another config. Once configured, `ingest`, `update`, `retrieve`, `surface`, `thought`, `run-once`, and `write` can read missing `--vault`, `--db`, or `--out` values from config when that command needs them.

### Ingest a Markdown vault

```bash
mneme ingest --vault ./examples/vault --db /tmp/mneme.sqlite
```

By default this rebuilds graph tables to avoid stale data and keeps deterministic navigation/extraction edges as `candidate` rather than making every parsed link active. Source-contained observation edges can be active; durable validated active edges and killed tombstones are preserved across rebuilds.

If you want to refresh the graph while preserving generated thought history, use `update`:

```bash
mneme update --vault ./examples/vault --db /tmp/mneme.sqlite
```

If you explicitly want append-only behaviour:

```bash
mneme ingest --vault ./examples/vault --db /tmp/mneme.sqlite --append
```

### Candidate promotion

Mneme is selective by default: parsed links/headings/dates/emails remain candidates until review or validation. To inspect candidate paths:

```bash
mneme candidates --db /tmp/mneme.sqlite
```

To opt into bulk activation, run a dry run first. The default mode only promotes validated research candidates; `--mode all` is intentionally explicit because it can make the graph noisy.

```bash
mneme promote-candidates --db /tmp/mneme.sqlite --dry-run
mneme promote-candidates --db /tmp/mneme.sqlite --mode validated-only
# explicit noisy option:
mneme promote-candidates --db /tmp/mneme.sqlite --mode all
```

### Safely edit Markdown notes

Mneme ships with a small path-safe Markdown editor for agents and scripts. It is part of the installed `mneme` CLI, returns JSON, uses vault-relative `.md` paths only, writes atomically, creates backups for changed existing notes, and supports dry-run diffs.

```bash
mneme note read Projects/new-note.md --vault ./examples/vault
mneme note write Projects/new-note.md --vault ./examples/vault --mode create --content '# New note
'
mneme note replace Projects/new-note.md --vault ./examples/vault --find 'New note' --replace 'Updated note' --dry-run
mneme note upsert-section Projects/new-note.md --vault ./examples/vault --heading Status --content 'Ready for review'
mneme note add-bullet Projects/new-note.md --vault ./examples/vault --heading Tasks --bullet 'Follow up'
```

Use `mneme note upsert-section` for section-level updates instead of fragile multiline find/replace. Use `mneme note add-bullet` for deduped bullets under a heading. These commands are intentionally small: exact replace, section upsert, bullet insertion, read, and write — not a full Markdown platform.

The older top-level `mneme write` command remains as a simple compatibility shortcut:

```bash
mneme write --vault ./examples/vault --path Projects/new-note.md --mode create --content '# New note
'
printf -- '- Follow up\n' | mneme write --vault ./examples/vault --path Projects/new-note.md --mode append
```

`mneme note` and `mneme write` only accept relative `.md` paths that resolve inside the vault. Modes are `create`, `append`, and `overwrite`.

For development:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```


### Write resolved research back to the graph

When an agent finishes source-backed research, pass a JSON resolution payload to `mneme resolve`. Mneme writes a durable Markdown evidence pack under `Sources/` and creates weighted graph edges.

```bash
mneme resolve --vault ./examples/vault --db /tmp/mneme.sqlite --file research-resolution.json
```

Minimal payload:

```json
{
  "slug": "school-clubs",
  "title": "School clubs resolved",
  "date": "2026-04-26",
  "sources_checked": ["email", "payment", "calendar", "vault"],
  "claims": [
    {
      "subject": "Example Child",
      "subject_type": "person",
      "predicate": "attends_activity",
      "object": "Handwriting Club",
      "object_type": "activity",
      "confidence": 0.94,
      "strength": 0.93,
      "certainty": "confirmed",
      "source_type": "payment",
      "evidence": "Payment receipt and school brochure confirm the club timing."
    }
  ],
  "unresolved": ["Morning club paid but child assignment is unclear."]
}
```

Safety rule: only sourced, confirmed/certain claims at or above `--active-threshold` (`0.90` by default) become `active` edges. Pending, unsupported, or lower-confidence claims become `candidate` edges. Candidate edges are stored for audit and follow-up, but graph walks/thoughts ignore them so unresolved claims do not become proactive “truth.”

The command accepts JSON via `--file` or stdin, which keeps the interface simple for future Node/npm wrappers.

### Generate one thought from an existing DB

`mneme thought` now uses the proactive scorer by default: it ranks high-signal observations, open loops, deadlines, hint matches, important note types, and recently-surfaced penalties before rendering a card.

Inspect candidates before generating:

```bash
mneme candidates --db /tmp/mneme.sqlite --limit 5
```

Explain scored and suppressed candidates:

```bash
mneme debug-candidates --db /tmp/mneme.sqlite --include-skipped
```

Generate the top thought card:

```bash
mneme thought --db /tmp/mneme.sqlite --out /tmp/mneme_out
```

### Retrieve prompt-time context

Build a deterministic local context pack for an agent prompt:

```bash
mneme retrieve --db /tmp/mneme.sqlite --prompt "What needs follow-up for the supplier?" --budget 2500 --max-items 8
```

`retrieve` uses the same scoring core as `candidates` and `thought`. It returns
source-backed observations, relevant edges, score factors, freshness/source
quality notes, skipped-item reasons, and a `truth_policy` for every edge. Killed
edges are excluded. Candidate semantic edges may be shown as `candidate_only`,
but they are not phrased as facts.

### Surface thoughts from retrieval

Use `surface` when an agent wants thought cards from the same cluster-aware,
brain-labelled retrieval path instead of a random walk:

```bash
mneme surface --db /tmp/mneme.sqlite --prompt "what should I remember about supplier launch readiness?" --limit 5
```

Each surfaced thought keeps the generated `title`, `insight`, `action`, and
graph `path`, plus a `surface` block with the retrieval item, matched terms,
cluster, brain label, and truth policy that caused it to appear. The response
also includes `suggested_actions`. For example, a source-contained observation
may suggest appending a bullet under `Next Actions`; a candidate synapse may
suggest explicit validation or deletion before it is trusted.

### Add and remove scoped agent memory

Agents can add working memory to the graph without editing Markdown notes by
using a `mneme://` source namespace:

```bash
mneme remember add --db /tmp/mneme.sqlite --file /tmp/agent-memory.json
mneme surface --db /tmp/mneme.sqlite --prompt "temporary validation memory"
mneme remember remove --db /tmp/mneme.sqlite --source-path mneme://test/validation
```

Payloads may contain `nodes`, `edges`, and `observations`. Edges and
observations must reference nodes from the same payload, which keeps temporary
memory removable as a unit:

```json
{
  "source_path": "mneme://test/validation",
  "nodes": [
    {"ref": "agent", "type": "agent", "name": "Test agent"},
    {"ref": "task", "type": "task", "name": "Validate retrieval"}
  ],
  "edges": [
    {"src": "agent", "dst": "task", "relation": "relates_to", "status": "active"}
  ],
  "observations": [
    {"node": "task", "kind": "fact", "text": "Validate retrieval before trusting output.", "score": 5}
  ]
}
```

`remember remove` only accepts `mneme://` sources. That keeps vault-ingested
notes and user-authored Markdown outside the deletion path.

### Build the Hermes-ready working brain

The working-brain pipeline keeps graph structure deterministic and runs model
labelling as a replaceable harness step. A local Ollama model is useful for
dogfooding, while Hermes can pass its own command through the same interface.

```bash
mneme consolidate \
  --db /tmp/mneme.sqlite \
  --label-provider ollama \
  --label-model gemma4:e4b \
  --label-max-clusters 25

mneme brain label \
  --db /tmp/mneme.sqlite \
  --targets cluster,node,synapse,relationship \
  --max-clusters 25 \
  --max-nodes 50 \
  --max-synapses 50 \
  --max-relationships 25 \
  --label-provider ollama \
  --label-model gemma4:e4b

mneme brain report --db /tmp/mneme.sqlite
mneme retrieve --db /tmp/mneme.sqlite --prompt "what should the agent remember here?"
```

Hermes can swap the model runner without changing Mneme's graph logic:

```bash
mneme brain label \
  --db /tmp/mneme.sqlite \
  --targets cluster,node,synapse,relationship \
  --label-provider hermes \
  --label-command "hermes label --json"
```

For a single smoke script:

```bash
MNEME_LABEL_PROVIDER=ollama MNEME_LABEL_MODEL=gemma4:e4b \
  scripts/hermes_brain_ready.sh /tmp/mneme.sqlite "retrieval prompt"
```

The script runs the full harness path Hermes needs before trusting the DB:
`consolidate`, `brain label`, `brain report`, `retrieve`, and `surface`. Set
`MNEME_SURFACE_LIMIT` to change how many retrieval-backed thoughts the final
surface check returns.

Set `MNEME_BRAIN_DEPTH` when the agent needs a different pass size:

```bash
MNEME_BRAIN_DEPTH=smoke scripts/hermes_brain_ready.sh /tmp/mneme.sqlite
MNEME_BRAIN_DEPTH=default scripts/hermes_brain_ready.sh /tmp/mneme.sqlite
MNEME_BRAIN_DEPTH=deep scripts/hermes_brain_ready.sh /tmp/mneme.sqlite
MNEME_BRAIN_DEPTH=full scripts/hermes_brain_ready.sh /tmp/mneme.sqlite
```

`smoke` labels a tiny proof set, `default` labels the largest clusters plus top
nodes and synapses, `deep` labels every discovered cluster plus a broader active
frontier, and `full` attempts to label every eligible target. Individual
`MNEME_LABEL_MAX_*` values still override the preset. `mneme brain report`
returns per-target coverage so Hermes can tell whether the latest brain is
shallow, moderate, or deep before trusting retrieval.

`retrieve` includes `clusters` and `brain_labels` in its JSON response, and
returned items may include `cluster` and `brain_label` metadata showing why a
node or synapse entered the context pack.

### Ingest and generate in one command

```bash
mneme run-once --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
```

Useful flags:

- `--hints deadline,lease,tax` — bias observation scoring and walks toward certain words
- `--hops 5` — number of graph hops in a thought path
- `--max-notes 100` — limit ingestion for a quick smoke test
- `--append` — keep existing nodes/edges instead of rebuilding; use carefully because stale data can remain
- `--follow-symlinks` — follow symlinked Markdown files that resolve inside the vault

### Explain why an edge exists

```bash
mneme explain-edge <edge-id> --db /tmp/mneme.sqlite
```

This prints:

- the edge and its source/destination nodes
- evidence text and source path
- relationship type metadata
- whether the relationship type requires validation
- debug/audit timeline entries

Example use case: a graph workbench can show why two nodes are connected instead of merely drawing a line.

## Relationship ontology

Mneme seeds a small relationship ontology in SQLite. Current categories include:

| Category | Examples | Meaning |
|---|---|---|
| `reference` | `links_to`, `linked_from` | Navigational Markdown references. Useful, but not proof of a semantic claim. |
| `structure` | `has_heading` | Document structure extracted from Markdown. |
| `extraction` | `mentions_date`, `mentions_email` | Pattern-extracted facts from text. |
| `observation` | `has_fact`, `has_risk`, `has_blocked`, `has_done` | Scored bullets/tasks that may be useful to an agent. |
| `semantic` | `belongs_to`, `located_in`, `part_of`, `father_of`, `attends_activity` | Real-world claims; should be validated before being treated as facts. |
| `semantic_pending` | `requested_activity` | Pending/requested real-world claims; useful for follow-up, not resolved truth. |

Unknown relationship types default to validation-required.

## Edge audit log

Every created edge can carry a debug entry explaining its origin. For example, an edge generated from `[[Beta]]` stores that it came from an explicit Markdown wikilink, not from semantic reasoning.

Agents and UIs should use this audit trail to answer:

- Why does this edge exist?
- Which source text created it?
- Is it a navigational reference or a semantic claim?
- Was it later validated, rejected, or superseded?

The public package currently logs creation events. Private deployments can extend the same table with validation, rejection, or lifecycle events.

## Graph workbench / UI design

Mneme's graph-building layer is intentionally location-agnostic: callers pass `--vault`, `--db`, and `--out`. A workbench should preserve that model rather than hard-coding deployment paths.

Recommended public packaging shape:

```bash
mneme ingest --vault /path/to/markdown --db /private/path/mneme.sqlite
mneme serve --db /private/path/mneme.sqlite --host 127.0.0.1 --port 8002 --mount /mneme
```

`mneme serve` is a design target, not yet part of the public CLI. A served workbench should be optional, read-only by default, and configurable for:

- graph DB path
- host/port
- URL mount path
- auth/reverse-proxy layer
- output/static asset directory
- node/link limits

For large graphs, workbench implementations should:

- auto-frame from actual node bounds
- support pointer events: drag, pan, pinch-zoom, and double-tap/frame on mobile
- merge aliases/path entities/display-title notes into canonical nodes before rendering
- cull offscreen nodes/links
- cap physics simulation work
- display relationship type, evidence, source path, and audit status in the details panel

## Agent / prompt-time retrieval direction

Mneme's long-term role is not just thought cards. It should also act as a fast context selector for agents:

```text
user prompt
  -> local Mneme retrieval over active/high-confidence graph context
  -> compact evidence pack
  -> model response grounded in source-backed memory
```

Recommended retrieval scoring direction:

1. active semantic relationships
2. strong active provenance/reference relationships
3. high `strength × confidence`
4. trusted source type
5. freshness / cooldown / reinforcement age
6. exact entity and lexical match
7. observation fallback
8. candidate or weak co-occurrence edges last

Killed/rejected edges should be excluded, and stale/low-strength/noisy observations should be demoted even when they lexically match the prompt.

This prompt-time retrieval layer is available through the public `mneme retrieve` CLI command.

## How it works today

1. Markdown notes become graph nodes.
2. Wikilinks, headings, tasks, dates, and email-like strings become connected nodes/edges.
3. Each edge is classified through the seeded relationship ontology.
4. Each edge gets a debug-log entry with source path, evidence text, confidence, and creation rationale.
5. High-signal bullets and tasks become observations.
6. Mneme chooses a biased seed node, walks nearby relationships, and creates a short thought.
7. The renderer writes a card to the output directory.

This prototype is intentionally conservative: it does not claim a relationship is true just because two things co-occur. Treat thought cards as prompts for review unless the edge audit trail and relationship type support stronger claims.

## Safety checks before publishing changes

```bash
python -m pytest -q
python scripts/privacy_scan.py
mneme run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out
```

The privacy scan fails on common generated artifacts, private paths, emails, secret-like assignments, private-key blocks, and common token prefixes. Projects can add custom forbidden terms without storing them in the repo:

```bash
MNEME_FORBIDDEN_TERMS="private-project-name,internal-domain" python scripts/privacy_scan.py
```

Before committing, also check for generated/private files:

```bash
find . -path ./.git -prune -o -name '*.sqlite*' -o -name 'thought_*.svg' -o -name 'thought_*.png' -o -name '*.pyc' -o -name '__pycache__' -print
```

## Roadmap

Near-term:

- configurable ontology files
- graph workbench API/server
- active/candidate/killed edge lifecycle helpers
- canonical entity/alias resolution
- prompt-time retrieval CLI/API
- contradiction and stale open-loop detection

Longer-term:

- richer render themes
- agent framework adapters
- optional vector search for fuzzy recall
- optional graph-native projection while keeping SQLite as the local audit ledger
