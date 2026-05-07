# Mneme

![Mneme — proactive thought surfacing for AI agents](assets/mneme-header_v002.png)

**Mneme** is a local-first proactive thought-surfacing system.

It treats sources as senses, converts bounded evidence into observations and synaptic links, applies activation/decay/reinforcement, and surfaces useful next actions before the user asks.

> Mneme (Μνήμη) means memory.

## Current status

Mneme is an **alpha** public package. The public repository contains the sanitized, reusable core:

- Markdown vault sense and normalized evidence ingestion
- optional Google Workspace sense through the local `gws` command
- SQLite graph storage
- relationship ontology seeding
- edge evidence + debug/audit logs
- deterministic activation, thought candidate generation, and feedback
- SVG/PNG thought-card rendering
- privacy-first rebuild defaults and scans
- CLI commands for senses, ticks, surfacing, feedback, inspectability, research resolution writeback, and edge explanation

The private dogfood runtime is also exploring active synapse validation, graph workbench UX, and later prompt-time context selection. Those patterns are documented below as design direction, but the public CLI is centered on the sense -> evidence -> activation -> surface -> feedback loop.

The shared public/private graph semantics are documented in [GRAPH_CONTRACT.md](GRAPH_CONTRACT.md), including edge/synapse status mapping and promotion rules.

## What it does

- Ingests source events from senses. Markdown vaults are one sense; Hermes/Google Workspace users can optionally use `gws` for Gmail, Calendar, and Tasks.
- Extracts notes, wikilinks, headings, tasks, dates, email-like strings, workspace items, and high-signal observations.
- Stores nodes, edges, observations, generated thoughts, relationship types, and edge debug logs in SQLite.
- Distinguishes **reference/structural edges** from **semantic claims** through a seeded relationship ontology.
- Records why an edge exists: source path, evidence text, confidence, extraction rule, and later validation/audit events.
- Scores activation over unresolved, risky, recent, corroborated, or connected items.
- Surfaces current thought candidates and accepts feedback: accept, deny, snooze, kill, acted, already done, too obvious, or good but later.
- Explains why a thought surfaced, including evidence, provenance, relationship statuses, activation factors, and feedback history.
- Renders compact thought cards as SVG, with optional PNG conversion via ImageMagick.
- Provides a CLI nervous-system control surface suitable for cron jobs, local agent runtimes, and private graph workbenches.

## Mental model

Mneme treats cognition as an auditable graph loop:

```text
Senses
  -> bounded evidence
  -> observations
  -> synaptic links
  -> activation / decay / reinforcement / weakening
  -> thought candidates
  -> surfaced next action
  -> user feedback
```

A line between two nodes is not automatically a fact. Mneme separates:

- **Reference edges** — e.g. `links_to`, created from explicit Markdown wikilinks or sensed source links. Useful for navigation, but not proof of a real-world relationship.
- **Extraction edges** — e.g. `mentions_date`, `mentions_email`, created from text patterns.
- **Observation edges** — e.g. `has_fact`, `has_risk`, `has_blocked`, created from scored bullets/tasks.
- **Semantic relationships** — e.g. `belongs_to`, `located_in`, `part_of`, `father_of`. These are marked as requiring validation before an agent treats them as real-world claims.

This keeps the graph useful without letting weak co-occurrence or casual links become hallucinated truth.

Mneme has no Obsidian dependency. Wikilinks/backlinks are connection hints, not semantic truth. Google Workspace support is optional and shells out to `gws`; Mneme does not include Google OAuth code or direct Google API client dependencies.

Mneme also treats later corrections as **guardrails**. If a newer note says an old
tracker row was stale, wrong, hallucinated, or must not be used without fresh
evidence, proactive candidate selection suppresses matching stale open-loop
observations. In other words, “this TODO once appeared in a daily note” is not the
same as “this TODO is currently live”. Agents should validate old tasks against a
fresh source before telling a user that something is still open, overdue, requested,
or stalled.

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
mneme sense run md
mneme tick --surface
mneme surface
mneme feedback <thought_id> --deny --reason "not useful right now"
mneme explain <thought_id>
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

The older `ingest`, `update`, `thought`, and `run-once` commands remain available. Newer automation should prefer `sense run`, `tick`, `surface`, `feedback`, and `explain`.

## CLI

### Create and validate config

```bash
mneme init --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
mneme doctor
```

Default config path is `~/.config/mneme/config.json`. Pass `--config /path/to/config.json` before the subcommand to use another config. Once configured, `ingest`, `update`, `thought`, `run-once`, and `write` can read missing `--vault`, `--db`, or `--out` values from config.

### Ingest a Markdown vault

```bash
mneme ingest --vault ./examples/vault --db /tmp/mneme.sqlite
```

`ingest` remains as a compatibility shortcut. Internally, Markdown is now handled as `MarkdownSense -> SenseEvent -> ingest_sense_events`, the same normalized path used by other senses.

By default this rebuilds graph tables to avoid stale data and keeps deterministic navigation/extraction edges as `candidate` rather than making every parsed link active. Source-contained observation edges can be active; durable validated active edges and killed tombstones are preserved across rebuilds.

If you want to refresh the graph while preserving generated thought history, use `update`:

```bash
mneme update --vault ./examples/vault --db /tmp/mneme.sqlite
```

If you explicitly want append-only behaviour:

```bash
mneme ingest --vault ./examples/vault --db /tmp/mneme.sqlite --append
```

### Senses and cognition pulse

The CLI is the nervous-system control surface:

```bash
mneme sense list
mneme sense run md --vault ./examples/vault --db /tmp/mneme.sqlite
mneme sense run gws --email --calendar --tasks --db /tmp/mneme.sqlite
mneme sense run gws --dry-run
mneme tick --db /tmp/mneme.sqlite
mneme tick --surface --db /tmp/mneme.sqlite
mneme surface --limit 3 --db /tmp/mneme.sqlite
mneme feedback <thought_id> --accept
mneme feedback <thought_id> --snooze 7d
mneme feedback <thought_id> --kill --reason "false assumption"
mneme explain <thought_id> --db /tmp/mneme.sqlite
```

`mneme tick` is not search. It updates deterministic activation scores, applies cooldowns and feedback penalties, suppresses killed candidates, and generates current thought candidates from normalized evidence. `mneme surface` returns the highest-activation candidates with evidence, source/sense provenance, suggested action, and feedback options. Every new command supports `--json` for agent use.

The optional `gws` sense is for Hermes / Google Workspace environments where a `gws` command already exists. Mneme shells out to `gws`; tests use fake command runners and do not require Gmail, Calendar, Tasks, Hermes, network access, or OAuth.

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

### Legacy thought card generation

`mneme thought` remains for backward compatibility and SVG/PNG card generation. For current proactive workflows, use `mneme tick --surface` and `mneme surface`; those commands persist inspectable thought candidates and feed the feedback loop.

Inspect candidates before generating:

```bash
mneme candidates --db /tmp/mneme.sqlite --limit 5
```

Generate the top thought card:

```bash
mneme thought --db /tmp/mneme.sqlite --out /tmp/mneme_out
```

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

For surfaced thought candidates, use:

```bash
mneme explain <thought-id> --db /tmp/mneme.sqlite
```

This explains why the thought surfaced now, including the seed observation/node, bounded evidence, sense provenance, source path or URI, relationship statuses, activation score breakdown, feedback history, and what accept/deny/kill/snooze would do.

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

## Future context selection direction

Mneme's primary loop is proactive thought surfacing. A later agent-facing layer can reuse the same active/high-confidence graph as a fast context selector:

```text
user prompt
  -> local Mneme context selection over active/high-confidence graph context
  -> compact evidence pack
  -> model response grounded in source-backed memory
```

Recommended context-selection scoring direction:

1. active semantic relationships
2. strong active provenance/reference relationships
3. high `strength × confidence`
4. trusted source type
5. freshness / cooldown / reinforcement age
6. exact entity and lexical match
7. observation fallback
8. candidate or weak co-occurrence edges last

Killed/rejected edges should be excluded, and stale/low-strength/noisy observations should be demoted even when they lexically match the prompt.

This prompt-time layer is under private dogfood and is not yet included as a public CLI command.

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
