"""Act 2 of the LifeVault fixture: the two weeks after the original "now".

Act 2 tests learning, not first-time recall. New memories arrive, notes are
edited, open loops close, facts change again, and the user corrects the
assistant in conversation. A memory system should absorb this incrementally
and answer questions about the new state, without forgetting the old one
(``as_of`` questions) or regressing on things that did not change.

``apply()`` mutates the act-1 collections in ``story`` in place, so act 2 is
always act 1 plus these events. All content is fictional.
"""
from __future__ import annotations

import story
from story import chat, email, event, journal, task

NOW = "2026-11-12T18:00:00+00:00"

# Notes whose text changes in act 2: path -> (updated date, new body).
NOTE_EDITS: dict[str, tuple[str, str]] = {}


def _edit(path: str, updated: str, body: str) -> None:
    NOTE_EDITS[path] = (updated, body.strip("\n"))


def _apply_note_edits() -> None:
    for note in story.NOTES:
        if note["path"] in NOTE_EDITS:
            note["updated"], note["body"] = NOTE_EDITS[note["path"]]


def apply() -> None:
    # Invoice INV-2026-017 is paid.
    email("a2-001", "2026-10-30T08:00", "bank", "Payment received: £6,000.00",
          "A payment of £6,000.00 from HALCYON LABS LTD has been credited to your account ending 4471.")
    task("a2-t-hl", "Confirm INV-2026-017 received", "2026-10-30", completed="2026-10-30", project="Halcyon")

    # Boiler fixed.
    chat("2026-11-02T09:10", "Tom (landlord)", "Tom", "Part's arrived! Flowline will fit it Wednesday 4th, 9am")
    chat("2026-11-04T12:30", "Tom (landlord)", "Tom", "Engineer says all done, new diverter valve in. Shout if any problems")
    chat("2026-11-04T12:41", "Tom (landlord)", "Nia", "Hot water is back. Thank you Tom!")
    journal("2026-11-04", "HOT WATER. First proper shower in two weeks. Ivy did a dance.")

    # School: slip paid, parents' evening, trip.
    task("a2-t-iv", "Pay museum trip £12 (done on ParentPay)", "2026-11-02", completed="2026-11-02", project="Ivy")
    journal("2026-11-05", "Parents' evening with Ms Adeyemi: Ivy's times tables much better since half term, "
                          "reading is excellent, she should try the school chess club.")
    journal("2026-11-10", "Ivy back from the Harbour Museum trip, full of facts about ship rats.")

    # Physio review: cleared to run.
    email("a2-002", "2026-11-06T10:15", "helen", "Review summary", """
Hi Nia,

Good news from today: you're cleared to start a return-to-run programme.
Three easy runs a week, 10 minutes each, flat routes only - no hills until December.
Keep the Spanish squats and step-downs going. Next check in 6 weeks (18 December).

Helen
""", thread="kn-review")
    event("ev-a2-physio", "2026-12-18T08:15", "2026-12-18T09:00", "Physio check - Helen", location="Northgate Physio", created="2026-11-06")

    # Christmas market: dates corrected, fee paid.
    email("a2-003", "2026-11-06T16:00", "Harbourside Makers Market <stalls@harboursidemakers.example>",
          "Correction to market dates + fee received", """
Apologies - our acceptance email had the wrong dates. The Christmas Makers Market runs Sunday 13 and
Monday 14 December (not 12-13). Your stall fee of £45 has been received, thank you. Setup from 8am.
""", thread="pt-market")

    # Accountant: partly done.
    email("a2-004", "2026-11-09T11:00", "rhea", "Re: Welcome - your 2025-26 return", """
Thanks Nia - got the P60 and the expenses spreadsheet. I still need your pension contribution statements
before I can finish. No rush before the 15th, but the sooner the better.
""", thread="tx-rhea")

    # Deposit dispute decided.
    email("a2-005", "2026-11-10T09:30", "depositguard", "Adjudication decision: case DG-58213", """
The adjudicator has reached a decision on case DG-58213 (disputed amount £240).
Awarded to tenant: £160. Awarded to landlord: £80 (oven cleaning only).
Payment of £160 will be made within 10 working days.
""", thread="mv-dg")

    # Book returned.
    chat("2026-11-11T19:20", "Sam", "Sam", "The Salt Orchard is in your letterbox!! sorry it took 5 months")
    chat("2026-11-11T19:25", "Sam", "Nia", "Got it! Forgiven")

    # Handoff moves a second time.
    email("a2-006", "2026-11-12T10:05", "daniel", "Handoff date (again)", """
Nia - Lukas is off sick for the next week, so let's move the dev handoff from 20 November to Friday
27 November. Sorry for the shuffle. Everything else stays as planned.
""", thread="hl-handoff")
    event("ev-a2-handoff", "2026-11-27", "2026-11-28", "Kestrel dev handoff", created="2026-11-12", all_day=True)

    # The user corrects the assistant in conversation; corrections are just memories.
    chat("2026-11-08T21:02", "Assistant", "Nia", "Note for later: Rhea's email changed - it's rhea.k@ledgerline.example now, the old one bounces")
    chat("2026-11-08T21:02", "Assistant", "Assistant", "Noted: Rhea Kapoor's email is now rhea.k@ledgerline.example.")
    chat("2026-11-09T08:40", "Assistant", "Nia", "Also Mum's hip operation has been moved to 2 February, not 19 January")
    chat("2026-11-09T08:40", "Assistant", "Assistant", "Noted: Grace's hip operation moved to 2 February 2027.")

    # Background noise keeps arriving.
    for i, day in enumerate(["2026-11-02", "2026-11-09"]):
        email(f"a2-nl-{i}", f"{day}T07:00", "Design Weekly <digest@designweekly.example>", f"Design Weekly #{226 + i}: motion and accessibility",
              "This week: motion and accessibility. Plus jobs, links and a tool of the week.", labels=["newsletter"])
    journal("2026-11-07", "Slow Saturday. Threw eight mug bodies for the market.")

    # Notes the user edited in act 2.
    _edit("Projects/Flat Move.md", "2026-11-10", """
# Flat Move

Current home: Flat 3, 22 Alder Street, Bristol (landlord [[Tomasz Wren]]). Moved in 2026-09-15.

## Log
- 2026-07-10 offer accepted; 2026-07-28 rent negotiated to £1,425
- 2026-09-15 moved in
- 2026-10-18 boiler died; 2026-10-21 temporary bypass; 2026-11-04 new diverter valve fitted - FIXED
- 2026-11-10 DepositGuard decision: £160 back to me, £80 to the old landlord for the oven

## Open
- [x] Chase Tomasz about boiler part ETA
- [x] Get the deposit deduction decided (DG-58213) - partial win
- [x] Change address on car insurance before renewal
""")
    _edit("Health/Knee Rehab.md", "2026-11-06", """
# Knee Rehab

Left knee, patellofemoral pain after the half marathon in April. Physio: [[Helen Marsh]].

## Status (6 Nov review)
- Cleared to run again: 3 x 10 minute easy runs a week, flat routes only, no hills until December
- Keep Spanish squats and step-downs
- Next check 2026-12-18
""")
    _apply_note_edits()


QUESTIONS_SPEC: list[dict] = []


def _q(qid, category, question, answer, *, evidence, accept=None, reject=None, as_of=NOW, abstain=False):
    QUESTIONS_SPEC.append({"id": qid, "split": "act2", "category": category, "question": question, "answer": answer,
                           "evidence": evidence, "accept": accept or [], "reject": reject or [], "forbidden": [],
                           "as_of": as_of, "abstain": abstain, "note": ""})


def questions() -> list[dict]:
    """Questions asked at the end of act 2 (plus two 'as of' questions inside it)."""
    QUESTIONS_SPEC.clear()
    # Open loops that closed.
    _q("l-01", "loop_closed", "Has INV-2026-017 been paid?", "Yes - £6,000 received on 30 Oct",
       evidence=["email:a2-001", "task:a2-t-hl"], accept=[["6,000"], ["30 oct", "paid", "received"]], reject=["not yet"])
    _q("l-02", "loop_closed", "Is the boiler fixed?", "Yes - new diverter valve fitted on 4 Nov",
       evidence=["chat:Tom (landlord)@2026-11-04T12:30", "journal:2026-11-04", "note:Projects/Flat Move.md"], accept=[["4 nov", "fitted", "fixed", "hot water"]])
    _q("l-03", "loop_closed", "Does Sam still have my book?", "No - returned to the letterbox on 11 Nov",
       evidence=["chat:Sam@2026-11-11T19:20"], accept=[["letterbox", "returned"]])
    _q("l-04", "loop_closed", "How did the deposit dispute end?", "£160 back to Nia, £80 to the landlord for the oven",
       evidence=["email:a2-005", "note:Projects/Flat Move.md"], accept=[["160"], ["80"]])
    _q("l-05", "loop_closed", "Have I paid the Christmas market stall fee?", "Yes - received, per the 6 Nov email",
       evidence=["email:a2-003"], accept=[["received"]])
    # Facts that changed again.
    _q("c-01", "changed_again", "When is the Kestrel dev handoff?", "Friday 27 November (moved from 6 Nov, then 20 Nov)",
       evidence=["email:a2-006", "event:ev-a2-handoff"], accept=[["27 nov", "2026-11-27"]], reject=["20 november is"])
    _q("c-02", "changed_again", "Can I go running yet?", "Yes - 3 x 10 min easy runs a week, flat only, no hills until December",
       evidence=["email:a2-002", "note:Health/Knee Rehab.md"], accept=[["10 min"], ["hills", "flat"]])
    _q("c-03", "changed_again", "When is the Christmas market?", "Sunday 13 and Monday 14 December (corrected from 12-13)",
       evidence=["email:a2-003"], accept=[["13"], ["14 dec", "14 december"]])
    _q("c-04", "changed_again", "What do I still owe the accountant?", "Pension contribution statements (P60 and expenses received)",
       evidence=["email:a2-004"], accept=[["pension"]])
    _q("c-05", "changed_again", "When is my next physio appointment?", "18 December, 08:15",
       evidence=["email:a2-002", "event:ev-a2-physio", "note:Health/Knee Rehab.md"], accept=[["18 dec", "2026-12-18"]], reject=["6 november"])
    # Corrections given to the assistant in conversation.
    _q("u-01", "user_correction", "What's my accountant's email address?", "rhea.k@ledgerline.example (the old address bounces)",
       evidence=["chat:Assistant@2026-11-08T21:02"], accept=[["rhea.k@ledgerline.example"]])
    _q("u-02", "user_correction", "When is Mum's hip operation?", "2 February 2027 (moved from 19 January)",
       evidence=["chat:Assistant@2026-11-09T08:40"], accept=[["2 feb", "february 2"]], reject=["19 january is"])
    # Brand-new facts.
    _q("n-01", "new_fact", "What did Ms Adeyemi say at parents' evening?", "Times tables much better, reading excellent, try chess club",
       evidence=["journal:2026-11-05"], accept=[["times tables"], ["chess", "reading"]])
    # History must survive updates.
    _q("h-a2-01", "history_kept", "As of 1 November, was the boiler fixed?", "No - still on a temporary bypass, part awaited",
       evidence=["chat:Tom (landlord)@2026-10-28T21:30", "email:mv-021"], accept=[["not", "awaiting", "bypass", "next week"]],
       as_of="2026-11-01T12:00:00+00:00")
    _q("h-a2-02", "history_kept", "As of 31 October, when was the Kestrel handoff?", "20 November",
       evidence=["email:hl-017", "event:ev-hl-handoff2"], accept=[["20 nov", "2026-11-20"]], as_of="2026-10-31T12:00:00+00:00")
    _q("h-a2-03", "history_kept", "What was my accountant's email before I changed it?", "rhea@ledgerline.example",
       evidence=["note:People/Rhea Kapoor.md", "email:tx-003"], accept=[["rhea@ledgerline.example"]])
    return list(QUESTIONS_SPEC)


# Unchanged act-1 questions re-asked at the act-2 "now": nothing about them changed, so a learning system must
# still get them right (regression check). Ids refer to truth.questions().
REGRESSION_IDS = ["single-04", "tail-01", "ent-01", "tok-01", "upd-02", "hist-01", "imp-01", "abs-02", "h-16", "h-18"]
