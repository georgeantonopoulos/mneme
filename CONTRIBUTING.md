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

## Commit style

Use conventional commits where practical:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `test:` tests
- `ci:` automation
- `chore:` maintenance
