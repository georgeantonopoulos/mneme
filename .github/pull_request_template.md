## Summary

-

## Test plan

- [ ] `python -m pytest -q`
- [ ] `mneme run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out`
- [ ] `python scripts/privacy_scan.py`

## Privacy checklist

- [ ] No real vault content
- [ ] No generated databases/cards from private notes
- [ ] No secrets, tokens, or credentials
- [ ] No private names, emails, paths, IDs, or project-specific examples
