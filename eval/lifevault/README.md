# LifeVault

A fictional, multi-source personal memory fixture for scoring Mneme (or any agent memory) on realistic questions.

Everything is invented. The persona is Nia Okafor, a freelance designer and single parent in Bristol, from
2026-05-01 to the fixture "now" of 2026-10-29. All email addresses use reserved `.example` domains.

## What's in it

| Source | Path | Notes |
|---|---|---|
| Notes | `data/vault/` | Markdown with frontmatter, wikilinks, tasks; projects, people, areas, meetings, archive, inbox, journal |
| Email | `data/sources/email/*.eml` | RFC 5322, threaded (`In-Reply-To`), attachments, sent/drafts, newsletters, spam, one HTML phishing email with hidden instructions |
| Calendar | `data/sources/calendar/nia.ics` | Includes cancelled and rescheduled events |
| Chat | `data/sources/chat/messages.jsonl` | WhatsApp-style, one message per line |
| Tasks | `data/sources/tasks/tasks.json` | To-do export with due and completed dates |
| Questions | `data/questions.json` | 55 gold questions with evidence refs |

Ten storylines create facts that change over time: a move date that slips, a negotiated rent, a client contact
who leaves, an accountant change, a cancelled job, rescheduled physio, a rebooked flight, a swapped custody
weekend. Noise (newsletters, receipts, filler journal days, archive notes) makes retrieval earn its answers.

## Question categories

single hop, multi hop, aggregation, temporal (absolute and relative), knowledge update, historical state
(`as_of`), contradiction, abstention, entity disambiguation (two "Sam"s, "Tom" = Tomasz), paraphrase,
exact token (booking refs, invoice numbers), preference, implicit, long tail, open loops, safety.

Each question lists `evidence` (refs a good system should retrieve), `accept`/`reject` strings for loose answer
grading, `forbidden` refs, `as_of`, and `abstain`. Ref formats: `email:<id>`, `note:<path>`,
`journal:<date>`, `event:<uid>`, `task:<id>`, `chat:<conversation>@<timestamp>`.

## Rebuild

```bash
python eval/lifevault/build.py          # regenerate data/
python eval/lifevault/build.py --check  # fail if data/ is stale
```

The build is deterministic. Edit `story.py` (storylines), `noise.py` (background) or `truth.py` (questions),
then rebuild; `truth.py` validates that every evidence ref exists.
