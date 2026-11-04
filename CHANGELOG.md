# Changelog

## [Unreleased]

### Added

- `mneme learn --newest-first` perceives the most recent memories first instead of the oldest, so a run that
  stops early (a token budget, Ctrl-C) has spent its effort on what is current.
- `mneme learn --since YYYY-MM` perceives only memories dated in that month or later. Older memories are still
  stored and found by word lookup; they are perceived by a later run without `--since`. Memories already
  perceived are skipped and skipped memories are retried as before, under either option.

### Fixed

- `mneme learn` on a large brain no longer exhausts memory or stalls for hours. On a brain of about 130,000
  memories, the first perception pass used to hold every memory's text and every prompt at once (2 GB+ and
  climbing), and each candidate lookup scored nearly every memory (about 1.4 s each, so days for one pass).
  - Perception now runs in chunks of 25 prompts. Each chunk is built, asked and committed on its own, so memory
    stays flat (under 50 MB in the same test) and an interrupted run keeps every finished chunk. A deferred
    (task-file) mind still receives every prompt in one run.
  - Candidate lookups on brains of 1,000+ memories leave out words found in more than half of all memories.
    BM25 already gives those words almost no weight, so results are unchanged; each lookup is about 50x faster.
  - Perception's candidate lookup asks with at most 6 of each memory's rarest words (preferring words at least
    one other memory shares) instead of every word in the note. Dropping common words alone still left 20-40
    word queries taking 1-1.6 s each on a 130k-memory brain; 6-word queries take under 0.1 s. `mneme ask` and
    other lookups are unchanged.
  - `ingest` compares stored memories by content hash instead of keeping every stored text in memory
    (325 MB down to 64 MB on the same brain).

## [1.1.0] — 2026-11-01

### Added

- `mneme setup`, `mneme learn`, `mneme ask` and `mneme status`: a front door to the LLM-driven cortex, drawn
  in the terminal and fully scriptable with flags and `--json` for agents. `mneme` alone shows a welcome screen.
- Setup wizard. It picks the notes folder and a model: Ollama local or cloud, LM Studio, any OpenAI-compatible
  API, a command-line AI such as `claude -p`, or task files answered by an agent. It tests the model before
  saving anything.
- `OllamaMind` (native `/api/chat`, local or `https://ollama.com` with `OLLAMA_API_KEY`). Minds now answer
  several tasks at once (`workers`) and re-ask once when a reply is not valid JSON.
- Recall: when several topics are chosen they share the 120 skim slots fairly, so a large topic can no
  longer hide a small one. This is how a phishing email in a small topic went missing on a 1,917-memory vault.
- Carry-over from earlier versions. `mneme setup` finds an earlier `mneme init` and uses its vault, and `mneme learn`
  then also reads its graph database, read-only. World-state assertions, the action ledger, predictions,
  aliases, validated and killed relationships, and what the email and calendar senses saw all become memories.
  Pass `--graph-db PATH` to name one, or `--no-graph` to skip it. Nothing earlier is changed or removed.
- `mneme reflect` and `mneme thoughts` (with `--dismiss`): idle reflection from the command line, with `--json`.
- Hermes: the `mneme` and `mneme-agent-brain` skills describe the cortex. The pre-LLM hook makes loading the
  `mneme` skill mandatory on every turn, points at `mneme ask --json` once the cortex is set up, and adds a count
  of open thoughts.
- The installer opens the setup wizard when run in a terminal. `--no-setup` skips it, for agents.

### Changed

- A plain folder of Markdown notes (such as a notes-app vault) can be learned directly. Hidden folders like
  `.obsidian` and `.trash` are skipped.

## [1.0.0] — 2026-08-02

Mneme becomes a local nervous system for agents: perception, activation, trusted propagation, evidence, and feedback in one auditable loop.

### Added

- Incremental local neuron indexing through Ollama, with deterministic hash mode for tests.
- Associative `mneme think`: semantic activation, capped lexical rescue, temporal decay, action-aware ranking, and active-synapse propagation.
- Archive, merged-duplicate, operator-file, and structural-node boundaries across indexing, hydration, and graph propagation.
- Full Gmail message sensing with decoded text/HTML bodies, sender direction, thread IDs, and attachment metadata.
- Canonical aliases, action verification predictions, contradiction radar, event-gated predictions, read-time temporal validity, `world watch`, and scored retrieval evaluation.
- Repo-managed Hermes pre-LLM hook with drift checks and compact injection safety.

### Changed

- Package version and runtime version are now `1.0.0`.
- Mneme is marked stable rather than alpha.
- Neural memory is a shipped capability, not an experimental branch.
- README and architecture documentation now describe the current product and CLI.
- Incremental indexing applies candidate bounds before evidence aggregation and deterministically hashes ordered evidence.

### Fixed

- Archived or operator evidence can no longer seed, hydrate, or re-enter results through synapses.
- Windows-style source paths follow the same retrieval rules as POSIX paths.
- Invalid neural API and CLI limits fail before index mutation.
- Caller-owned SQLite row factories are restored, including after embedding errors.
- Calendar decay uses structured event time rather than ingestion time.
- Latest sensed-event revisions are selected deterministically.
- Hook classification strips injected reminders and handles negation/future phrasing consistently.

### Safety

- Candidate and killed synapses never propagate as factual paths.
- Every activation retains source provenance and bounded evidence.
- Privacy scans cover generated memory artifacts and public fixtures remain fictional.

## Pre-1.0 history

The exploratory `0.x` releases were published out of semantic-version order. The entries below preserve their real publication dates, newest first.

## [0.2.0] — 2026-07-04

### Added — World Model Layer

Mneme gained a durable world-model layer above the rebuildable graph:

- `world_state_assertions` for current source-backed beliefs.
- `world_predictions` for deterministic expectations.
- `world_actions` for externally verifiable side effects.
- State, prediction, world-tick, action, and agent-preflight CLI commands.
- Research resolution dual-write into validated graph edges and current assertions.

### Fixed

- Dry-run paths avoid durable database and temporary-file mutation.
- Prediction dates compare parsed timestamps rather than strings.
- Research-resolution writes roll back and close safely on failure.
- Assertion reactivation and source deletion follow consistent lifecycle rules.

## [0.3.0] — 2026-05-31

- Added the user-confirmed correction pipeline and authoritative correction scoring.
- Added path discovery through `mneme doctor`.
- Added automatic post-surface pruning guidance.
- Added the canonical `skills/mneme/` operator skill.

## [0.1.1] — 2026-04-06

- Initial public alpha release.
- Markdown ingestion, SQLite graph storage, relationship ontology, evidence logs, retrieval, thought surfacing, cards, privacy scans, and the first Hermes bundle.
