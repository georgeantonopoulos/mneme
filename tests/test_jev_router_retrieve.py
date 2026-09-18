"""Credential-free tests for the optional Jev router in retrieve_context.

No network access, no API key required. Pins the safety contract: the
router re-orders retrieval items advisorially and degrades silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mneme.core import ingest_vault, retrieve_context


@pytest.fixture()
def db(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "home.md").write_text("# Home\n\nThe family lives in Athens.\n", encoding="utf-8")
    (vault / "rent.md").write_text(
        "# Rent\n\nRent payment is due on the 1st of each month to the landlord.\n", encoding="utf-8"
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=None)
    return db


def test_retrieve_without_router_has_no_report(db):
    result = retrieve_context(db, "when is rent due?", max_items=8)
    assert "router" not in result or result.get("router") is None


def test_retrieve_router_degrades_silently(db, monkeypatch):
    from mneme import jev_router

    def broken(*args, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr(jev_router, "rank_frontier", broken)
    legacy = retrieve_context(db, "when is rent due?", max_items=8)
    routed = retrieve_context(db, "when is rent due?", max_items=8, router="jev")
    assert routed["router"]["mode"] == "jev"
    assert routed["router"]["applied"] is False
    assert routed["router"]["error"]
    assert [i["title"] for i in routed["items"]] == [i["title"] for i in legacy["items"]]
    assert len(routed["items"]) == len(legacy["items"])


def test_retrieve_router_reorders_items(db, monkeypatch):
    from mneme import jev_router

    legacy = retrieve_context(db, "when is rent due?", max_items=8)
    if not legacy["items"]:
        pytest.skip("fixture produced no retrievable items")
    legacy_titles = [i["title"] for i in legacy["items"]]

    def fake_rank(prompt, candidates, **kwargs):
        target = next(
            (c for c in candidates if "rent" in (c.get("evidence") or "").lower()), candidates[0]
        )
        probs = {c["id"]: 0.05 for c in candidates}
        probs[target["id"]] = 1.0
        return {"choice": target["id"], "confidence": 0.9, "probabilities": probs, "error": None}

    monkeypatch.setattr(jev_router, "rank_frontier", fake_rank)
    routed = retrieve_context(db, "when is rent due?", max_items=8, router="jev")
    assert routed["router"]["applied"] is True
    assert routed["router"]["error"] is None
    routed_titles = [i["title"] for i in routed["items"]]
    assert "rent" in routed_titles[0].lower()
    assert set(routed_titles) == set(legacy_titles)  # same set, only reordered
    assert len(routed["items"]) == len(legacy["items"])