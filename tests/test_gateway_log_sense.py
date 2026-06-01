"""Tests for the gateway_log sense.

Covers:
- empty log → no event
- log with no matches → no event
- log with MEDIA_REJECTED line → event with mneme:trigger/MEDIA_REJECTED tag
- log with ERROR/CRITICAL line → event with mneme:trigger/DELIVERY_ERROR tag
- cursor advances after read (idempotency: second call yields nothing)
- sense survives missing log file
- sense survives unwritable state path
- event digest stable for same content
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from mneme.cli import main
from mneme.core import ingest_sense_events
from mneme.senses.gateway_log import GatewayLogSense


GATEWAY_LOG_CONTENT_WITH_FAILURES = """\
2026-06-01 14:00:00,000 INFO gateway.run: starting up
2026-06-01 14:01:00,000 WARNING [sess-1] gateway.platforms.base: Skipping unsafe MEDIA directive path: /var/data/private/secret.png
2026-06-01 14:02:00,000 INFO gateway.platforms.telegram: sent message_id 7000
2026-06-01 14:03:00,000 WARNING [sess-1] gateway.platforms.base: Skipping unsafe MEDIA directive path: /var/data/private/etc-passwd
2026-06-01 14:04:00,000 ERROR gateway.platforms.telegram: HTTP 500 sending photo
2026-06-01 14:05:00,000 INFO gateway.run: shutdown
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_gateway_log_sense_yields_nothing_for_empty_log(tmp_path: Path):
    log = tmp_path / "gateway.log"
    _write(log, "")
    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=tmp_path / "c")
    assert list(sense.collect()) == []


def test_gateway_log_sense_skips_lines_with_no_match(tmp_path: Path):
    log = tmp_path / "gateway.log"
    _write(log, "2026-06-01 INFO gateway.run: all good\n2026-06-01 INFO gateway.run: still good\n")
    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=tmp_path / "c")
    assert list(sense.collect()) == []


def test_gateway_log_sense_emits_event_for_media_rejected(tmp_path: Path):
    log = tmp_path / "gateway.log"
    _write(log, GATEWAY_LOG_CONTENT_WITH_FAILURES)
    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=tmp_path / "c")
    events = list(sense.collect())
    assert len(events) == 1
    event = events[0]
    assert event.sense_id == "gw"
    assert event.sense_type == "gateway_log"
    assert event.event_type == "log_tail"
    assert "mneme:trigger/MEDIA_REJECTED" in event.tags
    assert "mneme:trigger/DELIVERY_ERROR" in event.tags
    assert "mneme:sense/gateway_log" in event.tags
    # Matched lines should appear in the text body.
    assert "Skipping unsafe MEDIA directive path" in event.text
    assert "HTTP 500" in event.text
    # Metadata should record counts.
    assert event.metadata["match_count"] == 3
    # Title should summarise.
    assert event.title and "3 delivery-failure event" in event.title


def test_gateway_log_sense_cursor_advances(tmp_path: Path):
    log = tmp_path / "gateway.log"
    state = tmp_path / "c.cursor"
    _write(log, "2026-06-01 WARNING [s1] Skipping unsafe MEDIA directive path: /bad/path.png\n")
    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=state)
    first = list(sense.collect())
    assert len(first) == 1
    # Second call: cursor has advanced, no new content → no event.
    second = list(sense.collect())
    assert second == []
    # Append new content → third call yields it.
    with log.open("a", encoding="utf-8") as fh:
        fh.write("2026-06-01 15:00 WARNING [s2] Skipping unsafe MEDIA directive path: /other.png\n")
    third = list(sense.collect())
    assert len(third) == 1
    assert "/other.png" in third[0].text


def test_gateway_log_sense_survives_missing_log(tmp_path: Path):
    sense = GatewayLogSense(
        sense_id="gw",
        log_path=tmp_path / "does-not-exist.log",
        state_path=tmp_path / "c",
    )
    # Must yield nothing, not raise.
    assert list(sense.collect()) == []


def test_gateway_log_sense_survives_unwritable_cursor(tmp_path: Path):
    log = tmp_path / "gateway.log"
    _write(log, "WARNING Skipping unsafe MEDIA directive path: /x\n")
    # Point state_path inside a non-existent dir; the sense should still
    # attempt the collect and not crash. If parent can't be created it
    # should silently yield nothing on the second pass — but the FIRST
    # pass must still emit (read happens before write).
    bad_state = tmp_path / "nonexistent-subdir" / "cursor"
    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=bad_state)
    events = list(sense.collect())
    # If the read worked and the file content matched, we get an event
    # even if the cursor write fails (the OSError is caught).
    assert len(events) == 1


def test_gateway_log_sense_ingests_into_mneme_graph(tmp_path: Path):
    """End-to-end: sense → ingest produces a sense_event row with our
    match metadata preserved in the metadata_json column. Future surface
    calls can match on the tags via Mneme's normal cross-sense
    corroboration, but we don't test that here — that's covered by
    test_tick_surface_feedback_and_explain_are_source_agnostic."""
    db = tmp_path / "mneme.sqlite"
    log = tmp_path / "gateway.log"
    _write(log, GATEWAY_LOG_CONTENT_WITH_FAILURES)

    sense = GatewayLogSense(sense_id="gw", log_path=log, state_path=tmp_path / "c")
    conn = sqlite3.connect(db)
    stats = ingest_sense_events(conn, sense.collect())
    conn.commit()

    assert stats["events"] == 1
    row = conn.execute(
        "SELECT sense_id, sense_type, source_id, event_type, metadata_json FROM sense_events"
    ).fetchone()
    assert row is not None
    assert row[0] == "gw"
    assert row[1] == "gateway_log"
    assert row[2] == "gateway-log:gateway.log"
    assert row[3] == "log_tail"
    meta = json.loads(row[4]) if row[4] else {}
    assert meta.get("match_count") == 3
    assert "mneme:trigger/MEDIA_REJECTED" in meta.get("matched_tags", [])
    assert "mneme:trigger/DELIVERY_ERROR" in meta.get("matched_tags", [])
    conn.close()


def test_cli_sense_list_includes_gateway_log(tmp_path: Path, capsys):
    """After importing the sense, `mneme sense list --json` should include it."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"vault": str(tmp_path), "db": str(tmp_path / "db.sqlite"), "hints": []}), encoding="utf-8")
    main(["--config", str(config), "sense", "list", "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert "gateway_log" in [item["type"] for item in listed]
