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
6. If the user wants Google Drive backup, use Google Workspace/Drive tooling such as `gws drive files create --upload /path/file --params '{"fields":"id,name,size"}'` first. Use rclone or other remotes only as fallback.
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

## Prompt path classifier for agent hooks

Mneme includes a small helper for prompt-time routing in agent integrations. It classifies the raw user message as:

- `retrieval` — normal recall/search/help/planning.
- `correction` — the user corrects, contradicts, resolves, dismisses, or marks memory/assistant state stale.
- `both` — the user corrects something and also asks for help/search/action.

This is intentionally optional: the public Mneme core remains local-first and makes **no network calls by default**. Agent hooks can opt in to a model-backed classifier and keep a conservative regex fallback.

### Choosing a classifier model during onboarding

For Hermes/Ollama Cloud deployments, the tested default is:

```bash
export MNEME_PATH_CLASSIFIER_ENABLED=1
export MNEME_PATH_CLASSIFIER_PROVIDER=ollama-cloud
export MNEME_PATH_CLASSIFIER_MODEL=gemma4:31b
export MNEME_PATH_CLASSIFIER_TIMEOUT=2.0
export OLLAMA_BASE_URL=https://ollama.com/v1
export OLLAMA_API_KEY=...   # keep this in your agent's private .env, never in the repo
```

Why this default: in private dogfood testing, `gemma4:31b` via Ollama Cloud correctly classified `retrieval`, `correction`, and `both` examples in under ~1 second through the OpenAI-compatible `/chat/completions` route. Local tiny models can work, but on small CPU-only VPSes they may be slower than cloud inference or need more prompting.

Alternative local choices to try when you need zero network calls:

- `qwen3.5:0.8b` — good accuracy with few-shot prompting, but can be slow on 2-vCPU machines.
- `qwen2.5:0.5b-instruct` — smaller/faster, lower expected accuracy.
- `smollm2:360m-instruct-q4_K_M` — ultra-small, useful as an experiment but may miss subtle corrections.

Integration rule: always strip injected context and generated hook text before classification. The classifier must see only the user message, not blocks like `[Prompt-time retrieved context]` or `MNEME RETRIEVAL PATH ...`, otherwise it can be contaminated by its own previous routing instructions.

Python integration sketch:

```python
from mneme.path_classifier import classify_path

route = classify_path(
    user_message,
    model=os.getenv("MNEME_PATH_CLASSIFIER_MODEL", "gemma4:31b"),
    timeout=float(os.getenv("MNEME_PATH_CLASSIFIER_TIMEOUT", "2.0")),
)
if route["path"] in {"correction", "both"}:
    # run correction/writeback path
    ...
else:
    # run retrieval path
    ...
```

## Quick start

Configure Mneme once, validate it, then use short commands:

```bash
mneme setup
```

This opens a friendly terminal onboarding menu that asks for:

- Markdown vault path
- SQLite database path
- output/cards directory
- whether to enable Google Workspace (`gws`) as a sense
- whether to enable the Hermes prompt path classifier
- classifier provider/model choice (`gemma4:31b` on Ollama Cloud is the tested default)
- Hermes `.env` location for private API keys

For non-interactive setups you can still use:

```bash
mneme init --vault ./examples/vault --db /tmp/mneme.sqlite --out /tmp/mneme_out
```

Then validate and run:

```bash
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

Agent runtimes can also run a deterministic post-response safety net after a final answer. It does **not** trust the model blindly: it only writes when the response includes an explicit `mneme-resolution` JSON block or matches a narrow source-backed pattern (for example a property purchase/completion date answer that cites solicitor/SDLT/email evidence). This is intended for `post_llm_call` / post-response hooks so durable facts do not depend on the model remembering to call `mneme resolve` manually:

```bash
mneme post-response \
  --user-message-file /tmp/user.txt \
  --assistant-response-file /tmp/assistant.txt \
  --vault ./examples/vault \
  --db /tmp/mneme.sqlite \
  --json
```

Use `--dry-run` while wiring hooks.

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

Default config path is `~/.config/mneme/config.json`. Pass `--config /path/to/config.json` before the subcommand to use another config, or set `MNEME_CONFIG`. Runtime paths resolve in this order: CLI argument, environment variable, config file. The generic environment variables are `MNEME_DB`, `MNEME_VAULT`, `MNEME_OUT`, and `MNEME_HINTS`. Once configured, CLI commands can read missing `--vault`, `--db`, or `--out` values from those defaults.

Example config for sense-first automation:

```json
{
  "db": "/path/to/mneme.sqlite",
  "vault": "/path/to/markdown-vault",
  "out": "/path/to/mneme-out",
  "hints": ["deadline", "reminder", "invoice"],
  "senses": [
    {"id": "vault", "type": "md", "enabled": true, "config": {"path": "/path/to/markdown-vault"}},
    {"id": "gws", "type": "gws", "enabled": true, "config": {"email": true, "calendar": true, "tasks": true}}
  ]
}
```

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
mneme sense run hermes_sessions --db /tmp/mneme.sqlite --limit 10
mneme tick --db /tmp/mneme.sqlite
mneme tick --surface --db /tmp/mneme.sqlite
mneme tick --sense hermes_sessions --db /tmp/mneme.sqlite
mneme surface --limit 3 --db /tmp/mneme.sqlite
mneme feedback <thought_id> --accept
mneme feedback <thought_id> --snooze 7d
mneme feedback <thought_id> --kill --reason "false assumption"
mneme explain <thought_id> --db /tmp/mneme.sqlite
```

`mneme tick` is not search. It updates deterministic activation scores, applies cooldowns and feedback penalties, suppresses killed candidates, and generates current thought candidates from normalized evidence. `mneme surface` returns the highest-activation candidates with evidence, source/sense provenance, suggested action, and feedback options. Every new command supports `--json` for agent use.

The optional `gws` sense is for Google Workspace environments where a `gws` command already exists and is already authenticated. Mneme shells out to the current resource-style CLI forms (`gws gmail users messages list`, `gws calendar events list`, and `gws tasks tasks list`) with JSON `--params`; it does not manage OAuth or include Google API client dependencies. Tests use fake command runners and do not require Gmail, Calendar, Tasks, network access, or OAuth.

### Source Packets

Sensor crons and integrations should hand Mneme bounded source packets instead of pasting raw source text into prompts. Raw email bodies, attachments, and extracted document text are untrusted data. Mneme packet helpers store raw bytes on disk and persist only metadata, hashes, extraction status, and short sanitized excerpts labelled `UNTRUSTED DATA`.

```bash
pdftotext ./notice.pdf /tmp/notice.txt
mneme packet create \
  --packet-dir /tmp/mneme_packets \
  --source email \
  --kind attachment \
  --raw-path ./notice.pdf \
  --text-path /tmp/notice.txt
```

For automation, prefer `--text-path` or stdin instead of embedding raw external text in prompts or shell command strings. Sanitization removes invisible Unicode such as zero-width joiners/non-joiners, combining grapheme joiners, soft hyphens, and HTML zero-width entities, then redacts common prompt-injection markers from prompt-facing excerpts. Packet metadata is appended to `manifest.jsonl` and indexed in `source_packets.sqlite`.

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

### Vault deduplication

Mneme can detect and merge duplicate notes in your vault based on title similarity and content overlap, using synapse strength from the graph to decide which duplicate to keep.

```bash
mneme dedup --vault ./examples/vault --db /tmp/mneme.sqlite --dry-run
mneme dedup --vault ./examples/vault --db /tmp/mneme.sqlite --auto
mneme dedup --vault ./examples/vault --db /tmp/mneme.sqlite --json
```

Options:

- `--dry-run` — scan and report duplicate groups without making changes
- `--auto` — automatically merge duplicates (content from weaker nodes is merged into the stronger winner, then weaker files are deleted)
- `--json` — output results as JSON for programmatic use
- `--backup-dir` — custom backup directory (default: `~/.hermes/vault_backups`)
- `--title-threshold` — similarity threshold for title matching (default: 0.85)
- `--content-threshold` — content overlap threshold (default: 0.6)

The dedup command:

1. Scans the vault for files with similar titles or high content overlap
2. Queries the Mneme graph for synapse strength of each duplicate
3. Merges all content into the strongest node (by synapse score)
4. Tags the winner with `merged:` metadata listing merged sources
5. Backs up deleted files with timestamps before removal
6. Preserves daily notes — files with different dates are never merged together

After deduplication, run `mneme update` to refresh the graph:

```bash
mneme update --vault ./examples/vault --db /tmp/mneme.sqlite
```

### Hermes Sessions sense (chat history)

Mneme can ingest Hermes Agent conversation transcripts as a sense source, enabling retrieval to blend vault content with chat history.

```bash
mneme sense run hermes_sessions --db /tmp/mneme.sqlite --limit 10
mneme tick --sense hermes_sessions --db /tmp/mneme.sqlite
```

The `hermes_sessions` sense:

- Reads JSONL session files from `~/.hermes/sessions` (or custom path via config)
- Extracts user/assistant messages as text evidence
- Creates `SenseEvent`s with `event_type="conversation"`
- Enables cross-session knowledge retrieval and corroboration

Config example:

```json
{
  "senses": [
    {"id": "vault", "type": "md", "enabled": true, "config": {"path": "/path/to/vault"}},
    {"id": "hermes_sessions", "type": "hermes_sessions", "enabled": true, "config": {"path": "~/.hermes/sessions", "limit": 50}}
  ]
}
```

Chat sessions are now included in `mneme retrieve` results, `mneme surface` candidates, and `mneme explain` evidence chains.

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
