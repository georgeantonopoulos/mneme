# Learning eval: keeping up with new memories

Act 2 covers the two weeks after the original "now" (29 Oct to 12 Nov 2026). In that time:
- invoices get paid and the boiler is fixed;
- the dev handoff moves a second time;
- physio clears Nia to run, and the market dates are corrected;
- the deposit dispute is decided and Sam returns the book;
- two notes are edited;
- the user corrects the assistant in chat ("Rhea's email changed", "Mum's op moved to 2 February").

```bash
python eval/lifevault/build.py                # writes data/ (act 1) and data_act2/
python eval/lifevault/run_learning.py         # replays cached answers -> results/learning.json
```

Both systems start from the same act-1 brain, which was perceived once with Claude Haiku as the mind.
- **stale**: never updated. This is the no-learning floor.
- **incremental**: ingests `data_act2/` with `incremental=True`, then calls `perceive()` again.
  - New memories are added.
  - An edited note becomes a new version (`id~date`), and the old version is kept for "as of" questions.
  - Only new neurons are perceived, and only the gists of topics they touched are rewritten.
  - The region map is kept.

No prompts or code were changed for act 2. Recall is the same four-step zoom used in `CORTEX.md` v4.

## Results (top 8)

| System | act-2 answer-in-context | act-2 hit@8 | act-2 evidence recall | regression answer-in-context (10 unchanged act-1 questions) |
|---|---|---|---|---|
| stale | 0.44 | 0.38 | 0.24 | 1.00 |
| **incremental** | **1.00** | **1.00** | **0.94** | **1.00** |

By act-2 category (answer-in-context, stale → incremental):

| Category | Questions | stale | incremental |
|---|---|---|---|
| open loops that closed | 5 | 0.4 | 1.0 |
| facts that changed again | 5 | 0.2 | 1.0 |
| corrections given in chat | 2 | 0.0 | 1.0 |
| brand-new facts | 1 | 1.0* | 1.0 |
| history kept ("as of", "before I changed it") | 3 | 1.0 | 1.0 |

\*The stale score overstates what a brain without act 2 can know. Four of its seven "passes" are string
coincidences in act-1 text:
- `l-01`: the act-1 invoice says "£6,000" and an open task says "Check INV-2026-017 paid".
- `l-02`: the act-1 engineer's report says "bypass fitted".
- `n-01`: the teacher's note already mentioned reading and times tables.
- `c-04`: pension statements were owed in act 1 too.

On the gold-evidence measure (hit@8), stale gets none of the 13 questions about change. Its 0.38 is the 3
history questions plus 3 edited notes, which keep the same ref across versions. The incremental brain cited
the right act-2 memory for all 16.

## Cost of learning

| | Prompt tokens |
|---|---|
| Full perception of act 1 (402 memories) | 202k |
| **Incremental update for act 2** (23 new memories, 2 new note versions) | **37k (18%)** |

The update ran:
- 2 perceive batches, covering the 23 new neurons;
- 12 of 29 topic gists;
- 8 of 9 area gists.

Area gists are the main waste: one new memory in a topic marks its whole area dirty, and most areas got
one. The update happens once per batch of new memories, not once per question.

## What the mind noticed on its own

- **The user's correction beat the memory record.** "What's my accountant's email?" returned the 8 Nov chat
  correction (`rhea.k@…`). The mind also noted that Rhea's 9 Nov email still came from the old address.
  That is a real flaw in the fixture: the story sends that email from the address the user says bounces.
  The answer key does not depend on it.
- **History survived.** "As of 1 November, was the boiler fixed?" correctly said no (bypass, part
  awaited). "As of 31 October, when was the handoff?" said 20 November. The 4 Nov fix and the 12 Nov move
  were hidden by `as_of`.
- **Corrections in chat need no special path.** "Mum's op moved to 2 February" is an ordinary chat memory.
  Perception linked it to the hospital letter, and routing found it. Nothing in the core treats
  corrections specially.
- **Second fixture flaw.** Act 2 re-issues "Design Weekly #226", which act 1 already had. It is harmless
  noise, recorded here rather than fixed so that the cached answers stay valid.

## Caveats

- 16 act-2 questions and 10 regression questions, written by the author of the story. Treat the numbers as
  direction, not decimals.
- Each system ran once. The act-1 brain is shared and fully cached, so routing variance only affects the
  act-2 recall calls.
- Stale scores use the same string metric as the rest of the eval. As shown above, the metric is generous
  to a system that has seen only the "before" state.
- The sub-agents had file access. One opened six routing prompts outside its batch, which hold no answers.
  It wrote nothing for them. No agent read the questions, truth files or story source.
