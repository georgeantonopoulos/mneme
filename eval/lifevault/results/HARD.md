# Hard questions, repeated runs

```bash
python eval/lifevault/run_hard.py     # replays cached answers -> results/hard.json
```

There are 30 new questions in `hard.py`. Each was written and committed before any system saw it, and
checked so that every accepted answer string appears in its evidence memories. They aim at what earlier evals
found hard:
- answers spread over many memories (lists, totals, deadlines across storylines);
- multi-hop links;
- long-tail details buried in long notes;
- "as of" questions about past states.

The cortex recall was run 3 times per system, each run with its own answer cache. Perception and the
dev-feedback phase are shared, so the runs differ only in the mind's recall choices.

## Results (top 8, Haiku mind)

| System | Runs | answer-in-context, mean [min-max] | hit@8 | evidence recall | right in every run / some runs / no run |
|---|---|---|---|---|---|
| bm25 | 1 | 0.77 | 0.87 | 0.67 | 23 / 0 / 7 |
| **cortex, fresh** | 3 | **0.94** [0.93-0.97] | **1.00** | **0.85** | **28 / 1 / 1** |
| cortex, with experience | 3 | 0.92 [0.90-0.93] | 0.98 | 0.84 | 27 / 1 / 2 |

- **Run-to-run variance is small.** Fresh runs differ by one question, and 28 of 30 questions came out the
  same in all three runs. Earlier single-run differences of one or two questions were in that range.
- **The cortex beats BM25 on the questions keyword search can't answer:**
  - lists and totals spread across memories (`hd-01`, `hd-02`, `hd-04`);
  - a past state (`hd-27`, the physio date as of 2 October);
  - a detail phrased differently from the question (`hd-16`, the painkiller).

  BM25 got nothing the fresh cortex missed.
- **Experience did not help.** The brain with confirmed dev feedback scored slightly lower in every run.
  Its best run equals the fresh brain's worst. Twice it returned no evidence at all, for `hd-03` and `hd-23`.
  This matches `USE.md`: leads help a reworded question find its original, but they add nothing for new
  questions, and they cost about 24% more prompt tokens.

## What is still hard

Two questions fail in nearly every run of both systems. Both are broad questions whose answer spans
several storylines:

- `hd-03` "What deadlines do I have in the first half of November?" The deadlines sit in four areas
  (school, pottery, tax, car). Recall found about two thirds of the evidence.
- `hd-07` "Who is supposed to get back to me about something?" The answer covers the Halcyon invoice, the
  deposit dispute and the boiler part. Recall found the boiler every time, and the other two at most once.

The same pattern explains `loop-01` and `agg-01` in the dev set. Top-down recall zooms into at most 3
areas and 4 topics, so a question that needs one memory from each of five topics loses some of them. This
is the clearest remaining weakness, and it is structural, not noise.

## Caveats

- 30 questions written by the vault's author, 3 runs per system. A difference of one question is noise.
  The two failures above held in at least 5 of 6 runs.
- These questions turned out less hard for the cortex than intended: fresh scores 0.94. They are hard
  for BM25.
- The sub-agents had file access. In the first round, two agents listed the outbox folder and read prompts
  outside their batch. Prompts hold no answers, and they wrote nothing for them. Later rounds forbade
  directory listings.

## Tried and reverted: broad recall

Change (commit 72efe57, reverted):
- for questions asking for a list, a total, or all of something, the mind could choose every relevant area
  and up to 8 topics;
- the candidate pool took each chosen topic's newest memories in turn.

It was aimed at `hd-03` and `hd-07`. It was measured on this set (3 runs) and on the 81 dev and held-out
questions. Every prompt was asked afresh.

| | before | broad recall |
|---|---|---|
| hard, answer-in-context mean [min-max] | **0.94** [0.93-0.97] | 0.90 [0.87-0.93] |
| hard, right in every run / some / none | **28 / 1 / 1** | 24 / 5 / 1 |
| dev answer-in-context | **0.92** | 0.90 |
| held-out answer-in-context | **0.96** | 0.92 |
| recall prompt tokens per question | 4,772 | 4,802 |

- **Gained:** `hd-03` (November deadlines) passed in 2 of 3 runs instead of 1.
- **Not fixed:** `hd-07` ("Who is supposed to get back to me?") still failed in every run. The mind now
  routed to 6-7 topics, covering the invoice and the deposit, but the evidence it chose was still mostly the
  boiler. Its notes treat the unpaid invoice and the deposit decision as not "someone getting back to me",
  so the miss looks like interpretation rather than routing. This is not verified memory by memory.
- **Lost:** specific questions became less stable.
  - `hd-22` (Kestrel accent colour) failed in 2 of 3 runs.
  - `hd-06`, `hd-23` and `hd-27` each failed once.
  - In the dev and held-out sets, `para-01`, `h-01` and `hop-03` were lost and `h-24` was gained.

  Several losses were empty answers. Once breadth was allowed, the skim saw a differently ordered and
  wider pool and opened nothing.

Net, broad recall cost about 1 question in 25 and fixed half of one, so it was reverted.
