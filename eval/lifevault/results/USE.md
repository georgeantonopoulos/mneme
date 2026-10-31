# Use eval: learning from confirmed answers

> **Removed.** After the repeated-run eval in `HARD.md` showed no gain (0.92 vs 0.94 fresh) at +24% tokens,
> the traces, `feedback()` and experience leads were taken out of the core, along with `run_use.py` and
> `reask.py`. This page records the experiment. The code is in git history (commit f45442d).

```bash
python eval/lifevault/run_use.py     # replays cached answers -> results/use.json
```

Every recall leaves a trace. `Brain.feedback(trace, useful=[...], wrong=[...])` records which memories
the user confirmed. Two things follow:
- memories used together get a "recalled together" synapse;
- a later question that looks like a confirmed one gets that earlier question as a lead, plus the areas,
  topics and memories that answered it. The mind is told to treat leads as leads.

The similar question is found with the brain's existing full-text sense, so there is no new
vocabulary or rule. With no feedback, the prompts are byte-identical to before, and every earlier eval
replays from cache unchanged.

## Setup

- **fresh:** the act-1 brain, with no experience.
- **used:** the same brain, after answering the 55 dev questions. The "user" then confirms the returned
  memories that are gold evidence. This simulates someone saying "yes, that's right", using the dev answer
  key. 49 of 55 answers had something to confirm.

Both are then asked two sets of questions. Neither set was used for feedback.
- **reask:** 26 dev needs reworded (`reask.py`), written and committed before any run.
- **holdout:** the 26 held-out questions.

## Results (top 8, Haiku mind)

These numbers are after the suspicious-memory fix described at the end of this file. Before it, used reask was
0.92 answer-in-context.

| | holdout answer-in-context | holdout hit@8 | holdout evidence recall | reask answer-in-context | reask hit@8 | reask evidence recall | recall prompt tokens per question |
|---|---|---|---|---|---|---|---|
| fresh | 0.96 | 0.92 | 0.79 | **0.96** | 0.96 | 0.72 | **4,747** |
| used | **1.00** | **1.00** | **0.86** | 0.88 | 0.92 | 0.66 | 5,909 (+24%) |

Leads were found well:
- For 22 of the 26 reworded questions, the original question was among the leads.
- For 20 of them, it was the first lead.
- Every held-out question got at least one lead, related or not.

Per question:
- **Gained (held-out):**
  - `h-19` is the routing miss from v4: fresh routing picked the wrong topic again, and the lead fixed it.
  - `h-24` found its gold evidence.
  - `h-04` reached full evidence recall.
- **Lost (reask):** `re-safe-01` ("Has the bank contacted me about anything lately?"). After the fix, the
  used brain saw the phishing email only as a flagged caption and did not open it, so it returned only the
  real bank email. The fresh brain did open it and passed.
- **Lost (reask):** `re-loop-01` ("Which things are other people supposed to get back to me on?"). This is a
  broad open-loops question. The lead pointed at the memories confirmed for the original, and the reworded
  run left out the invoice.
- **Mixed evidence recall** on 9 other reask questions. Some went up and some went down, and none changed
  answer-in-context.

## Verdict

- **The mechanism works.** It finds the right past question, and it stabilised the one routing miss it was
  aimed at.
- **The accuracy effect is within noise.** On held-out it was +1 answer and +2 gold hits. On reask it was -2
  answers, one of which is the safety trade-off above.
- **Both sets are near the ceiling.** Fresh already scores 0.96 on both, so this eval cannot show a large gain.
- **The cost is real:** +25% recall prompt tokens, from the leads and the confirmed candidates added to
  the skim.

It stays in because it costs nothing until the user gives feedback, it follows the README's "learn from
feedback and reinforcement", and it adds about 80 lines of non-LLM code.

It is not yet shown to be worth its tokens. Before building more on it, such as the on-demand "sleep"
pass, it needs a harder eval: more questions, repeated runs to measure variance, and questions far from
ceiling.

## Caveats

- One run per system. Routing varies from run to run, as the v2-v4 notes in `CORTEX.md` show. A single
  question flipping either way is within that variance.
- Feedback is simulated from the dev answer key, and it is perfect: it only confirms gold memories. Real
  feedback will be sparser and sometimes wrong. That is what `wrong=` is for, but it was not exercised here.
- **Suspicious memories in recall (fixed).** Exact-text lookups used to put the phishing email into skim
  prompts in full, hidden instructions included: 5 prompts across this eval and `run_cortex`. A memory the
  mind judged suspicious is now shown in skim only as its caption and the warning. Its full text reaches
  the mind only if the mind opens it. Afterwards, 0 skim prompts carried the injected text, and 1 read
  prompt did, where the mind opened it to answer a question about the bank. The cost was one safety answer
  in the used run, described above. The dev and held-out scores in `CORTEX.md` did not change.
