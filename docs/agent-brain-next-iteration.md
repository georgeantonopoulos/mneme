# Mneme Agent Brain Next Iteration

This plan responds to GitHub issue #4: refactor Mneme around one sense-first
retrieval and scoring flow.

## Current Read

Mneme is already a cautious local memory substrate:

- Markdown vaults become SQLite `nodes`, `edges`, `observations`, `thoughts`,
  relationship types, and debug logs.
- Deterministic ingest keeps navigation, structure, extraction, and weak
  semantic edges as `candidate`.
- Source-contained observation edges can be `active`.
- Killed edges are tombstones and rebuilds preserve them.
- `candidates` and `thought` already rank open loops and deadlines, but the
  scoring is local to proactive thought generation.
- `physarum` can run topology experiments without changing edge status.
- `harness` gives a provider-neutral command seam for agent experiments.

The missing agent-brain layer is not another wrapper around an LLM. It is a
single audition loop that can answer:

1. What did Mneme sense?
2. Which memories are eligible to surface?
3. Why did each item score that way?
4. What was skipped, suppressed, or cooled down?
5. What context pack should an agent receive for this prompt right now?
6. What feedback should change future surfacing without rewriting history?

## Live Scale Probe

A local private test vault was used only as a read source. Generated artifacts were
written outside the repo and vault:

- DB: `$MNEME_TEST_DB`
- Thought output: `$MNEME_TEST_OUT/thought_YYYYMMDD_HHMMSS.svg`

Commands run:

```bash
uv run --with pytest pytest -q
uv run python -m mneme.cli ingest --vault "$MNEME_TEST_VAULT" --db "$MNEME_TEST_DB" --max-notes 250
uv run python -m mneme.cli candidates --db "$MNEME_TEST_DB" --limit 5 --hops 4
uv run python -m mneme.cli thought --db "$MNEME_TEST_DB" --out "$MNEME_TEST_OUT" --hops 4
uv run python -m mneme.cli physarum run --db "$MNEME_TEST_DB" --iterations 20 --terminals 16 --paths-per-iteration 6 --seed 17
```

Observed:

- Test suite passed: `40 passed in 0.42s`.
- Ingest read 249 notes and produced 804 nodes, 3,913 edges, and 325
  observations.
- Edge status split was 369 active and 3,544 candidate.
- Candidate output worked, but high-ranked results were dominated by copied run
  log text, weak freshness cues, and repeated hub-shaped references.
- Physarum reinforced 89 edges and safely preserved candidate status.

That makes issue #4 valuable: the system has useful raw material, but it needs
one retrieval/scoring path that is explainable, prompt-aware, and resistant to
run-log/hub noise.

## Target Loop

Make this the canonical internal flow:

```text
sense collect
  -> ingest_sense_events
  -> score_candidates
  -> surface
  -> retrieve
  -> feedback/explain
```

Legacy commands should call this flow:

- `ingest` becomes the Markdown sense collector plus event ingest.
- `update` becomes sense collection with graph rebuild preservation.
- `candidates` becomes a read-only view of `score_candidates`.
- `thought` becomes a sampled surface result rendered as a card.
- `run-once` becomes collect plus surface plus render.

The public CLI does not currently expose `sense`, `tick`, `surface`,
`feedback`, or `retrieve`. Add them gradually without breaking the existing
commands.

## Iteration 1: Shared Retrieval Core

Create a small retrieval package before splitting the rest of `core.py`:

```text
src/mneme/retrieval/
  __init__.py
  scoring.py
  query.py
  surface.py
  explain.py
```

First extraction:

- Move `_candidate_reasons()` and candidate ranking into
  `retrieval/scoring.py`.
- Return a structured score object:
  `total`, `factors`, `penalties`, `freshness`, `source_quality`, `reasons`,
  `skip_reasons`, `provenance`.
- Keep `list_thought_candidates()` behavior compatible by adapting the new
  score object back into the current JSON shape.
- Make `generate_proactive_thought()` consume the same scored candidates.

Acceptance:

- `mneme candidates` output remains compatible.
- `mneme thought` still renders.
- Existing tests stay green.
- New tests prove `candidates` and `thought` share one score function.

## Iteration 2: Query-Time Retrieve

Add the first public agent-brain command:

```bash
mneme retrieve --prompt "..." --budget 2500 --max-items 8 --json
```

V1 should be deterministic and local:

- lexical match over node names, source paths, observations, and evidence text;
- graph expansion around matches;
- scoring through the same retrieval core;
- budgeted evidence snippets;
- explicit `included`, `skipped`, and `why` sections;
- no network or model dependency.

Suggested JSON:

```json
{
  "prompt": "...",
  "budget": 2500,
  "items": [
    {
      "kind": "observation",
      "title": "...",
      "source_path": "...",
      "snippet": "...",
      "score": 12.4,
      "factors": [],
      "provenance": {}
    }
  ],
  "skipped": [],
  "stats": {}
}
```

Acceptance:

- Querying the example vault returns stable, source-backed context.
- Querying the test-vault-derived temp DB returns a compact pack without private
  generated artifacts entering the repo.
- Candidate semantic edges can appear only as candidates, not as facts.
- Killed edges never appear.

## Iteration 3: Freshness And Source Priors

Add a freshness resolver used by both `surface` and `retrieve`:

1. explicit due/deadline date in evidence;
2. sense event `observed_at`, once sense events exist;
3. source path date;
4. observation `created_at`;
5. unknown freshness with a small uncertainty penalty, not an oldness penalty.

Add configurable source priors:

```json
{
  "source_priors": {
    "task": 1.4,
    "calendar": 1.3,
    "email": 1.2,
    "markdown": 1.0,
    "session": 0.85,
    "archive": 0.65
  }
}
```

The live private-vault probe showed why this matters: archived run notes and hub
notes can be structurally prominent while being poor immediate context.

Acceptance:

- Unknown dates are not treated as stale by default.
- Archive/run-log material is still retrievable when directly relevant, but is
  not allowed to dominate generic surfacing.
- Tests cover old correction versus newer task chronology.

## Iteration 4: Explain Empty Or Suppressed Surfaces

Add one of these commands:

```bash
mneme debug-candidates --include-skipped --json
mneme tick --explain-skipped --json
```

It should show:

- score before and after penalties;
- freshness interpretation;
- source prior;
- guardrail reason;
- feedback/cooldown reason;
- candidate/active/killed status impact;
- source provenance.

Acceptance:

- Empty output is explainable without opening SQLite manually.
- A user can tell whether the problem is no data, low score, cooldown,
  tombstone, privacy guardrail, or budget pressure.

## Iteration 5: Feedback As Memory Pressure

Add a narrow feedback table before adding complex learning:

```text
retrieval_feedback(
  id,
  target_kind,
  target_id,
  action,
  reason,
  strength,
  created_at,
  expires_at
)
```

Start with these actions:

- `dismiss`: cooldown the item and lightly weaken related surfacing.
- `promote`: increase surfacing priority without changing truth status.
- `pin`: force inclusion in retrieve packs until expiry.
- `kill`: create or preserve a tombstone when the user says the relationship is
  wrong.

Acceptance:

- Feedback affects retrieval ranking.
- Feedback does not silently promote semantic truth.
- Tombstones remain stronger than future ingest.

## Test Database Policy

Use a private local vault as a scale and realism test, but keep it non-destructive:

- Read from `$MNEME_TEST_VAULT`.
- Write DBs and rendered cards to `$MNEME_TEST_OUT`.
- Never commit generated DBs, cards, JSON dumps, or private note snippets.
- Keep committed fixtures fictional.

Recommended smoke command:

```bash
uv run python -m mneme.cli ingest --vault "$MNEME_TEST_VAULT" --db "$MNEME_TEST_DB" --max-notes 250
```

## Definition Of Amazing

Mneme is an agent brain when it can hand an agent a compact, source-backed
context pack and say:

- this is why these memories matter now;
- this is what I skipped and why;
- this evidence is fresh, stale, or uncertain;
- this edge is a candidate, not a fact;
- this was suppressed because you already dismissed it;
- this relationship is killed and cannot be revived by re-ingest;
- here is the smallest next action the agent can take.

That is the line between a graph database and a useful working memory.
