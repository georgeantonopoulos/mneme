"""Re-asked questions for the learning-from-use eval.

Every other answerable dev question, reworded the way someone might ask it again weeks later. The wording
was written before any run of the use eval and is never tuned. Each reworded question keeps the original's
evidence, accepted answers and "as of", so it is scored exactly like the original.
"""
from __future__ import annotations

REWORDED: dict[str, str] = {
    "single-01": "How do I email Tomasz?",
    "single-03": "What shade did we choose as the main Kestrel colour?",
    "hop-01": "If Halcyon still hasn't paid the newest invoice, who do I contact?",
    "hop-03": "Who's looking after Ivy the evening the trip form is due?",
    "agg-01": "What's the running total Halcyon Labs has paid me?",
    "agg-03": "Who have I billed this year?",
    "time-02": "What date is the last Kestrel prototype review?",
    "rel-02": "How long after the boiler died did the engineer come out?",
    "upd-01": "What date did I actually move into the new flat?",
    "upd-03": "What time and day is swimming for Ivy now?",
    "upd-05": "What's the car insurance going to cost this year?",
    "upd-07": "When do we hand Kestrel over to the developers?",
    "hist-01": "Before the move, which address was I at when I went to see the new place?",
    "hist-03": "How much a day was Halcyon paying me back in July?",
    "con-01": "Which day do I fly to Lisbon - the 8th or 9th of October?",
    "abs-03": "What was Bramble's payment for the finished logo?",
    "ent-01": "What has Sam told me about how Ivy's swimming is going?",
    "ent-03": "Who's my landlord now, as opposed to the last place?",
    "para-02": "Can I start running again?",
    "tok-01": "What is booking reference AE7QK2 for?",
    "tok-03": "Did the INV-2026-017 money come in?",
    "pref-01": "What is Ivy into these days?",
    "imp-01": "What did the removal company charge?",
    "tail-01": "What made us scrap the campaign wizard idea?",
    "loop-01": "Which things are other people supposed to get back to me on?",
    "safe-01": "Has the bank contacted me about anything lately?",
}


def questions(dev: list[dict]) -> list[dict]:
    by_id = {q["id"]: q for q in dev}
    return [{**by_id[qid], "id": f"re-{qid}", "split": "reask", "question": text, "original": by_id[qid]["question"]}
            for qid, text in REWORDED.items()]
