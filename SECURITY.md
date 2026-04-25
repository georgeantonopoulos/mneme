# Security Policy

## Supported versions

Mneme is pre-1.0. Security fixes will target the latest `main` branch unless release branches are introduced later.

## Reporting a vulnerability

Please open a private security advisory on GitHub or contact the maintainers through GitHub.

Do not include private vault data in reports. If a reproduction is needed, create a minimal fake Markdown vault.

## Security model

Mneme is local-first:

- no telemetry
- no required network calls
- no hosted database
- no LLM dependency

The main risk is accidental publication of private knowledge-base content. Use `scripts/privacy_scan.py` and keep generated databases/cards out of git.
