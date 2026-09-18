"""Credential-free tests for the optional Jev router in agent preflight.

No network access, no API key required. Pins the safety contract: the
router reorders current world assertions advisorially and degrades silently
on any failure.
"""

from __future__ import annotations

import pytest

from mneme import jev_router
from mneme.agent import agent_preflight


def _fake_db(tmp_path):
    """Build a minimal DB with current world assertions via the world model CLI paths.

    Uses the same schema helpers as the runtime so list_assertions works.
    """
    import sqlite3

    from mneme.core import ingest_vault, now_iso, stable_id

    db = tmp_path / "preflight.sqlite"
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "home.md").write_text("# Home\n\nThe family lives in Athens.\n", encoding="utf-8")
    ingest_vault(vault, db, hints=None)

    from mneme.world_model.schema import ensure_world_model_schema
    from mneme.world_model.state import write_assertions

    conn = sqlite3.connect(db)
    ensure_world_model_schema(conn)
    write_assertions(
        conn,
        [
            {
                "subject": "Athens Home",
                "predicate": "located_in",
                "object_name": "Athens",
                "confidence": 1.0,
                "certainty": "user_confirmed",
                "evidence_text": "test fixture evidence",
                "source_type": "user_confirmed",
                "status": "current",
                "metadata": {"research_resolution": True},
            },
            {
                "subject": "Rent Payment",
                "predicate": "due_on",
                "object_name": "the 1st",
                "confidence": 1.0,
                "certainty": "user_confirmed",
                "evidence_text": "test fixture evidence",
                "source_type": "user_confirmed",
                "status": "current",
                "metadata": {"research_resolution": True},
            },
            {
                "subject": "Dog Lexie",
                "predicate": "vaccine_due",
                "object_name": "October",
                "confidence": 1.0,
                "certainty": "user_confirmed",
                "evidence_text": "test fixture evidence",
                "source_type": "user_confirmed",
                "status": "current",
                "metadata": {"research_resolution": True},
            },
        ],
        source_path="tests/fixture",
    )
    conn.commit()
    conn.close()
    return db


def test_preflight_without_router_is_untouched(tmp_path):
    db = _fake_db(tmp_path)
    result = agent_preflight(db, "rent question")
    assert result["router"] is None
    assert result["world"]["current_assertions"]


def test_preflight_router_degrades_silently(tmp_path, monkeypatch):
    db = _fake_db(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr(jev_router, "rank_frontier", broken)
    result = agent_preflight(db, "rent question", router="jev")
    assert result["router"]["mode"] == "jev"
    assert result["router"]["applied"] is False
    assert result["router"]["error"]
    assert result["world"]["current_assertions"]  # order preserved, nothing lost


def test_preflight_router_reorders_assertions(tmp_path, monkeypatch):
    db = _fake_db(tmp_path)
    legacy = agent_preflight(db, "when is rent due?")
    legacy_order = [a["subject_name"] for a in legacy["world"]["current_assertions"]]

    def fake_rank(prompt, candidates, **kwargs):
        # Push the Rent Payment assertion to the top with high probability.
        rent = next(c for c in candidates if "Rent" in (c.get("evidence") or ""))
        probs = {c["id"]: 0.05 for c in candidates}
        probs[rent["id"]] = 1.0
        return {"choice": rent["id"], "confidence": 0.9, "probabilities": probs, "error": None}

    monkeypatch.setattr(jev_router, "rank_frontier", fake_rank)
    routed = agent_preflight(db, "when is rent due?", router="jev")
    assert routed["router"]["applied"] is True
    assert routed["router"]["error"] is None
    routed_order = [a["subject_name"] for a in routed["world"]["current_assertions"]]
    assert routed_order[0] == "Rent Payment"
    assert set(routed_order) == set(legacy_order)  # same set, only reordered