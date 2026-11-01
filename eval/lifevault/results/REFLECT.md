# Reflection: what the brain raises, retires and connects while idle

```bash
python eval/lifevault/run_reflect.py     # replays cached answers -> results/reflect.json
```

`Brain.reflect()` runs one idle pass:
1. The mind reads the area and topic summaries plus memories that are new since the last pass, and
   proposes thoughts. Each thought cites the neurons it rests on.
2. Each proposed thought is checked against the full text of the neurons it cites and their linked
   neighbours. It is kept only if it is supported and still unresolved.
3. Open thoughts that have since been resolved are retired.
4. For up to 4 topic pairs the mind suspects are related, it reads both sides and adds `reflect` synapses.
   A synapse is kept only if it joins a neuron on each side.

Dismissed thoughts are inhibited: they are passed to later reflections as "quiet" for 14 days.

The answer key is `proactive.py`, committed before any reflection code existed. Each of 3 runs reflected at
the act-1 moment (29 Oct), then learned act 2 and reflected again at 12 Nov, with its act-1 thoughts still
open.

## Results (Haiku mind, 3 runs)

| | run 1 | run 2 | run 3 | mean |
|---|---|---|---|---|
| act 1: items raised, of 9 | 7 | 8 | 8 | **85%** |
| act 1: thoughts kept / resolved items raised | 7 / 0 | 7 / 0 | 7 / 0 | **0 stale** |
| act 2: new items raised, of 5 | 4 | 4 | 4 | **80%** |
| act 2: act-1 thoughts retired | 4 | 5 | 5 | 4.7 |
| act 2: thoughts that were already past | 1 | 1 | 1 | 1 |
| gold links found, of 8 | 0 | 1 | 1 | 8% |
| new synapses made | 2 | 5 | 3 | 3.3 |

Cost per pass: about 16k prompt tokens in 12 calls (1 reflect, 6-8 checks, 3 connects).

### What works

- **Raising the right things.** Every run raised these act-1 items: the unpaid invoice, the permission slip,
  the Kestrel review, the boiler part, the accountant's documents, and the phishing warning. The misses were
  the stall fee and firing slots (run 1) and the 5-6 Nov clash (runs 2 and 3).
- **No resolved items raised at act 1.** The check step did most of the work here. In every run it dropped
  "update the insurance address", because a later memory showed it was done. It also corrected wrong
  details: an estimate credited to the wrong accountant, a detail not in the cited memories, and "tomorrow's
  payment run".
- **Keeping up.** At act 2, every run retired 4-5 of its 7 act-1 thoughts as resolved or past. No retired
  thought was raised again. Every run then raised the handoff moving to
  27 Nov, the pension statements, the £160 deposit award, and the firing slots now overdue.
- **Useful finds the key did not list.**
  - The 20 Nov calendar event still shows as confirmed after the handoff moved (all 3 runs).
  - Rhea's new email address appears only in a chat, while her latest email came from the old one.
  - Tom's £50 boiler credit has not shown up.
  - Mum's new operation date rests on a single chat message.

### What does not, yet

- **One past item stays open.** All 3 runs kept the "audit 2 Nov, review 3 Nov" thought open on 12 Nov,
  after both dates had passed. The scorer's stale patterns missed it, and also wrongly flagged as stale the
  thoughts that correctly point out the old 20 Nov event. The counts above are corrected by hand.
- **The corrected market dates (13-14 Dec) were never raised.**
- **Dreaming rarely finds the links that matter.** Only 1 of the 8 planted links appeared, in 2 runs: the
  insurance address and the flat move. Most new synapses are plausible but shallow: the phishing email and
  the real bank, Mum's visit and a Cheltenham train ticket. The mind proposes topic pairs from the
  summaries, and the planted links sit between topics whose summaries do not mention each other. Recall
  has not yet been checked with these synapses in place.

## Caveats

- 9 + 5 answer-key items and 8 links, written by the vault's author. Treat the percentages as direction.
- The scorer matches by cited evidence or key strings, and its stale patterns are crude, as noted above.
  Every thought from every run is in `results/reflect.json` for reading.
