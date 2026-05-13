import json
import sqlite3

from mneme.post_response import detect_resolution_payloads, process_post_response


def test_detects_source_backed_property_purchase_answer():
    user = "When did I purchase Example Terrace flat?"
    assistant = """
Best evidence I found:
- Exchange: 2 September 2022 — solicitor email said exchange today.
- Completion / purchase date: 9 September 2022 — solicitor email said congratulations and attached the SDLT return.

So the clean answer is: completed/purchased on 9 September 2022.
"""
    payloads = detect_resolution_payloads(user, assistant)
    assert len(payloads) == 1
    claims = payloads[0]["claims"]
    assert claims[0]["subject"] == "Example Terrace flat"
    assert claims[0]["predicate"] == "completed_purchase_on"
    assert claims[0]["object"] == "2022-09-09"
    assert claims[0]["status"] == "active"
    assert claims[1]["predicate"] == "exchanged_contracts_on"
    assert claims[1]["object"] == "2022-09-02"


def test_does_not_write_unsourced_answer():
    user = "When did I purchase Example Terrace flat?"
    assistant = "You probably bought it on 9 September 2022."
    assert detect_resolution_payloads(user, assistant) == []


def test_process_post_response_writes_edges(tmp_path):
    vault = tmp_path / "vault"
    db = tmp_path / "mneme.sqlite"
    user = "When did I purchase Example Terrace flat?"
    assistant = """
- Exchange: 2 September 2022 — solicitor email.
- Completion / purchase date: 9 September 2022 — solicitor email with SDLT return.
"""
    result = process_post_response(user, assistant, vault=vault, db=db)
    assert result["detected"] == 1
    assert result["writes"][0]["claims_written"] == 2
    assert (vault / result["writes"][0]["note_path"]).exists()

    con = sqlite3.connect(db)
    rows = con.execute("SELECT relation, status, confidence, strength FROM edges ORDER BY relation").fetchall()
    con.close()
    assert ("completed_purchase_on", "active", 0.93, 0.91) in rows
    assert ("exchanged_contracts_on", "active", 0.91, 0.9) in rows


def test_explicit_payload_block_is_supported():
    assistant = """Done.
```mneme-resolution
{"title":"Fictional fact","claims":[{"subject":"Alpha","predicate":"confirmed_on","object":"2026-01-01","status":"active","confidence":0.95,"strength":0.95,"evidence":"Fictional official source."}]}
```
"""
    payloads = detect_resolution_payloads("irrelevant", assistant)
    assert payloads[0]["title"] == "Fictional fact"
    assert payloads[0]["claims"][0]["subject"] == "Alpha"
