# Private-to-Public Divergence Guide

Mneme is designed to be dogfooded in private agent runtimes without letting private deployment details leak into the public package. This guide explains how to inspect a private runtime, decide what belongs upstream, and promote only sanitized, reusable improvements.

## Core principle

Promote mechanics, not memories.

Good public changes describe reusable behavior:

- sense interfaces and source-packet boundaries;
- graph contracts and relationship-status invariants;
- correction/retrieval routing semantics;
- freshness, decay, and stale-open-loop guardrails;
- thought lifecycle state machines;
- privacy scans, fixture tests, and setup flows.

Keep private deployment facts private:

- real people, addresses, emails, domains, message IDs, dates, account numbers, and project names;
- real vault contents, generated cards, SQLite databases, logs, and transcripts;
- local filesystem paths, cron IDs, service names, backup folders, and secret locations;
- incident reports whose examples identify the user or a third party.

## Public vs private boundary

| Area | Public repo | Private deployment |
|---|---|---|
| Senses | generic `SenseEvent` abstractions, Markdown/session/GWS adapters, tests with fictional fixtures | configured source paths, real Gmail/calendar/vault content, local ledgers |
| Graph | edge schema, relationship ontology, contract tests, promotion rules | validated facts about real people/projects, private synapse/edge IDs |
| Retrieval | generic ranking/freshness rules and explanation APIs | user-specific source priority and private evidence packs |
| Corrections | classifier, guardrail semantics, tombstone/feedback behavior | concrete tombstones for real false claims |
| Thought cards | contract shape, lifecycle APIs, rendering rules | generated cards from private notes or sessions |
| Automation | documented integration patterns and safe defaults | actual cron jobs, platform tokens, service restarts |
| Backups | SQLite-consistent backup/encrypt/verify policy | passphrase files, Drive folder IDs, live backup archives |

## Promotion decision checklist

Before upstreaming a private dogfood lesson, answer yes to all of these:

1. Is the change source-agnostic or expressible with fictional fixtures?
2. Does it preserve Mneme's local-first default and avoid required cloud/LLM calls?
3. Can it be tested using temporary vaults/databases and invented data?
4. Does it avoid real names, emails, addresses, domains, IDs, message subjects, and local absolute paths?
5. Does it strengthen a public invariant such as evidence-before-belief, candidate caution, tombstone preservation, or explicit lifecycle updates?
6. Can the docs explain the behavior without referencing the private incident that motivated it?
7. Does `python scripts/privacy_scan.py` pass after the change?

If any answer is no, keep the detail private and extract only the generic design rule.

## Safe extraction patterns

### Convert an incident into a fixture

Instead of copying a private incident:

- create a fictional note such as `examples/vault/Projects/move.md`;
- use fake people like `Alex`, fake addresses like `1 Example Street`, and fake message IDs like `msg_example_001`;
- encode the invariant in a test name and assertion.

Example invariant:

> A stale daily-note task must not surface as currently open after a later correction says it was resolved unless a fresh source reactivates it.

### Convert a private script into an API contract

If a private script directly queries a live database or mutates a local service, upstream a safer public API instead:

- add a CLI command with `--dry-run` where possible;
- use temp SQLite databases in tests;
- keep JSON input/output stable;
- return structured errors instead of tracebacks;
- document what the private deployment must provide externally.

### Convert a private source path into a configuration placeholder

Use placeholders such as:

```text
/path/to/vault
/path/to/mneme.sqlite
/path/to/output
```

Do not commit private home-directory paths or service unit names.

## Mandatory privacy gate before commit

Run the public gate from the repository root:

```bash
python -m pytest -q
python scripts/privacy_scan.py
bash -n scripts/install.sh
mneme run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out
find . -path ./.git -prune -o \( -name '*.sqlite*' -o -name 'thought_*.svg' -o -name 'thought_*.png' -o -name '*.pyc' -o -name '__pycache__' -o -name out \) -print
```

The `find` command should show only disposable/generated artifacts that you then remove before committing.

If a private deployment needs additional forbidden words, pass them through the environment rather than storing them in the repo:

```bash
MNEME_FORBIDDEN_TERMS='PrivateName,private-domain.example' python scripts/privacy_scan.py
```

## What not to upstream

Do not upstream:

- private skill text copied verbatim;
- private cron prompts or platform message templates containing real context;
- generated SQLite/card/log artifacts;
- live-source queries with real addresses, dates, message IDs, or account details;
- service restart instructions for a specific host;
- private DB surgery snippets unless rewritten as audited public commands/tests.

## Public sync workflow

1. Inspect public philosophy: `README.md`, `GRAPH_CONTRACT.md`, `CONTRIBUTING.md`, and relevant tests.
2. Inspect the private runtime/skill for lessons, grouping them as:
   - safe generic mechanics;
   - private-only operational facts;
   - risky/sensitive material.
3. Choose the smallest public change that preserves the lesson.
4. Write docs/tests/code using fictional fixtures and placeholder paths.
5. Run the privacy/test gate.
6. Review the diff for private terms before pushing.
7. Watch CI after pushing.

The goal is to keep public Mneme honest to the private dogfood experience without turning a public repo into a shadow copy of a private life-admin system.
