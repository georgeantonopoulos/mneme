"""Hand-written storylines for the fictional LifeVault fixture.

Everything here is invented. People, companies, schools and addresses are
fictional; every email address uses a reserved ``.example`` domain. The
persona is Nia Okafor, a freelance product designer and single parent, and the
story runs from 2026-05-01 to the fixture "now" of 2026-10-29.

Each storyline appends to the module-level collections below. ``build.py``
turns them into Markdown notes, .eml files, an .ics calendar, a chat export and
a task-app export. ``truth.py`` holds the ground-truth facts and eval questions
that refer back to these events by id.
"""
from __future__ import annotations

NOW = "2026-10-29T18:00:00+00:00"
ME = ("Nia Okafor", "nia@okafor.example")

EMAILS: list[dict] = []
NOTES: list[dict] = []
JOURNAL: dict[str, list[str]] = {}
EVENTS: list[dict] = []
CHATS: list[dict] = []
TASKS: list[dict] = []

PEOPLE = {
    "tomasz": ("Tomasz Wren", "tomasz@wrenlettings.example"),
    "gemma": ("Gemma Holt", "gemma@harbourside-lets.example"),
    "priya": ("Priya Raman", "priya@halcyonlabs.example"),
    "daniel": ("Daniel Achterberg", "daniel@halcyonlabs.example"),
    "halfin": ("Halcyon Labs Accounts", "accounts@halcyonlabs.example"),
    "josie": ("Josie Bramble", "josie@brambleandco.example"),
    "marsh": ("Northgate Physio", "bookings@northgatephysio.example"),
    "helen": ("Helen Marsh", "helen@northgatephysio.example"),
    "school": ("Larkfield Primary Office", "office@larkfield-primary.example"),
    "adeyemi": ("Kemi Adeyemi", "k.adeyemi@larkfield-primary.example"),
    "marcus": ("Marcus Hale", "marcus.hale@mailbox.example"),
    "sam": ("Sam Petrov", "sam.petrov@mailbox.example"),
    "felix": ("Felix Grant", "felix@grantlowe.example"),
    "rhea": ("Rhea Kapoor", "rhea@ledgerline.example"),
    "brightway": ("Brightway Insurance", "renewals@brightway-insurance.example"),
    "aerolis": ("Aerolis Airways", "bookings@aerolis.example"),
    "casa": ("Casa do Rio Lisbon", "reservas@casadorio.example"),
    "flowline": ("Flowline Heating", "jobs@flowlineheating.example"),
    "depositguard": ("DepositGuard Disputes", "disputes@depositguard.example"),
    "swim": ("Riverside Swim School", "hello@riversideswim.example"),
    "bank": ("Northmoor Bank", "alerts@northmoorbank.example"),
    "mum": ("Grace Okafor", "grace.okafor@mailbox.example"),
    "lena": ("Lena Fischer", "lena@kilnhouse.example"),
}


def email(eid, date, frm, subject, body, *, to="me", thread=None, cc=None, html=None, attachments=None, folder="inbox", labels=None):
    sender = ME if frm == "me" else PEOPLE.get(frm, frm)
    recipient = ME if to == "me" else PEOPLE.get(to, to)
    EMAILS.append({
        "id": eid, "date": date, "from": sender, "to": recipient, "cc": [PEOPLE[c] for c in (cc or [])],
        "subject": subject, "body": body.strip("\n"), "thread": thread or eid, "html": html,
        "attachments": attachments or [], "folder": folder, "labels": labels or [],
    })


def note(path, created, body, *, updated=None, tags=None, kind="note"):
    NOTES.append({"path": path, "created": created, "updated": updated or created, "body": body.strip("\n"), "tags": tags or [], "kind": kind})


def journal(date, *lines):
    JOURNAL.setdefault(date, []).extend(lines)


def event(uid, start, end, summary, *, location="", desc="", status="CONFIRMED", sequence=0, created=None, all_day=False):
    EVENTS.append({"uid": uid, "start": start, "end": end, "summary": summary, "location": location, "desc": desc,
                   "status": status, "sequence": sequence, "created": created or start[:10], "all_day": all_day})


def chat(ts, conversation, frm, text):
    CHATS.append({"ts": ts, "chat": conversation, "from": frm, "text": text})


def task(tid, title, created, *, due=None, completed=None, project="Inbox", notes=""):
    TASKS.append({"id": tid, "title": title, "created": created, "due": due, "completed": completed, "project": project, "notes": notes})


# ---------------------------------------------------------------------------
# Storyline 1: moving flat (old landlord, new landlord, move date, rent, boiler)
# ---------------------------------------------------------------------------
def moving() -> None:
    note("Projects/Flat Move.md", "2026-05-04", """
# Flat Move

Current flat: 14 Cotham Rise, Bristol (let through Harbourside Lets, agent [[Gemma Holt]]).
Lease ends 2026-09-30. Need somewhere with a second bedroom for [[Ivy]] and a spare corner for the wheel.

## Criteria
- Two bedrooms, under £1,500 a month
- Walking distance to [[Larkfield Primary]]
- Ground floor or lift (knee - see [[Knee Rehab]])
- Somewhere I could fire small pieces, or at least store clay without the landlord freaking out

## Log
- 2026-05-04 started looking, registered with three agents
- 2026-06-12 viewed Alder Street flat, loved the light, landlord seems decent ([[Tomasz Wren]])
- 2026-07-10 offer accepted on Flat 3, 22 Alder Street. Move-in agreed for 1 September
- 2026-07-28 rent negotiated down to £1,425 (from £1,450) in exchange for a 15 month term
- 2026-08-05 UPDATE: move-in pushed to 15 September - Tomasz's decorators overran
- 2026-09-15 moved in. Boxes everywhere. Ivy chose the room with the round window.
- 2026-10-18 boiler died, no hot water. Tomasz is arranging Flowline.
- 2026-10-28 still waiting on the replacement diverter valve

## Open
- [ ] Get the £240 deduction on the Cotham Rise deposit overturned (DepositGuard case DG-58213)
- [ ] Chase Tomasz about boiler part ETA
- [x] Redirect post via Royal Mail
- [x] Change address with Northmoor Bank
- [ ] Change address on car insurance before renewal
""", updated="2026-10-28", tags=["project", "home"])

    note("People/Tomasz Wren.md", "2026-06-12", """
# Tomasz Wren

- Landlord of Flat 3, 22 Alder Street (owns the building, runs Wren Lettings himself)
- Goes by Tom in messages
- Email tomasz@wrenlettings.example, prefers WhatsApp for anything urgent
- Very responsive on weekdays, slow at weekends
- Wife runs a bakery on Gloucester Road, he brought croissants on move-in day
""", updated="2026-09-15", tags=["person", "home"])

    note("People/Gemma Holt.md", "2026-05-04", """
# Gemma Holt

- Letting agent at Harbourside Lets, manages 14 Cotham Rise (my old flat)
- gemma@harbourside-lets.example
- Handled the check-out inspection on 2026-09-30
- Deducted £240 from the deposit for "professional cleaning" - I disagree, the inventory photos show it spotless
""", updated="2026-10-06", tags=["person", "home"])

    email("mv-001", "2026-06-10T09:14", "tomasz", "Viewing - Flat 3, 22 Alder Street", """
Hi Nia,

Thanks for your interest in Flat 3. I can show you round on Friday 12 June at 5.30pm.
Two bedrooms, the second is smallish but has a lovely round window. Rent is £1,450 pcm,
bills not included. There is a dry storage room in the basement you could use for your pottery.

Best,
Tomasz
""", thread="mv-view")
    event("ev-mv-viewing", "2026-06-12T17:30", "2026-06-12T18:15", "Flat viewing - 22 Alder Street", location="Flat 3, 22 Alder Street, Bristol", created="2026-06-10")
    journal("2026-06-12", "Viewed Alder Street. The light in the back room is gorgeous and there's a basement store for clay. Tomasz seems decent - asked about Ivy's school before I did.")

    email("mv-002", "2026-07-10T16:40", "tomasz", "Offer accepted - Flat 3", """
Hi Nia,

Happy to confirm I accept your offer for Flat 3, 22 Alder Street at £1,450 per month.
Move-in date 1 September 2026. I'll send the tenancy agreement next week.
Holding deposit of £330 received, thank you.

Tomasz
""", thread="mv-offer")
    chat("2026-07-10T17:02", "Mum", "Nia", "We got the Alder Street flat!! Moving 1st Sept")
    chat("2026-07-10T17:05", "Mum", "Grace", "Wonderful darling. I'll come down and help with Ivy that week")

    email("mv-003", "2026-07-22T10:03", "me", "Re: Tenancy agreement", """
Hi Tomasz,

I've read through the agreement. Would you consider £1,425 if I sign for 15 months instead of 12?
It would really help with the budget this year.

Thanks,
Nia
""", to="tomasz", thread="mv-tenancy")
    email("mv-004", "2026-07-28T08:55", "tomasz", "Re: Tenancy agreement", """
Nia, that works for me. £1,425 pcm on a 15 month term starting on move-in. Updated agreement attached,
please sign by Friday.

T
""", thread="mv-tenancy", attachments=["Tenancy_Agreement_Flat3_v2.pdf"])
    task("t-mv-1", "Sign Alder Street tenancy agreement", "2026-07-28", due="2026-07-31", completed="2026-07-30", project="Flat Move")

    email("mv-005", "2026-08-05T19:21", "tomasz", "Move-in date - change", """
Hi Nia,

I'm really sorry - the decorators have overrun on the kitchen and won't be finished by 1 September.
Could we move your move-in to Tuesday 15 September? I'll take £300 off the first month to make up for it.

Apologies again,
Tomasz
""", thread="mv-date")
    email("mv-006", "2026-08-05T21:10", "me", "Re: Move-in date - change", """
That's annoying but OK - 15 September works, and thank you for the discount.
My current lease runs to 30 September so we have overlap anyway.

Nia
""", to="tomasz", thread="mv-date")
    event("ev-mv-move", "2026-09-01", "2026-09-02", "MOVE DAY - Alder Street", status="CANCELLED", sequence=1, created="2026-07-10", all_day=True)
    event("ev-mv-move2", "2026-09-15", "2026-09-16", "MOVE DAY - Alder Street (rescheduled)", location="22 Alder Street", created="2026-08-05", all_day=True)
    journal("2026-08-05", "Move pushed to the 15th. Honestly fine, gives me two more weeks to pack. £300 off is nice.")
    task("t-mv-2", "Book van for move", "2026-08-06", due="2026-09-10", completed="2026-08-20", project="Flat Move", notes="Booked Bristol Man & Van for 15 Sept 8am, £280")
    email("mv-007", "2026-08-20T12:00", "Bristol Man & Van <bookings@bristolmanvan.example>", "Booking confirmed: 15 Sep 2026, 08:00", """
Booking ref BMV-4471
Date: Tuesday 15 September 2026, 08:00
From: 14 Cotham Rise  To: Flat 3, 22 Alder Street
Price: £280 (2 movers, 4 hours)
""", thread="mv-van")

    journal("2026-09-15", "MOVED. Van was early, Mum kept Ivy busy, Tomasz brought croissants. Ivy picked the round-window room. Exhausted.")
    chat("2026-09-15T21:40", "Sam", "Nia", "We're in! Come for (takeaway) dinner on Saturday?")
    chat("2026-09-15T21:52", "Sam", "Sam", "YES. bringing your book back finally")

    # old flat deposit dispute
    event("ev-mv-checkout", "2026-09-30T10:00", "2026-09-30T11:00", "Check-out inspection, 14 Cotham Rise", location="14 Cotham Rise", created="2026-09-10")
    email("mv-010", "2026-10-02T15:30", "gemma", "Deposit return - 14 Cotham Rise", """
Dear Nia,

Following the check-out inspection on 30 September we propose returning £1,360 of your £1,600 deposit.
A deduction of £240 has been made for professional cleaning of the oven and carpets.

Kind regards,
Gemma Holt
Harbourside Lets
""", thread="mv-deposit")
    email("mv-011", "2026-10-03T09:10", "me", "Re: Deposit return - 14 Cotham Rise", """
Hi Gemma,

I don't accept the £240 deduction. The oven and carpets were professionally cleaned on 28 September
(receipt attached) and the check-out photos show this. Please return the full £1,600.

Nia
""", to="gemma", thread="mv-deposit", attachments=["SparkleClean_receipt_28Sep.pdf"])
    email("mv-012", "2026-10-06T11:45", "gemma", "Re: Deposit return - 14 Cotham Rise", """
Dear Nia,

Our landlord does not agree. You are welcome to raise a dispute through DepositGuard.

Gemma
""", thread="mv-deposit")
    email("mv-013", "2026-10-07T08:20", "depositguard", "Dispute opened: case DG-58213", """
Your dispute has been registered.
Case reference: DG-58213
Disputed amount: £240
The landlord has 14 days to submit evidence. An adjudicator decision is normally issued within 28 days
of evidence closing. Estimated decision date: 20 November 2026.
The undisputed £1,360 will be released to you within 5 working days.
""", thread="mv-dg")
    email("mv-014", "2026-10-13T07:02", "bank", "Payment received: £1,360.00", """
A payment of £1,360.00 from DEPOSITGUARD SCHEME has been credited to your account ending 4471.
""")
    task("t-mv-3", "Upload cleaning receipt + photos to DepositGuard", "2026-10-07", due="2026-10-21", completed="2026-10-09", project="Flat Move")

    # boiler
    chat("2026-10-18T07:15", "Tom (landlord)", "Nia", "Morning Tom - no hot water or heating since last night, boiler shows error F28")
    chat("2026-10-18T08:40", "Tom (landlord)", "Tom", "Sorry Nia! I'll get Flowline out Monday, they're the people who did the install")
    journal("2026-10-18", "Boiler dead. Cold showers at the gym, Ivy bathed at Marcus's. Grim.")
    email("mv-020", "2026-10-19T09:05", "flowline", "Engineer visit booked - Flat 3, 22 Alder Street", """
Job ref FL-20931
Engineer visit: Wednesday 21 October, 8am-12pm
Reported fault: no heat / hot water, code F28
Landlord account: Wren Lettings
""", thread="mv-boiler")
    event("ev-mv-boiler", "2026-10-21T08:00", "2026-10-21T12:00", "Flowline engineer - boiler", location="Flat 3, 22 Alder Street", created="2026-10-19")
    email("mv-021", "2026-10-21T13:20", "flowline", "Visit report FL-20931", """
Engineer attended. Fault: failed diverter valve. Temporary bypass fitted - heating restored,
hot water only via immersion. Replacement part ordered, expected 5-7 working days.
We will contact the landlord to arrange the return visit.
""", thread="mv-boiler")
    chat("2026-10-21T13:40", "Tom (landlord)", "Tom", "Flowline say part is 5-7 working days, they'll come back to fit it. Sorry again")
    chat("2026-10-28T19:02", "Tom (landlord)", "Nia", "Hi Tom, any news on the boiler part? still on the immersion")
    chat("2026-10-28T21:30", "Tom (landlord)", "Tom", "Chased them today, supplier says early next week. I'll knock £50 off November for the hassle")
    task("t-mv-4", "Chase Tom re boiler part", "2026-10-26", due="2026-10-30", project="Flat Move")


# ---------------------------------------------------------------------------
# Storyline 2: Halcyon Labs - Kestrel app redesign (main client)
# ---------------------------------------------------------------------------
def halcyon() -> None:
    note("Clients/Halcyon Labs.md", "2026-05-06", """
# Halcyon Labs

Main client this year. Fintech for small charities. Project: [[Kestrel Redesign]].

- Producer: [[Priya Raman]] (until 14 Aug - she left for a startup)
- Producer from 18 Aug: [[Daniel Achterberg]]
- Invoices go to accounts@halcyonlabs.example, payment terms 30 days
- Day rate £450 (May-Aug), £500 from 1 September (agreed with Daniel 2026-08-27)

## Invoices
| Invoice | Amount | Sent | Status |
|---|---|---|---|
| INV-2026-011 | £3,600 | 2026-05-29 | paid 2026-06-24 |
| INV-2026-012 | £4,050 | 2026-06-30 | paid 2026-07-28 |
| INV-2026-014 | £4,500 | 2026-07-31 | paid 2026-09-12 (13 days late) |
| INV-2026-016 | £5,000 | 2026-08-31 | paid 2026-09-29 |
| INV-2026-017 | £6,000 | 2026-09-30 | due 2026-10-30 |
""", updated="2026-09-30", tags=["client", "work"])

    note("Projects/Kestrel Redesign.md", "2026-05-06", """
# Kestrel Redesign

Redesign of Halcyon's donation-management app for small charities. Client: [[Halcyon Labs]].

## Phases
1. Discovery + interviews (May)
2. Information architecture + flows (June)
3. Visual design system (July-Aug)
4. Hi-fi screens + prototype (Sept-Oct)
5. Handoff to dev - target 2026-11-20

## Decisions
- 2026-06-18 Dropped the "campaign wizard" - charities found it patronising in testing
- 2026-07-09 Brand colour: deep teal #0F5C5A, accent marigold
- 2026-08-27 Scope add: offline mode for event volunteers (+8 days)
- 2026-10-14 Handoff moved from 2026-11-06 to 2026-11-20 because of the offline mode work

## Open
- [ ] Final prototype review with Daniel - 2026-11-03
- [ ] Accessibility audit of colour tokens
- [ ] Write handoff doc for the dev team (Lukas)
""", updated="2026-10-14", tags=["project", "work"])

    note("People/Priya Raman.md", "2026-05-06", """
# Priya Raman

- Producer at [[Halcyon Labs]] who hired me for Kestrel
- Left Halcyon on 2026-08-14 to join a climate startup (Fernleaf)
- Personal: priya.r@mailbox.example. Still happy to be a reference.
""", updated="2026-08-14", tags=["person", "work"])
    note("People/Daniel Achterberg.md", "2026-08-18", """
# Daniel Achterberg

- Took over as producer on Kestrel from [[Priya Raman]] on 2026-08-18
- Dutch, very direct, likes decisions written down
- Agreed my day rate rise to £500 from September
- Weekly check-in Thursdays 10:00
""", updated="2026-08-27", tags=["person", "work"])

    email("hl-001", "2026-05-05T11:00", "priya", "Kestrel - would you be up for it?", """
Hi Nia,

We're redesigning Kestrel (our donation-management app) and I'd love you to lead design.
Roughly 6 months, 2-3 days a week. Day rate £450? Kickoff Wednesday 6 May if you're in.

Priya
""", thread="hl-kickoff")
    event("ev-hl-kickoff", "2026-05-06T10:00", "2026-05-06T12:00", "Kestrel kickoff @ Halcyon", location="Halcyon Labs, Paintworks", created="2026-05-05")
    email("hl-002", "2026-05-29T17:00", "me", "Invoice INV-2026-011", """
Hi, please find attached invoice INV-2026-011 for £3,600 (8 days, May). Payment terms 30 days.
""", to="halfin", thread="hl-inv11", attachments=["INV-2026-011.pdf"], folder="sent")
    email("hl-003", "2026-06-24T09:00", "bank", "Payment received: £3,600.00", "A payment of £3,600.00 from HALCYON LABS LTD has been credited to your account ending 4471.")
    email("hl-004", "2026-06-18T16:20", "priya", "Testing results - campaign wizard", """
Nia - the charity testing was pretty clear. 5 of 6 participants found the campaign wizard patronising.
Let's drop it and go with the template gallery idea. Can you update the flows?
""", thread="hl-wizard")
    email("hl-005", "2026-06-30T17:30", "me", "Invoice INV-2026-012", "Invoice INV-2026-012 attached, £4,050 (9 days, June).", to="halfin", thread="hl-inv12", attachments=["INV-2026-012.pdf"], folder="sent")
    email("hl-006", "2026-07-28T09:00", "bank", "Payment received: £4,050.00", "A payment of £4,050.00 from HALCYON LABS LTD has been credited to your account ending 4471.")
    email("hl-007", "2026-07-31T16:45", "me", "Invoice INV-2026-014", "Invoice INV-2026-014 attached, £4,500 (10 days, July). Due 30 August.", to="halfin", thread="hl-inv14", attachments=["INV-2026-014.pdf"], folder="sent")
    email("hl-008", "2026-08-11T10:12", "priya", "Some news", """
Hi Nia,

I wanted you to hear it from me - I'm leaving Halcyon on Friday 14 August to join Fernleaf.
Daniel Achterberg will take over Kestrel from 18 August. He's great, you'll like him.
It's been a joy working with you.

Priya
""", thread="hl-priya")
    journal("2026-08-11", "Priya's leaving Halcyon. Gutted, she's the reason I got Kestrel. Hope Daniel isn't a nightmare.")
    event("ev-hl-daniel", "2026-08-18T10:00", "2026-08-18T11:00", "Intro call - Daniel (Kestrel handover)", created="2026-08-12")
    email("hl-009", "2026-08-27T15:00", "daniel", "Rate + offline mode", """
Hi Nia,

Following our call: agreed, your day rate moves to £500 from 1 September.
We'd also like to add offline mode for event volunteers - estimate 8 extra days.
Let's keep the Thursday 10:00 check-ins.

Daniel
""", thread="hl-rate")
    email("hl-010", "2026-08-31T17:10", "me", "Invoice INV-2026-016", "Invoice INV-2026-016 attached, £5,000 (10 days, August at £500 per agreement... wait no)", to="halfin", thread="hl-inv16", attachments=["INV-2026-016.pdf"], folder="drafts")
    email("hl-011", "2026-08-31T17:25", "me", "Invoice INV-2026-016", "Invoice INV-2026-016 attached, £5,000 (11 days in August at £450 = £4,950, plus £50 prototype hosting). Due 30 September.", to="halfin", thread="hl-inv16", attachments=["INV-2026-016.pdf"], folder="sent")
    email("hl-012", "2026-09-02T09:30", "me", "INV-2026-014 overdue", """
Hi accounts team, INV-2026-014 (£4,500) was due on 30 August and I haven't received payment yet.
Could you let me know when it will be paid?
""", to="halfin", thread="hl-inv14", folder="sent")
    email("hl-013", "2026-09-04T14:00", "halfin", "Re: INV-2026-014 overdue", """
Apologies Nia - this got stuck because Priya was the approver and she has left. Daniel has now approved it.
It will go out in the payment run on 12 September.
""", thread="hl-inv14")
    email("hl-014", "2026-09-12T08:00", "bank", "Payment received: £4,500.00", "A payment of £4,500.00 from HALCYON LABS LTD has been credited to your account ending 4471.")
    email("hl-015", "2026-09-29T08:00", "bank", "Payment received: £5,000.00", "A payment of £5,000.00 from HALCYON LABS LTD has been credited to your account ending 4471.")
    email("hl-016", "2026-09-30T16:30", "me", "Invoice INV-2026-017", "Invoice INV-2026-017 attached, £6,000 (12 days September at £500). Due 30 October.", to="halfin", thread="hl-inv17", attachments=["INV-2026-017.pdf"], folder="sent")
    email("hl-017", "2026-10-14T11:00", "daniel", "Handoff date", """
Nia - given the offline mode work, let's move dev handoff from 6 November to 20 November.
Final prototype review stays on 3 November. Lukas from the dev team will join.
""", thread="hl-handoff")
    event("ev-hl-review", "2026-11-03T14:00", "2026-11-03T16:00", "Kestrel final prototype review", location="Halcyon Labs", created="2026-10-14")
    event("ev-hl-handoff", "2026-11-06", "2026-11-07", "Kestrel dev handoff", status="CANCELLED", sequence=1, created="2026-07-01", all_day=True)
    event("ev-hl-handoff2", "2026-11-20", "2026-11-21", "Kestrel dev handoff", created="2026-10-14", all_day=True)
    for i, day in enumerate(["2026-08-20", "2026-08-27", "2026-09-03", "2026-09-10", "2026-09-17", "2026-09-24", "2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22", "2026-10-29"]):
        event(f"ev-hl-checkin-{i}", f"{day}T10:00", f"{day}T10:30", "Kestrel check-in w/ Daniel", created="2026-08-18")
    task("t-hl-1", "Chase INV-2026-014", "2026-09-01", due="2026-09-02", completed="2026-09-12", project="Halcyon")
    task("t-hl-2", "Accessibility audit of Kestrel colour tokens", "2026-10-01", due="2026-11-02", project="Halcyon")
    task("t-hl-3", "Write Kestrel handoff doc", "2026-10-14", due="2026-11-18", project="Halcyon")
    task("t-hl-4", "Check INV-2026-017 paid", "2026-09-30", due="2026-10-31", project="Halcyon")
    chat("2026-10-22T10:35", "Daniel (Halcyon)", "Daniel", "Thanks for today. Lukas asked if the offline sync states can be in the prototype by Monday")
    chat("2026-10-22T10:41", "Daniel (Halcyon)", "Nia", "Yes, I'll add the three sync states (queued, syncing, failed) by Monday")


# ---------------------------------------------------------------------------
# Storyline 3: Bramble & Co - small brand job, cancelled with kill fee
# ---------------------------------------------------------------------------
def bramble() -> None:
    note("Clients/Bramble and Co.md", "2026-07-01", """
# Bramble & Co

Small tea shop chain (3 shops). Brand refresh: logo, menu boards, packaging. Contact [[Josie Bramble]].
Quoted £2,400 fixed. 30% kill fee in contract.

- 2026-07-01 kickoff, moodboards
- 2026-07-24 logo round 1 delivered
- 2026-08-20 CANCELLED - Josie's investor pulled out. Kill fee £720 invoiced (INV-2026-015)
- 2026-09-03 kill fee paid

Lesson: always put the kill fee in. It saved me here.
""", updated="2026-09-03", tags=["client", "work"])
    note("People/Josie Bramble.md", "2026-07-01", "# Josie Bramble\n\n- Owner of [[Bramble and Co]]\n- Lovely, chaotic, sends voice notes at midnight\n- Might come back in 2027 if funding sorts out", tags=["person", "work"])
    email("br-001", "2026-06-26T13:00", "josie", "Brand refresh for the tea shops?", "Hi Nia! A friend of Priya's recommended you. We need a brand refresh before the third shop opens. Budget around £2.5k. Fancy it?", thread="br-intro")
    email("br-002", "2026-08-20T22:47", "josie", "Bad news, sorry", """
Nia I'm so sorry. Our investor has pulled out and we're pausing the third shop and the rebrand.
Please invoice the kill fee per the contract. Your logo round was gorgeous, I hope we get back to it.

Josie x
""", thread="br-cancel")
    email("br-003", "2026-08-25T10:00", "me", "Invoice INV-2026-015", "Kill fee per contract clause 7: 30% of £2,400 = £720. Due 24 September.", to="josie", thread="br-cancel", attachments=["INV-2026-015.pdf"], folder="sent")
    email("br-004", "2026-09-03T08:00", "bank", "Payment received: £720.00", "A payment of £720.00 from BRAMBLE AND CO LTD has been credited to your account ending 4471.")
    journal("2026-08-20", "Bramble cancelled. Disappointing but the kill fee clause did its job. Gap in Sept now - pitch to Lena's studio?")


# ---------------------------------------------------------------------------
# Storyline 4: knee rehab
# ---------------------------------------------------------------------------
def knee() -> None:
    note("Health/Knee Rehab.md", "2026-05-12", """
# Knee Rehab

Left knee, patellofemoral pain after the half marathon in April. Physio: [[Helen Marsh]] at Northgate Physio.

## Exercises (current - updated 2026-09-29)
- Spanish squats 3x45s hold
- Step-downs 3x12 from 20cm step
- Single-leg bridges 3x15
- ~~Wall sits~~ (replaced by Spanish squats on 29 Sept)

## Rules
- No running until the review on 2026-11-06 (Helen, 29 Sept)
- Cycling fine. Swimming fine except breaststroke kick.
- Ibuprofen gel only, not tablets (stomach)

## Appointments
- 2026-05-12 assessment
- 2026-06-09, 2026-07-14, 2026-08-18 follow-ups
- 2026-09-29 follow-up: progress good, new programme
- 2026-11-06 review - decide on return to running
""", updated="2026-09-29", tags=["health"])
    note("People/Helen Marsh.md", "2026-05-12", "# Helen Marsh\n\n- Physio at Northgate Physio, treating my left knee ([[Knee Rehab]])\n- Bookings via bookings@northgatephysio.example", tags=["person", "health"])
    for i, (d, seq) in enumerate([("2026-05-12", 0), ("2026-06-09", 0), ("2026-07-14", 0), ("2026-08-18", 0), ("2026-09-29", 0)]):
        event(f"ev-kn-{i}", f"{d}T08:15", f"{d}T09:00", "Physio - Helen Marsh", location="Northgate Physio, Gloucester Road", created=d)
    email("kn-001", "2026-10-01T12:00", "marsh", "Appointment confirmation", """
Your appointment with Helen Marsh is confirmed:
Thursday 5 November 2026, 08:15
Northgate Physio, Gloucester Road
""", thread="kn-nov")
    email("kn-002", "2026-10-20T09:30", "marsh", "Appointment rescheduled", """
Helen is on a course on 5 November. Your appointment has been moved to:
Friday 6 November 2026, 08:15
Reply to this email if this doesn't suit.
""", thread="kn-nov")
    event("ev-kn-nov", "2026-11-05T08:15", "2026-11-05T09:00", "Physio review - Helen", status="CANCELLED", sequence=1, created="2026-10-01")
    event("ev-kn-nov2", "2026-11-06T08:15", "2026-11-06T09:00", "Physio review - Helen (return to running?)", location="Northgate Physio", created="2026-10-20")
    journal("2026-09-29", "Physio: Helen pleased. New exercises (Spanish squats, ugh). Still no running until Nov review. Cycling is fine so bike to Halcyon.")
    journal("2026-07-19", "Knee twinged on the stairs at Mum's. Iced it. Doing the exercises maybe 4 days out of 7, need to be better.")


# ---------------------------------------------------------------------------
# Storyline 5: Ivy - school, swimming, co-parenting with Marcus
# ---------------------------------------------------------------------------
def ivy() -> None:
    note("People/Ivy.md", "2026-05-01", """
# Ivy

My daughter, 8 (birthday 2 March). Year 4 at [[Larkfield Primary]] from September, class teacher [[Kemi Adeyemi]].

- Allergies: mild hayfever, no food allergies
- Swimming: Riverside Swim School, Stage 5. Saturdays 9:00 until August, **Sundays 10:00 from 13 September**
- Best friends: Maya and Leo
- Dad: [[Marcus Hale]] - alternate weekends (Fri pickup from school, back Sunday 6pm)
- Currently obsessed with octopuses and making clay octopuses on my wheel
""", updated="2026-09-08", tags=["person", "family"])
    note("People/Marcus Hale.md", "2026-05-01", """
# Marcus Hale

- Ivy's dad. We co-parent; alternate weekends + Wednesday tea
- marcus.hale@mailbox.example, WhatsApp is better
- Lives in Easton
- Swapped weekends: he has Ivy 30 Oct - 1 Nov (Halloween) instead of 23-25 Oct
""", updated="2026-10-12", tags=["person", "family"])
    note("Areas/Larkfield Primary.md", "2026-05-01", """
# Larkfield Primary

Ivy's school. Office: office@larkfield-primary.example. Year 4 teacher from Sept: [[Kemi Adeyemi]].

- Term dates autumn 2026: 3 Sept - 18 Dec, half term 26-30 Oct
- Parents' evening: 5 November, my slot 16:30
- Harbour Museum trip: 10 November, permission slip + £12 due 3 November
- PE days: Tuesday and Thursday (needs kit)
""", updated="2026-10-21", tags=["family", "school"])
    note("People/Kemi Adeyemi.md", "2026-09-04", "# Kemi Adeyemi\n\n- Ivy's Year 4 class teacher at [[Larkfield Primary]] (from Sept 2026)\n- k.adeyemi@larkfield-primary.example\n- Says Ivy is strong at reading, needs practice with times tables", tags=["person", "family"])

    for d in ["2026-05-02", "2026-05-09", "2026-05-16", "2026-05-23", "2026-06-06", "2026-06-13", "2026-06-20", "2026-06-27", "2026-07-04", "2026-07-11", "2026-07-18", "2026-08-29", "2026-09-05"]:
        event(f"ev-swim-{d}", f"{d}T09:00", f"{d}T09:45", "Ivy swimming", location="Riverside Pool", created="2026-04-20")
    email("iv-001", "2026-09-07T18:00", "swim", "Autumn timetable change - Stage 5", """
Dear parents,

From Sunday 13 September, Stage 5 lessons move from Saturdays 9:00 to Sundays 10:00 (same pool).
Autumn term fee: £96, payable by 11 September.
""", thread="iv-swim")
    for d in ["2026-09-13", "2026-09-20", "2026-09-27", "2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25", "2026-11-01", "2026-11-08"]:
        event(f"ev-swim-{d}", f"{d}T10:00", f"{d}T10:45", "Ivy swimming", location="Riverside Pool", created="2026-09-07")
    task("t-iv-1", "Pay autumn swim fee £96", "2026-09-07", due="2026-09-11", completed="2026-09-08", project="Ivy")
    # A second "Sam" (the swim coach) so retrieval has to tell people apart.
    email("iv-005", "2026-10-19T17:45", "Sam Doherty <sam@riversideswim.example>", "Ivy - ready for Stage 6", """
Hi Nia,

Ivy has passed all her Stage 5 outcomes - her backstroke is lovely. She can move up to Stage 6 from
January (Sundays 10:45). I'll send the form nearer the time.

Sam Doherty
Head coach, Riverside Swim School
""", thread="iv-stage6")
    journal("2026-10-19", "Ivy passed Stage 5! Coach Sam says Stage 6 from January, Sundays 10:45. She did a victory lap of the kitchen.")

    email("iv-002", "2026-09-04T15:30", "adeyemi", "Welcome to Year 4!", """
Dear parents and carers,

Welcome to Year 4 - Kingfisher class. PE is on Tuesdays and Thursdays. Reading records should come in every Monday.
I'll be in touch about parents' evening in October.

Ms Adeyemi
""", thread="iv-welcome")
    email("iv-003", "2026-10-12T16:00", "school", "Parents' evening booking", """
Your parents' evening appointment is confirmed:
Ivy Okafor-Hale, Year 4 Kingfisher - Ms Adeyemi
Thursday 5 November 2026, 16:30-16:40
""", thread="iv-pe")
    event("ev-iv-pe", "2026-11-05T16:30", "2026-11-05T16:40", "Parents' evening - Ms Adeyemi", location="Larkfield Primary", created="2026-10-12")
    email("iv-004", "2026-10-21T14:10", "school", "Year 4 trip to the Harbour Museum - 10 November", """
Dear parents,

Year 4 will visit the Harbour Museum on Tuesday 10 November. Please return the signed permission slip and
a £12 contribution via ParentPay by Tuesday 3 November. Children need a packed lunch.
""", thread="iv-trip", attachments=["Permission_slip_Y4_museum.pdf"])
    task("t-iv-2", "Sign museum permission slip + pay £12 on ParentPay", "2026-10-21", due="2026-11-03", project="Ivy")
    event("ev-iv-trip", "2026-11-10", "2026-11-11", "Ivy school trip - Harbour Museum (packed lunch!)", created="2026-10-21", all_day=True)

    chat("2026-10-12T20:15", "Marcus", "Marcus", "Could we swap weekends? My parents are visiting 30 Oct-1 Nov and want to see Ivy for Halloween")
    chat("2026-10-12T20:20", "Marcus", "Nia", "Sure - so you have her 30 Oct-1 Nov and I keep her 23-25 Oct?")
    chat("2026-10-12T20:21", "Marcus", "Marcus", "Perfect, thanks. I'll do the Sunday swim on the 1st")
    event("ev-iv-marcus1", "2026-10-23", "2026-10-26", "Ivy at Marcus's", status="CANCELLED", sequence=1, created="2026-09-01", all_day=True)
    event("ev-iv-marcus2", "2026-10-30", "2026-11-02", "Ivy at Marcus's (Halloween swap)", created="2026-10-12", all_day=True)
    journal("2026-10-12", "Swapped weekends with Marcus so his parents get Halloween with Ivy. Means I have her all half term week - need a plan for the 26-29th while I work.")
    task("t-iv-3", "Sort childcare for half term 26-29 Oct", "2026-10-12", due="2026-10-20", completed="2026-10-16", project="Ivy", notes="Mum is coming 26-28, holiday club Thursday 29")
    chat("2026-10-16T12:00", "Mum", "Grace", "I'll come Monday 26th to Wednesday, train gets in 11:40")
    chat("2026-10-16T12:05", "Mum", "Nia", "Amazing thank you. I've booked Ivy into Kickstart holiday club on the Thursday")


# ---------------------------------------------------------------------------
# Storyline 6: tax and accountant change
# ---------------------------------------------------------------------------
def tax() -> None:
    note("Finance/Tax 2025-26.md", "2026-05-20", """
# Tax 2025-26

Self assessment for tax year 6 Apr 2025 - 5 Apr 2026.

- Accountant: ~~[[Felix Grant]] (Grant & Lowe)~~ -> [[Rhea Kapoor]] at Ledgerline from 22 Sept 2026
- Felix retired at the end of September; Grant & Lowe handed clients over
- Rhea's fee: £540 fixed (Felix was £600)
- Rhea needs: P60 from the part-time teaching, expenses spreadsheet, pension statements - **by 15 November**
- Filing deadline 31 January 2027; balancing payment + first payment on account also 31 January 2027
- Estimate from Felix (July): around £3,900 to pay in January
""", updated="2026-10-05", tags=["finance"])
    note("People/Felix Grant.md", "2026-05-20", "# Felix Grant\n\n- Was my accountant (Grant & Lowe) 2019-2026\n- Retired end of September 2026, handed over to Rhea Kapoor at Ledgerline", updated="2026-09-22", tags=["person", "finance"])
    note("People/Rhea Kapoor.md", "2026-09-22", "# Rhea Kapoor\n\n- My accountant from 22 Sept 2026, Ledgerline\n- rhea@ledgerline.example\n- Quick on email, wants everything as a shared folder", tags=["person", "finance"])
    email("tx-001", "2026-07-15T10:00", "felix", "Tax estimate 2025-26", """
Hi Nia,

Based on the figures so far I'd estimate around £3,900 payable on 31 January 2027 (balancing payment plus
first payment on account). I'll finalise once I have your P60 and expenses.

Felix
""", thread="tx-est")
    email("tx-002", "2026-09-01T09:00", "felix", "Retirement and handover", """
Dear clients,

After 30 years I'm retiring at the end of September. With your consent your file will transfer to
Rhea Kapoor at Ledgerline, who I trust completely. Her fixed fee will be £540.

Felix Grant
""", thread="tx-handover")
    email("tx-003", "2026-09-22T11:30", "rhea", "Welcome - your 2025-26 return", """
Hi Nia,

Felix has passed your file over. To file in good time I need these by Sunday 15 November:
1. P60 from Westbury College (part-time teaching)
2. Your expenses spreadsheet for the year
3. Pension contribution statements

Shared folder link to follow.
Rhea
""", thread="tx-rhea")
    task("t-tx-1", "Send Rhea P60 + expenses + pension statements", "2026-09-22", due="2026-11-15", project="Admin")
    task("t-tx-2", "Find P60 from Westbury College", "2026-09-22", due="2026-11-08", project="Admin")
    journal("2026-09-22", "Felix has retired, Rhea Kapoor (Ledgerline) is my new accountant. Cheaper too. Need to dig out the P60 - think it's in the blue folder?")


# ---------------------------------------------------------------------------
# Storyline 7: car insurance renewal
# ---------------------------------------------------------------------------
def car() -> None:
    note("Finance/Car.md", "2026-05-01", """
# Car

2017 Toyota Yaris, reg WX17 KDP (fictional plate).
- MOT due 2027-03-02
- Insurance: Brightway, renews 14 November 2026
- Breakdown: through Northmoor Bank account perks
""", updated="2026-10-20", tags=["finance"])
    email("cr-001", "2026-10-10T07:30", "brightway", "Your renewal quote", """
Your car insurance renews on 14 November 2026.
Renewal premium: £612.00 (last year £498.00)
Address on policy: 14 Cotham Rise, Bristol
To accept, do nothing. To discuss, call us.
""", thread="cr-renew")
    journal("2026-10-10", "Brightway want £612 for the car, up from £498. Absolutely not. Also they still have the old address.")
    task("t-cr-1", "Call Brightway: haggle + update address", "2026-10-10", due="2026-11-07", completed="2026-10-20", project="Admin")
    email("cr-002", "2026-10-20T15:12", "brightway", "Policy updated - revised renewal", """
Thanks for calling today.
Address updated to: Flat 3, 22 Alder Street, Bristol
Revised renewal premium: £548.00, renewing 14 November 2026.
""", thread="cr-renew")


# ---------------------------------------------------------------------------
# Storyline 8: Lisbon trip
# ---------------------------------------------------------------------------
def lisbon() -> None:
    note("Travel/Lisbon October.md", "2026-07-02", """
# Lisbon October

Solo trip (Ivy at Marcus's) - Lena's ceramics fair + rest.

- Flights: Aerolis, booking AE7QK2. Originally out Thu 8 Oct, moved to **Fri 9 Oct** (Aerolis cancelled the 8th). Back Tue 13 Oct.
- Hotel: Casa do Rio, Alfama, 9-13 Oct (changed from 8-13)
- Ceramics fair: Feira de Cerâmica, Saturday 10 Oct, with [[Lena Fischer]]
- Must see: tile museum, Lena's friend's studio in Marvila

## After
- Bought two small azulejo tiles for Ivy
- Idea from the fair: sell octopus mugs at the Christmas market (see [[Ember and Clay]])
""", updated="2026-10-14", tags=["travel"])
    email("ls-001", "2026-07-02T21:00", "aerolis", "Booking confirmed AE7QK2", """
Booking reference: AE7QK2
Outbound: Thu 8 Oct 2026, BRS 06:40 -> LIS 09:35
Return:  Tue 13 Oct 2026, LIS 19:10 -> BRS 22:00
Passenger: Ms Nia Okafor
""", thread="ls-flight")
    email("ls-002", "2026-07-02T21:30", "casa", "Reserva confirmada", "Reservation confirmed: 8-13 October 2026, 5 nights, Double room. Ref CDR-2219.", thread="ls-hotel")
    email("ls-003", "2026-09-14T06:00", "aerolis", "Important: change to your booking AE7QK2", """
Unfortunately your flight on Thu 8 Oct has been cancelled.
You have been rebooked on: Fri 9 Oct 2026, BRS 06:40 -> LIS 09:35.
Your return flight is unchanged.
""", thread="ls-flight")
    email("ls-004", "2026-09-14T08:12", "me", "Re: Reserva CDR-2219", "Hello, could you change my reservation to 9-13 October please (4 nights)? My flight was moved.", to="casa", thread="ls-hotel", folder="sent")
    email("ls-005", "2026-09-15T10:00", "casa", "Re: Reserva CDR-2219", "Done - your reservation is now 9-13 October, 4 nights. No fee.", thread="ls-hotel")
    event("ev-ls-trip", "2026-10-08", "2026-10-14", "Lisbon", status="CANCELLED", sequence=1, created="2026-07-02", all_day=True)
    event("ev-ls-trip2", "2026-10-09", "2026-10-14", "Lisbon (Aerolis AE7QK2)", created="2026-09-14", all_day=True)
    event("ev-ls-fair", "2026-10-10T10:00", "2026-10-10T17:00", "Feira de Cerâmica with Lena", location="Lisbon", created="2026-08-01")
    journal("2026-10-10", "The fair! Lena knows everyone. Saw someone selling octopus-handle mugs and immediately thought of Ivy. Could I do a run of those for the Christmas market?")
    journal("2026-10-13", "Home. Ivy loved the tiles. Back to Kestrel tomorrow.")


# ---------------------------------------------------------------------------
# Storyline 9: Ember & Clay - pottery side project (semantic, few keywords)
# ---------------------------------------------------------------------------
def pottery() -> None:
    note("Projects/Ember and Clay.md", "2026-05-18", """
# Ember and Clay

The little pottery thing. Not a business yet - more a way to make something with my hands that isn't a screen.

- Wheel lives in the basement store at Alder Street now
- Firing at [[Lena Fischer]]'s kiln (Kiln House studio), £15 a shelf
- Glazes I like: tenmoku, shino, a speckled oatmeal
- Signature thing: octopus-handle mugs (Ivy's idea, see [[Lisbon October]])

## Christmas market
- Applied for a stall at the Harbourside Christmas Makers Market, 12-13 December
- Accepted 2026-10-24, stall fee £45, pay by 6 November
- Target: 24 mugs, 30 small bowls. Need to start throwing by early November to have time for two firings.
""", updated="2026-10-24", tags=["project", "craft"])
    note("People/Lena Fischer.md", "2026-05-18", "# Lena Fischer\n\n- Runs Kiln House studio, fires my pots\n- lena@kilnhouse.example\n- Took me to the Lisbon ceramics fair\n- Gentle but honest feedback: 'your walls are still too thick'", tags=["person", "craft"])
    email("pt-001", "2026-10-24T13:00", "Harbourside Makers Market <stalls@harboursidemakers.example>", "Stall application accepted", """
Congratulations - your application for a stall at the Harbourside Christmas Makers Market (12-13 December)
has been accepted. Stall fee £45, payable by 6 November to secure your pitch.
""", thread="pt-market")
    task("t-pt-1", "Pay Christmas market stall fee £45", "2026-10-24", due="2026-11-06", project="Ember and Clay")
    task("t-pt-2", "Book two firing slots with Lena for late Nov", "2026-10-24", due="2026-11-10", project="Ember and Clay")
    chat("2026-10-24T13:30", "Lena", "Nia", "I got the market stall!!")
    chat("2026-10-24T13:45", "Lena", "Lena", "Of course you did. Book firings for 20 and 27 Nov, the kiln fills up before Christmas")
    journal("2026-05-18", "First evening at Lena's wheel in months. Hands knew what to do even if the walls came out thick. Felt like breathing.")
    journal("2026-06-21", "Threw six bowls. Two survived trimming. Something about mud on my hands at the end of a screen day.")
    journal("2026-08-30", "Made a clay octopus with Ivy. She wants to sell them. Maybe she's right?")


# ---------------------------------------------------------------------------
# Storyline 10: friends and family odds and ends
# ---------------------------------------------------------------------------
def social() -> None:
    note("People/Sam Petrov.md", "2026-05-01", """
# Sam Petrov

- Oldest friend (since uni). Lives in Redland.
- Birthday 3 October - got them the Kiln House pottery taster voucher
- Borrowed my copy of *The Salt Orchard* in June. Said they'd bring it back on 19 Sept - forgot. Still has it.
- Allergic to cats
""", updated="2026-09-20", tags=["person", "friends"])
    note("People/Grace Okafor.md", "2026-05-01", "# Grace Okafor\n\n- My mum. Lives in Cheltenham.\n- Helps with Ivy in half term\n- Hip replacement booked for January 2027", tags=["person", "family"])
    chat("2026-06-14T22:10", "Sam", "Sam", "can I borrow The Salt Orchard? you won't shut up about it")
    chat("2026-06-14T22:11", "Sam", "Nia", "yes but I want it back this time!!")
    chat("2026-09-20T09:00", "Sam", "Sam", "argh I forgot the book. next time I promise")
    chat("2026-10-03T08:00", "Sam", "Nia", "Happy birthday!! 🎂 voucher is in your inbox")
    email("so-001", "2026-10-03T07:58", "Kiln House <lena@kilnhouse.example>", "Gift voucher for Sam Petrov", "A gift from Nia: one pottery taster session at Kiln House. Voucher code KH-TASTE-0310.", to="sam", folder="sent", thread="so-voucher")
    event("ev-so-sam", "2026-10-03T19:30", "2026-10-03T23:00", "Sam's birthday drinks", location="The Grain Barge", created="2026-09-15")
    chat("2026-09-28T20:00", "Mum", "Grace", "They've given me a date for the hip - 19 January")
    journal("2026-09-28", "Mum's hip op is 19 Jan. Need to plan to go up to Cheltenham for a week after.")
    task("t-so-1", "Get The Salt Orchard back from Sam", "2026-09-20", project="Personal")
