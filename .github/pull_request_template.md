## Summary

-

## Test plan

- [ ] `python -m pytest -q`
- [ ] `mneme run-once --vault ./examples/vault --db /tmp/mneme_smoke.sqlite --out /tmp/mneme_smoke_out`
- [ ] `mneme contract check --db /tmp/mneme_smoke.sqlite`
- [ ] `python scripts/privacy_scan.py`

## Mneme contract checklist

- [ ] Active semantic edges require explicit evidence and validation.
- [ ] Candidate edges remain tentative in retrieval, surface, and thoughts.
- [ ] Killed edges cannot be resurrected by ingest, update, promote, or remember.
- [ ] Feedback weakens by default and kills only false relationships.
- [ ] Old open loops require fresh source evidence before being treated as live.
- [ ] Agent-facing outputs include `truth_policy` and contract metadata.

## Privacy checklist

- [ ] No real vault content
- [ ] No generated databases/cards from private notes
- [ ] No secrets, tokens, or credentials
- [ ] No private names, emails, paths, IDs, or project-specific examples
