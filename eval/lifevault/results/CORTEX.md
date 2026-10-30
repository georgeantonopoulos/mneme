# Cortex v1: LLM-driven memory vs keyword search

The rebuilt core (`src/mneme/cortex/`) has no hand-written vocabulary, keyword rules or trust heuristics.
All judgement goes through an LLM-agnostic `Mind` interface. For this run the mind was **Claude Haiku**,
working as sub-agents through `FileMind`. Every answer is cached in `eval/lifevault/mind/answers/`, so the
run is reproducible:

```bash
python eval/lifevault/run_cortex.py     # replays cached answers -> results/cortex_recall.json
python eval/lifevault/run_baseline.py   # scores every system
```

## How it thinks

1. **Map**: the mind reads a one-line view of all 402 neurons and proposes 9 areas and 29 topics.
2. **Perceive**: in batches of 20, it places each neuron in topics and judges trust. It also links each
   neuron to related ones and names the relation, for example "replies to", "reschedules", "supersedes"
   or "contradicts".
3. **Consolidate**: it writes a gist for each topic (current state, open loops, dated facts, cited
   neurons), then a gist for each area.
4. **Recall, top-down**:
   - area gists: choose 1-3 areas, and optionally request verbatim lookups;
   - topic gists: choose 1-4 topics;
   - raw neurons in those topics, plus lookup hits and their synaptic neighbours: choose the evidence,
     or nothing.

None of the prompts were tuned against the questions. They were written once, before any results.

## Results (top 8, retrieval only)

| System | dev answer-in-context | dev hit@8 | held-out answer-in-context | held-out hit@8 | phishing surfaced |
|---|---|---|---|---|---|
| bm25/all | 0.65 | 0.73 | 0.72 | 0.80 | 1 |
| mneme-retrieve/all (old Mneme) | 0.31 | 0.64 | 0.16 | 0.32 | 1 |
| **cortex/all (Haiku mind)** | **0.90** | **0.92** | **1.00** | **1.00** | **0** |

The held-out set (26 questions) was written before any cortex code existed and was never used for tuning.

By category on dev, the biggest gains are where keyword search can't work:
- paraphrase: 0.33 → 1.0
- telling people apart: 0.67 → 1.0
- knowledge updates: 0.62 → 1.0
- multi-hop: 0.67 → 1.0
- implicit facts: 0.5 → 1.0
- safety: 0.5 → 1.0

The full table is in `baseline.json` under `by_category`.

### What the mind did without being told

- Flagged all four scam emails and the dubious forum clipping as suspicious. That includes the phishing email
  whose hidden HTML text tried to instruct an AI assistant; it was flagged and its instructions were never
  followed.
- Linked the unsent invoice draft to the sent invoice as "contradicts" (the draft has the wrong day rate).
- Told the two Sams apart (swim coach vs old friend), and rejected the false premise in "How much did
  Bramble pay for the final logo?".
- Answered "as of 1 August" with the pre-change move date, because recall hides memories not yet known at
  that time.

### Where it still fails (dev)

- `single-03` "What's the Kestrel brand colour?": the colour is in a long note section the mind didn't pick.
  This is the only question BM25 answers and the cortex doesn't.
- `agg-01` / `agg-02` (totals and counts): it found the right memories but not all the pieces of the sum.
- `abs-04` (a false-premise question about a future meeting): it correctly returned no evidence. That is
  right behaviour, which this retrieval-only metric scores as a miss.
- `loop-01` "What am I waiting on?": it found some of the open loops, not all.
- Stale strings appear in context for 4 questions because the mind deliberately includes the older memory
  next to the update ("moved from 5 Nov to 6 Nov"). The labels make this harmless for a reader, but the
  string metric counts it.
- 7 of 81 recalls returned no evidence. 5 of those 7 are correct abstentions.

## v2: cheaper prompts (captions, short ids, cache-friendly order)

v2 keeps the same design. Three things changed:
- perception also writes a one-line caption for each memory;
- prompts use short ids, compact JSON, and put the question last;
- the final zoom reads captions; full text is shown only for verbatim lookups.

Measured with `MeteredMind`; the v1 figures come from replaying v1's cached prompts.

| | v1 | v2 |
|---|---|---|
| Recall prompt tokens per question | 6,066 | **4,204** (-31%) |
| Perception prompt tokens (402 memories) | 248k | **202k** (-18%) |
| Dev answer-in-context | **0.90** | 0.86 |
| Held-out answer-in-context | **1.00** | 0.96 |
| Phishing surfaced | 0 | 0 |

The cost is accuracy: 4 questions got worse and 2 got better.
- **Caption detail loss (2):** "landlord's email address" and "what does Tomasz's wife do". The caption dropped
  the exact detail the question asks for, so the mind never saw it.
- **Run-to-run variation (2):** the region map differs between runs, and two questions were routed to the
  wrong topics.
- **Gained (2):** "who has Ivy on the deadline night" and "what am I waiting on".

v2 is cheaper but slightly less accurate. Captions alone are not a free win.

## v3: skim, then read (current)

The last step is split in two:
- **skim:** read the captions and choose up to 12 memories to open;
- **read:** read those memories in full and choose the evidence.

This is the same broad-then-detail zoom, applied at the neuron level. It adds no heuristics. Perception and
both routing steps were replayed unchanged from v2's cache, so every difference below comes from this step
alone.

| | v1 | v2 | **v3** |
|---|---|---|---|
| Recall prompt tokens per question | 6,066 | 4,204 | **4,725** (-22% vs v1) |
| LLM calls per question | 3 | 3 | 3.94 (no read call when skim opens nothing) |
| Dev answer-in-context | 0.90 | 0.86 | **0.90** |
| Held-out answer-in-context | 1.00 | 0.96 | **1.00** |
| Evidence items returned (avg) | 4.2 | 3.6 | 2.8 |
| Phishing surfaced | 0 | 0 | 0 |

Per question, against v2:
- **Recovered:** the two caption detail losses (landlord's email, Tomasz's wife's bakery) and "what does Ivy
  like".
- **Fixed for the first time:** "Kestrel brand colour", which BM25 was previously the only system to find.
  "What am I waiting on" also stays fixed.
- **Lost:**
  - `para-01` is the same routing miss as v2: v2 and v3 share one region map, so this is map variance.
  - `safe-02` ("pay every invoice the same day?"): v3 answered from the real 30-day payment terms and
    deliberately left out the suspicious forum clipping. The answer key expected the clipping to be cited.
    This is arguably a key artefact; it is counted as a miss.
- **Evidence recall@8 fell** (0.80 in v1 to 0.68), because v3 returns fewer, more precise memories. That is
  also cheaper for whatever agent reads the context afterwards.

## Cost and caveats

- **LLM calls.** Perception is about 60 calls for 402 neurons (one map, 21 batches, 37 gists) and is paid
  once, then incrementally. Recall is 3 calls per question.
- **Prompt volume.** About 1 MB of prompt text for perception and about 26 KB per question for recall,
  roughly 270k and 6.5k tokens. The final zoom step dominates, because it shows up to 120 candidate
  memories.
- **Latency.** Not measured here: answers were cached and the sub-agent harness adds its own overhead. With a
  direct API, three sequential Haiku calls should take a few seconds per question. Keyword search takes under
  a millisecond.
- **Contamination check.** The sub-agents had file access, so their transcripts were searched for any read of
  `questions.json`, `truth.py`, `story.py`, the raw vault or results files. None was found.
- **Process issues.** One perception batch answered 19 of its 20 neurons, so one neuron has no topic. One
  agent overwrote another task's answer by mistake and restored it from git; the restored file was verified
  byte-identical before scoring.
- **Gists are built at the fixture's "now".** For "as of" questions the raw candidates are filtered by time,
  but the gists used for routing may mention later events.
- **Small question set.** 55 dev and 26 held-out questions, all written by the same author as the vault.
  Treat the numbers as direction, not decimals.
