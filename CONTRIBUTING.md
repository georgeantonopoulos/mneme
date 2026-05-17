# Contributing to Mneme

Thanks for considering a contribution.

## Development

```bash
python -m pip install -e .
python -m pytest -q
mneme run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out
python scripts/privacy_scan.py
```

## Privacy rules

Mneme is intended to process private knowledge bases locally, but the public repository must never contain private data.

Do not commit:

- real vault content
- generated SQLite databases
- generated thought cards from real notes
- access tokens, API keys, credentials, or secrets
- private names, emails, addresses, IDs, or project-specific examples
- local absolute paths from your machine

Use fake examples under `examples/`.

## Promoting private dogfood lessons

Mneme may be tested in private runtimes before patterns are promoted here. Promote reusable mechanics, not private memories. Before copying any private lesson into this repo, read [docs/PRIVATE_PUBLIC_DIVERGENCE.md](docs/PRIVATE_PUBLIC_DIVERGENCE.md) and convert the lesson into source-agnostic docs, code, or tests with fictional fixtures.

Safe public examples:

- a generic source-packet state machine;
- a contract test for candidate/killed edge behavior;
- a fictional stale-task fixture that proves freshness guardrails;
- placeholder paths such as `/path/to/vault`.

Unsafe public examples:

- real vault snippets, emails, calendar items, names, addresses, domains, or message IDs;
- generated SQLite databases, cards, logs, or transcripts;
- host-specific cron IDs, local service names, backup folder IDs, or secret locations.

## Commit style

Use conventional commits where practical:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `test:` tests
- `ci:` automation
- `chore:` maintenance
