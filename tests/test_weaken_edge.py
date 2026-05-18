"""Tests for weaken_edge — gentle negative-feedback edge reduction."""

import json, sqlite3
from pathlib import Path

from mneme.core import (
    ingest_vault,
    log_edge_event,
    weaken_edge,
    upsert_edge,
)


def test_weaken_edge_reduces_strength_and_logs_feedback(tmp_path: Path):
    """Weakening reduces strength, preserves status, and records an audit event."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nRelated: [[Beta]]\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    edge = conn.execute("SELECT * FROM edges WHERE relation='links_to'").fetchone()
    assert edge is not None

    before_strength = float(edge["strength"])
    result = weaken_edge(db, edge["id"], reason="user dismissed edge proposal", factor=0.5)

    conn2 = sqlite3.connect(db)
    conn2.row_factory = sqlite3.Row
    updated = conn2.execute("SELECT * FROM edges WHERE id=?", (edge["id"],)).fetchone()
    logs = conn2.execute(
        "SELECT event, actor, thinking_json FROM edge_debug_log WHERE edge_id=? ORDER BY created_at",
        (edge["id"],),
    ).fetchall()
    conn2.close()

    assert result["weakened"] == 1
    assert result["previous_strength"] == before_strength
    assert result["strength"] == round(before_strength * 0.5, 6)
    assert result["status"] == edge["status"]
    assert float(updated["strength"]) == result["strength"]

    weaken_events = [r for r in logs if r["event"] == "weakened"]
    assert len(weaken_events) == 1
    thinking = json.loads(weaken_events[0]["thinking_json"])
    assert thinking["reason"] == "user dismissed edge proposal"
    assert thinking["factor"] == 0.5
    assert thinking["previous_strength"] == before_strength


def test_weaken_edge_demotes_weak_active_edge_to_candidate(tmp_path: Path):
    """An active edge whose strength falls below 0.10 is reclassified as candidate."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)  # needed to init schema

    conn = sqlite3.connect(db)
    src = upsert_edge(conn, "X", "Y", "links_to", "x.md", "[[Y]]", 1.0, status="active", strength=0.19)
    conn.commit()
    # Apply a strong enough reduction to push below 0.10 threshold
    result = weaken_edge(db, src, reason="almost kill", factor=0.3)
    conn2 = sqlite3.connect(db)
    conn2.row_factory = sqlite3.Row
    updated = conn2.execute("SELECT status, strength FROM edges WHERE id=?", (src,)).fetchone()
    conn2.close()

    assert result["status"] == "candidate"
    assert updated["status"] == "candidate"
    assert float(updated["strength"]) < 0.10


def test_weaken_edge_respects_floor(tmp_path: Path):
    """The floor parameter prevents strength from dropping below it."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    src = upsert_edge(conn, "A", "B", "links_to", "a.md", "[[B]]", 1.0, strength=0.5)
    conn.commit()
    result = weaken_edge(db, src, reason="floor-check", factor=0.1, floor=0.3)
    assert result["strength"] == 0.3


def test_weaken_edge_unknown_id_returns_error(tmp_path: Path):
    """A missing edge returns a not-found error dict, not an exception."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    result = weaken_edge(db, "nonexistent-ID", reason="test")
    assert result["weakened"] == 0
    assert result["error"] == "not_found"


def test_weaken_edge_does_not_touch_killed_edge(tmp_path: Path):
    """Already killed edges are left unchanged by weaken."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    killed = upsert_edge(conn, "K1", "K2", "links_to", "k.md", "[[K2]]", 0.5, status="killed", strength=0.0)
    conn.commit()
    result = weaken_edge(db, killed, reason="should-not-change", factor=0.5)
    assert result["weakened"] == 0
