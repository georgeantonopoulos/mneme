# LifeVault baseline

Retrieval-only scores for the current Mneme against a plain keyword-search baseline, on the 55 LifeVault
questions. Raw per-question results are in [`baseline.json`](baseline.json). Reproduce with:

```bash
python eval/lifevault/run_baseline.py
```

## Systems

- **mneme-retrieve/notes**: `mneme retrieve` (what the agent hook and `agent preflight` use) over the
  Markdown vault only. This is all Mneme can read today without the Gmail/Calendar connectors.
- **mneme-retrieve/all**: the same, with every email, calendar event, chat day and task rendered to Markdown
  so Mneme can see everything.
- **mneme-think/all**: the neural `mneme think` path over everything. Uses the offline hash embedder
  because Ollama is not available here, so this is a lower bound for `think`.
- **bm25/all**: about 150 lines of plain Okapi BM25 over small chunks (one email, event, task or chat day, or
  one note paragraph). No graph, no embeddings, no tuning.

All systems get the same budget: top k = 8 items.

## Results

| System | hit@3 | hit@8 | evidence recall@8 | MRR | answer in context@8 | p50 latency |
|---|---|---|---|---|---|---|
| mneme-retrieve/notes | 0.42 | 0.60 | 0.27 | 0.39 | 0.33 | 23 ms |
| mneme-retrieve/all | 0.46 | 0.64 | 0.34 | 0.42 | 0.31 | 39 ms |
| mneme-think/all (hash) | 0.48 | 0.58 | 0.29 | 0.43 | 0.26 | 26 ms |
| **bm25/all** | **0.60** | **0.73** | **0.52** | **0.46** | **0.65** | **0.2 ms** |

- **hit@k**: at least one gold evidence document is in the top k.
- **evidence recall**: the fraction of all gold evidence documents found.
- **answer in context**: the retrieved text contains the strings a correct answer needs. This is a proxy for
  "could an LLM answer from this context", graded on the 47 questions that have answer strings.

### By category (hit@8 / answer in context@8)

| Category | mneme-retrieve/notes | mneme-retrieve/all | mneme-think/all | bm25/all |
|---|---|---|---|---|
| abstention (near-miss premises) | 0.0 / 0.0 | 0.0 / 0.0 | 1.0 / 0.5 | 1.0 / 0.5 |
| aggregation | 0.67 / 0.0 | 0.67 / 0.0 | 0.0 / 0.0 | 0.67 / 0.0 |
| contradiction | 1.0 / 0.5 | 0.5 / 0.5 | 1.0 / 0.5 | 1.0 / 1.0 |
| entity disambiguation | 0.33 / 0.33 | 0.33 / 0.33 | 0.67 / 0.33 | 0.67 / 0.67 |
| exact token | 0.5 / 0.75 | 1.0 / 0.5 | 1.0 / 0.5 | 1.0 / 1.0 |
| historical state | 1.0 / 0.25 | 1.0 / 0.25 | 1.0 / 0.5 | 1.0 / 0.75 |
| implicit | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.5 / 0.5 |
| knowledge update | 0.75 / 0.38 | 0.88 / 0.38 | 0.5 / 0.38 | 0.75 / 0.62 |
| long tail | 1.0 / 0.5 | 1.0 / 0.5 | 0.5 / 0.0 | 1.0 / 1.0 |
| multi hop | 0.25 / 0.33 | 0.25 / 0.33 | 0.25 / 0.0 | 0.5 / 0.67 |
| open loops | 0.5 / 0.5 | 0.5 / 0.5 | 1.0 / 0.0 | 0.5 / 0.0 |
| paraphrase | 0.33 / 0.0 | 0.33 / 0.0 | 0.0 / 0.0 | 0.33 / 0.33 |
| preference | 1.0 / 0.5 | 1.0 / 0.5 | 0.5 / 0.0 | 0.5 / 0.5 |
| safety | 0.5 / 0.5 | 0.5 / 0.5 | 0.5 / 0.5 | 0.5 / 0.5 |
| single hop | 1.0 / 0.5 | 1.0 / 0.5 | 0.5 / 0.0 | 0.75 / 0.75 |
| temporal absolute | 1.0 / 0.5 | 1.0 / 0.5 | 1.0 / 0.5 | 1.0 / 1.0 |
| temporal relative | 0.0 / 0.0 | 0.0 / 0.0 | 0.67 / 0.33 | 0.67 / 1.0 |

Most categories have only 2-4 questions, so read single cells as anecdotes and the totals as the signal.

## What this says

1. **Plain BM25 beats every Mneme mode on every headline metric**, at about a hundredth of the latency. This
   matches the literature in [`docs/research/brain-memory-survey.md`](../../../docs/research/brain-memory-survey.md):
   good chunking plus lexical or hybrid search is the bar to clear.
2. **Mneme often finds the right document but not the right line.** Its hit@8 (0.64) is not far behind
   BM25 (0.73), but answer-in-context is half (0.31 vs 0.65). Causes seen in the per-question output:
   - Only lines containing trigger words ("waiting", "due", "need"...) become observations, so plain facts
     ("Flowline found a failed diverter valve", "movers cost £280") are invisible.
   - The same snippet is often returned twice (observation plus edge), wasting slots.
   - Some queries return only 2-4 items.
   - Common words like "the" count as matches.
3. **More sources barely helped Mneme** (hit@8 0.60 → 0.64), while BM25 uses them fully. The ingest
   pipeline, not the data, is the bottleneck.
4. **Relative-time questions score zero for `mneme retrieve`**: "how many days between...", "before or after...".
5. **The phishing email was retrieved by both mneme-retrieve/all and BM25** for "What's my Northmoor online
   banking password?". Retrieval should be allowed to find it only when it is labelled untrusted; none of these
   systems labels it.
6. **No system can say "I don't know".** Every system returns something for the three pure abstention questions
   (dentist, ballet recital, password). Those questions are not scored here; they need an answer step.

## Caveats

- Retrieval only; no LLM writes answers. Answer-in-context is a string proxy and can both over- and under-count.
- The answer key was audited once for missing evidence and loose answer strings (see git history of
  `truth.py`), but it is still hand-written by one author.
- `think` ran with hash embeddings. With a real local embedding model it should do better on paraphrase
  questions; that run is still to do.
- Small question set (55). Good for direction, not for decimals.
