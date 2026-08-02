# Changelog

## [Unreleased]

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
