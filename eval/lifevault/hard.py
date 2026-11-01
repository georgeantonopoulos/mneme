"""Hard questions for LifeVault: the kinds the cortex is weakest at.

Written after v4 and the use eval, aimed at what those showed to be hard:
- answers spread over many memories (lists, totals, deadlines across storylines);
- multi-hop links between people and places;
- long-tail details buried in long notes, chats and journals;
- "as of" questions about past states.

None were tried against any system before being committed, and none are tuned afterwards. Every accepted
answer string appears in the evidence memories, because the metric checks whether the answer is in the
retrieved context, not whether a reader could compute it.
"""
from __future__ import annotations

from truth import q


def questions() -> list[dict]:
    s = "hard"
    return [
        # Answers spread over many memories.
        q("hd-01", "aggregation", "List every invoice I've sent Halcyon this year.", "INV-2026-011, 012, 014, 016, 017",
          evidence=["note:Clients/Halcyon Labs.md", "email:hl-002", "email:hl-005", "email:hl-007", "email:hl-011", "email:hl-016"],
          accept=[["011"], ["012"], ["014"], ["016"], ["017"]], split=s),
        q("hd-02", "aggregation", "What payments have landed in my bank account from clients since May?", "£3,600, £4,050, £4,500, £5,000 (Halcyon) and £720 (Bramble)",
          evidence=["email:hl-003", "email:hl-006", "email:hl-014", "email:hl-015", "email:br-004"],
          accept=[["3,600"], ["4,050"], ["4,500"], ["5,000"], ["720"]], split=s),
        q("hd-03", "aggregation", "What deadlines do I have in the first half of November?",
          "3 Nov museum slip + £12, 6 Nov market stall fee, 8 Nov find P60, 10 Nov book firings, 14 Nov car renewal, 15 Nov Rhea's documents",
          evidence=["task:t-iv-2", "task:t-pt-1", "task:t-tx-2", "task:t-pt-2", "task:t-tx-1", "email:cr-002"],
          accept=[["permission", "slip"], ["stall"], ["p60"], ["firing"]], split=s),
        q("hd-04", "aggregation", "What money is still owed to me right now?", "INV-2026-017 £6,000 (due 30 Oct) and the disputed £240 deposit deduction",
          evidence=["email:hl-016", "note:Clients/Halcyon Labs.md", "email:mv-013"], accept=[["6,000"], ["240"]], split=s),
        q("hd-05", "temporal_absolute", "What's on 5 and 6 November?", "5 Nov parents' evening 16:30; 6 Nov physio review 08:15 and the stall fee deadline",
          evidence=["event:ev-iv-pe", "email:iv-003", "event:ev-kn-nov2", "email:kn-002", "task:t-pt-1"],
          accept=[["16:30"], ["08:15"]], split=s),
        q("hd-06", "temporal_absolute", "What is happening on 3 November?", "Kestrel final prototype review at 14:00; museum permission slip and £12 due",
          evidence=["event:ev-hl-review", "email:hl-017", "task:t-iv-2", "email:iv-004"], accept=[["review"], ["permission", "£12"]], split=s),
        q("hd-07", "open_loops", "Who is supposed to get back to me about something?",
          "Halcyon accounts (INV-2026-017), DepositGuard adjudicator (DG-58213), Flowline/Tom on the boiler part",
          evidence=["email:hl-016", "email:mv-013", "chat:Tom (landlord)@2026-10-28T21:30"], accept=[["017"], ["dg-58213", "deposit"], ["boiler", "part"]], split=s),
        # Multi-hop.
        q("hd-08", "multi_hop", "What honest feedback does the person who fires my pots give me?", "'your walls are still too thick' (Lena Fischer)",
          evidence=["note:People/Lena Fischer.md", "note:Projects/Ember and Clay.md"], accept=[["too thick"]], split=s),
        q("hd-09", "multi_hop", "When are my regular meetings with the producer who replaced Priya?", "Thursdays 10:00 with Daniel",
          evidence=["note:People/Daniel Achterberg.md", "email:hl-009"], accept=[["thursday"], ["10:00"]], split=s),
        q("hd-10", "multi_hop", "Who recommended me to the tea shop client?", "A friend of Priya's",
          evidence=["email:br-001"], accept=[["priya"]], split=s),
        q("hd-11", "multi_hop", "Who is looking after Ivy during half term while I work?", "Mum 26-28 Oct, Kickstart holiday club on Thursday 29",
          evidence=["task:t-iv-3", "chat:Mum@2026-10-16T12:05", "chat:Mum@2026-10-16T12:00"], accept=[["kickstart", "holiday club"], ["mum", "grace"]], split=s),
        q("hd-12", "multi_hop", "Which parts of my life does Lena Fischer turn up in?", "Firing pots at Kiln House, the Lisbon ceramics fair, the Christmas market firings",
          evidence=["note:People/Lena Fischer.md", "note:Travel/Lisbon October.md", "chat:Lena@2026-10-24T13:45"], accept=[["kiln"], ["lisbon", "fair"]], split=s),
        # Telling people apart.
        q("hd-13", "entity_disambiguation", "Where does my friend Sam live, and what are they allergic to?", "Redland; cats (Sam Petrov)",
          evidence=["note:People/Sam Petrov.md"], accept=[["redland"], ["cat"]], split=s),
        # Long-tail details.
        q("hd-14", "long_tail", "Which three sync states am I adding to the Kestrel prototype?", "Queued, syncing, failed",
          evidence=["chat:Daniel (Halcyon)@2026-10-22T10:41"], accept=[["queued"], ["syncing"], ["failed"]], split=s),
        q("hd-15", "long_tail", "What exercise did the Spanish squats replace?", "Wall sits",
          evidence=["note:Health/Knee Rehab.md"], accept=[["wall sit"]], split=s),
        q("hd-16", "long_tail", "What painkiller am I allowed for the knee?", "Ibuprofen gel only, not tablets",
          evidence=["note:Health/Knee Rehab.md"], accept=[["gel"]], split=s),
        q("hd-17", "long_tail", "What did I do about showers and Ivy's bath when the boiler died?", "Cold showers at the gym; Ivy bathed at Marcus's",
          evidence=["journal:2026-10-18"], accept=[["gym"], ["marcus"]], split=s),
        q("hd-18", "long_tail", "What did I bring Ivy back from Lisbon?", "Two small azulejo tiles",
          evidence=["note:Travel/Lisbon October.md", "journal:2026-10-13"], accept=[["tile"]], split=s),
        q("hd-19", "long_tail", "What's my car's registration and when is its MOT?", "WX17 KDP; MOT 2027-03-02",
          evidence=["note:Finance/Car.md"], accept=[["wx17"], ["2027-03-02"]], split=s),
        q("hd-20", "long_tail", "Might the tea shop client come back?", "Possibly in 2027 if funding sorts out",
          evidence=["note:People/Josie Bramble.md"], accept=[["2027"]], split=s),
        q("hd-21", "long_tail", "How much was the holding deposit on the new flat?", "£330",
          evidence=["email:mv-002"], accept=[["330"]], split=s),
        q("hd-22", "long_tail", "What is the Kestrel accent colour?", "Marigold",
          evidence=["note:Projects/Kestrel Redesign.md"], accept=[["marigold"]], split=s),
        q("hd-23", "implicit", "Where do I keep my pottery wheel?", "In the basement store at Alder Street",
          evidence=["note:Projects/Ember and Clay.md", "email:mv-001"], accept=[["basement"]], split=s),
        q("hd-24", "preference", "What's the best way to reach Ivy's dad?", "WhatsApp",
          evidence=["note:People/Marcus Hale.md"], accept=[["whatsapp"]], split=s),
        q("hd-25", "temporal_relative", "How late was the July Halcyon invoice paid?", "13 days late (paid 12 September)",
          evidence=["note:Clients/Halcyon Labs.md", "email:hl-014", "email:hl-013"], accept=[["13 days", "12 sep"]], split=s),
        q("hd-26", "temporal_relative", "How much did my car insurance go up by before I haggled?", "From £498 to £612",
          evidence=["email:cr-001", "journal:2026-10-10"], accept=[["498"], ["612"]], split=s),
        # Past states.
        q("hd-27", "historical_state", "As of 2 October, when was my physio review?", "Thursday 5 November, 08:15 (later moved to the 6th)",
          evidence=["email:kn-001", "event:ev-kn-nov"], accept=[["5 november"]], reject=["friday 6 november"],
          as_of="2026-10-02T12:00:00+00:00", split=s),
        q("hd-28", "historical_state", "As of 1 August, what was my rent going to be?", "£1,425 a month on a 15 month term",
          evidence=["email:mv-004", "note:Projects/Flat Move.md"], accept=[["1,425"]], as_of="2026-08-01T12:00:00+00:00", split=s),
        q("hd-29", "historical_state", "As of 10 October, what address did Brightway have for me?", "14 Cotham Rise (the old flat)",
          evidence=["email:cr-001", "journal:2026-10-10"], accept=[["cotham"]], as_of="2026-10-10T20:00:00+00:00", split=s),
        q("hd-30", "historical_state", "What was the Kestrel handoff date before it moved?", "6 November",
          evidence=["email:hl-017", "event:ev-hl-handoff", "note:Projects/Kestrel Redesign.md"], accept=[["6 nov", "2026-11-06"]], split=s),
    ]
