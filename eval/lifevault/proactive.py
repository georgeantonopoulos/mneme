"""What a proactive brain should, and should not, raise on its own: the answer key for run_reflect.py.

Written before any reflection code existed. Two moments:

    act 1, 2026-10-29 18:00   (data/)        open loops and deadlines in the next fortnight
    act 2, 2026-11-12 18:00   (data_act2/)   what changed since, and what has closed

A thought counts as surfacing an item when it cites one of the item's evidence memories, or when its text
contains one string from every group in ``match``. A thought is stale when its text contains one string from
every group of a ``stale`` entry: it raises something that is already resolved. Thoughts that match nothing
are reported for reading by hand. They are not counted as wrong.

``links`` are real connections between memories that perception did not make (none of the eight is linked
after act-1 perception). Five pairs sit in different areas, and three share an area but not a topic.
"""
from __future__ import annotations

ACT1_NOW = "2026-10-29T18:00:00+00:00"
ACT2_NOW = "2026-11-12T18:00:00+00:00"


def _item(iid, text, *, evidence, match):
    return {"id": iid, "text": text, "evidence": evidence, "match": match}


ACT1_SURFACE = [
    _item("p-inv", "INV-2026-017 (£6,000) is due 30 Oct and not yet paid",
          evidence=["email:hl-016", "task:t-hl-4"], match=[["017", "6,000"], ["due", "paid", "chase", "payment"]]),
    _item("p-slip", "Museum permission slip and £12 due 3 Nov",
          evidence=["task:t-iv-2", "email:iv-004"], match=[["slip", "museum", "parentpay"]]),
    _item("p-review", "Kestrel final prototype review on 3 Nov (and the colour-token audit due 2 Nov)",
          evidence=["event:ev-hl-review", "task:t-hl-2"], match=[["review", "audit"], ["3 nov", "2 nov", "kestrel"]]),
    _item("p-stall", "Christmas market stall fee £45 due 6 Nov",
          evidence=["task:t-pt-1", "email:pt-001"], match=[["stall", "£45", "market fee"]]),
    _item("p-firing", "Book the two firing slots with Lena (20 and 27 Nov) by 10 Nov",
          evidence=["task:t-pt-2", "chat:Lena@2026-10-24T13:45"], match=[["firing", "kiln"]]),
    _item("p-boiler", "Boiler part still awaited; chase Tom",
          evidence=["task:t-mv-4", "chat:Tom (landlord)@2026-10-28T21:30"], match=[["boiler", "diverter"]]),
    _item("p-tax", "Rhea needs the P60, expenses and pension statements by 15 Nov (find the P60 by 8 Nov)",
          evidence=["task:t-tx-1", "task:t-tx-2", "email:tx-003"], match=[["p60", "rhea", "accountant"]]),
    _item("p-phish", "Warning: the 26 Oct 'bank' email is phishing",
          evidence=["email:sp-003"], match=[["phishing", "scam", "suspicious", "northmoor-verify"]]),
    _item("p-days", "Parents' evening 5 Nov 16:30, then physio review 6 Nov 08:15",
          evidence=["event:ev-iv-pe", "event:ev-kn-nov2", "email:kn-002"], match=[["parents", "physio"]]),
]

ACT1_STALE = [
    {"id": "s-insurance-address", "match": [["insurance", "brightway"], ["address", "cotham"], ["update", "change", "still"]]},
    {"id": "s-swim-fee", "match": [["swim"], ["£96", "fee"]]},
    {"id": "s-childcare", "match": [["half term", "half-term", "childcare"], ["sort", "need", "plan", "arrange"]]},
    {"id": "s-lisbon", "match": [["lisbon", "ae7qk2", "casa do rio"], ["flight", "hotel", "book"]]},
]

ACT2_SURFACE = [
    _item("q-handoff", "Kestrel dev handoff moved again, to 27 Nov",
          evidence=["email:a2-006", "event:ev-a2-handoff"], match=[["handoff"], ["27"]]),
    _item("q-pension", "Rhea still needs the pension statements by 15 Nov",
          evidence=["email:a2-004", "task:t-tx-1"], match=[["pension"]]),
    _item("q-firing", "Firing slots with Lena still not booked (was due 10 Nov)",
          evidence=["task:t-pt-2"], match=[["firing", "kiln"]]),
    _item("q-market", "Market dates corrected to 13-14 Dec",
          evidence=["email:a2-003"], match=[["market"], ["13", "14 dec"]]),
    _item("q-deposit", "DepositGuard awarded £160; payment due within 10 working days",
          evidence=["email:a2-005"], match=[["deposit", "dg-58213", "depositguard"], ["160"]]),
]

ACT2_STALE = [
    {"id": "s-invoice-unpaid", "match": [["017", "6,000"], ["unpaid", "not paid", "not been paid", "overdue", "outstanding", "chase"]]},
    {"id": "s-boiler-broken", "match": [["boiler", "diverter"], ["awaiting", "waiting", "chase", "still", "part"]]},
    {"id": "s-book", "match": [["salt orchard", "book"], ["still has", "get back", "return", "chase"]]},
    {"id": "s-slip", "match": [["slip", "museum"], ["due", "sign", "pay"]]},
    {"id": "s-stall-fee", "match": [["stall"], ["£45", "fee"], ["due", "pay"]]},
    {"id": "s-old-handoff", "match": [["handoff"], ["20 nov", "20 november"]]},
]

LINKS = [
    {"id": "l-lena-lisbon", "a": "note:People/Lena Fischer.md", "b": "note:Travel/Lisbon October.md",
     "why": "the person who fires the pots took Nia to the Lisbon ceramics fair"},
    {"id": "l-knee-flat", "a": "note:Health/Knee Rehab.md", "b": "note:Projects/Flat Move.md",
     "why": "the flat had to be ground floor or have a lift because of the knee"},
    {"id": "l-ivy-mugs", "a": "note:People/Ivy.md", "b": "note:Projects/Ember and Clay.md",
     "why": "Ivy's octopus obsession is behind the octopus-handle mugs"},
    {"id": "l-priya-bramble", "a": "email:br-001", "b": "note:People/Priya Raman.md",
     "why": "Bramble came through a friend of Priya's"},
    {"id": "l-boiler-marcus", "a": "journal:2026-10-18", "b": "note:People/Marcus Hale.md",
     "why": "Ivy bathed at Marcus's while the boiler was dead"},
    {"id": "l-insurance-move", "a": "email:cr-001", "b": "note:Projects/Flat Move.md",
     "why": "the insurance still had the old address, an open item on the move"},
    {"id": "l-wheel-basement", "a": "note:Projects/Ember and Clay.md", "b": "email:mv-001",
     "why": "the wheel lives in the basement store Tomasz offered for pottery"},
    {"id": "l-bramble-lena", "a": "journal:2026-08-20", "b": "note:People/Lena Fischer.md",
     "why": "after Bramble cancelled, Nia thought of pitching to Lena's studio"},
]
