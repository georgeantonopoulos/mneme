# Mneme

![Mneme — graph memory for AI agents](assets/mneme-header.png)

**Mneme** is a small graph-based memory layer for AI agents.

It turns a folder of Markdown notes into a local SQLite graph, walks that graph, and renders compact visual **thought path** cards that an agent can surface proactively.

> Mneme (Μνήμη) means memory.

## What it does

- Ingests Markdown notes from a vault/folder
- Extracts notes, wikilinks, headings, tasks, dates, emails, and high-signal observations
- Stores nodes, edges, observations, and generated thoughts in SQLite
- Performs biased graph walks over unresolved, risky, recent, or connected items
- Renders a thought card as SVG, with optional PNG conversion via ImageMagick
- Provides a CLI suitable for cron jobs or agent runtimes

## Install

```bash
git clone https://github.com/<owner>/mneme.git
cd mneme
python -m pip install -e .
```

## Quick start

```bash
mneme run-once --vault ./examples/vault --db ./mneme.sqlite --out ./out
```

The command prints JSON with the generated title, path, and image path. Agent runtimes can use that image as a proactive visual memory nudge.

## Privacy model

Mneme is local-first:

- No network calls
- No telemetry
- No LLM dependency
- No cloud database
- SQLite stays wherever you put it

Do **not** commit generated databases, private cards, or real vault content to public repositories.

## Status

Phase 1 prototype. Next improvements: configurable ontologies, contradiction detection, stale open-loop detection, semantic traversal, richer render themes, and agent framework adapters.
