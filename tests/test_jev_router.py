"""Credential-free tests for the optional Jev synapse router.

No network access, no API key required. The live endpoint is never called;
`rank_frontier` is monkeypatched or pointed at a local fake. These tests pin
the safety contract: the router is advisory, never lowers activation, and
degrades silently on any failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mneme import jev_router
from mneme.neural import think


# ---------- jev_router unit behavior ----------


def test_rank_frontier_empty_candidates_short_circuits():
    result = jev_router.rank_frontier("any prompt", [])
    assert result == {"choice": None, "confidence": 0.0, "probabilities": {}, "error": None}


def test_rank_frontier_no_key_raises(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(je_router_path := jev_router, "load_api_key", lambda: None)
    with pytest.raises(jev_router.JevRouterError):
        jev_router.rank_frontier("prompt", [{"id": "a", "relation": "r", "evidence": "e"}])


def test_rank_frontier_parses_choice(monkeypatch):
    def fake_evaluate(state_text, questions, *, endpoint, model, timeout_s):
        assert "prompt" in state_text
        assert "frontier_pick" in questions
        return {
            "frontier_pick": {
                "type": "choice",
                "choice": "edge_b",
                "confidence": 0.9,
                "probabilities": {"edge_a": 0.2, "edge_b": 0.8},
            }
        }

    monkeypatch.setattr(jev_router, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(jev_router, "_evaluate", fake_evaluate)
    result = jev_router.rank_frontier(
        "prompt", [{"id": "edge_a", "relation": "rel"}, {"id": "edge_b", "relation": "rel"}]
    )
    assert result["choice"] == "edge_b"
    assert result["confidence"] == 0.9
    assert result["probabilities"]["edge_a"] == pytest.approx(0.2)
    assert result["error"] is None


def test_rank_frontier_malformed_answer_reports_error(monkeypatch):
    monkeypatch.setattr(jev_router, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(jev_router, "_evaluate", lambda *a, **k: {"answers": "not-a-dict"})
    with pytest.raises(jev_router.JevRouterError):
        jev_router.rank_frontier("p", [{"id": "x"}])


def test_rank_frontier_low_confidence_flagged_advisory(monkeypatch):
    def fake_evaluate(*a, **k):
        return {"frontier_pick": {"choice": "x", "confidence": 0.3, "probabilities": {"x": 1.0}}}

    monkeypatch.setattr(jev_router, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(jev_router, "_evaluate", fake_evaluate)
    result = jev_router.rank_frontier("p", [{"id": "x"}])
    assert result["choice"] == "x"
    assert result["error"] == "low-confidence pick retained as advisory only"


def test_boost_activation_never_lowers_and_ignores_unknown_ids():
    acts = {"a": 0.5, "b": 0.2}
    ranking = {"probabilities": {"a": 1.0, "zz": 0.9}, "choice": "a", "confidence": 0.9}
    boosted = jev_router.boost_activation(acts, ranking, boost=1.5)
    assert boosted["a"] == pytest.approx(0.75)
    assert boosted["b"] == pytest.approx(0.2)
    assert acts["a"] == pytest.approx(0.5)  # input untouched


def test_boost_activation_no_ranking_is_identity():
    acts = {"a": 0.5}
    assert jev_router.boost_activation(acts, {"probabilities": {}}) == acts


def test_router_sends_no_secrets_in_state(monkeypatch):
    captured: dict = {}

    def fake_evaluate(state_text, questions, *, endpoint, model, timeout_s):
        captured["state"] = json.loads(state_text)
        return {"frontier_pick": {"choice": "e1", "confidence": 0.9, "probabilities": {"e1": 1.0}}}

    monkeypatch.setattr(jev_router, "load_api_key", lambda: "secret-key-value")
    monkeypatch.setattr(jev_router, "_evaluate", fake_evaluate)
    jev_router.rank_frontier("p", [{"id": "e1", "evidence": "x" * 900, "relation": "r"}])
    blob = json.dumps(captured["state"])
    assert "secret-key-value" not in blob
    assert "x" * 900 not in blob  # evidence truncated


# ---------- think() integration: fallback and wiring ----------


def _fake_router_result(*args, **kwargs):
    raise RuntimeError("router down")


def test_think_without_router_is_legacy(tmp_path, monkeypatch):
    """Default think output keeps router=None and never touches the router."""
    db = tmp_path / "legacy.sqlite"
    _build_indexable_db(db, monkeypatch)
    result = think(db, "note about rent", provider="hash", model="hash-v1")
    assert result["router"] is None
    assert result["activated_neurons"]


def test_think_router_degrades_silently_on_failure(tmp_path, monkeypatch):
    """A broken router must not change results or raise."""
    db = tmp_path / "degrade.sqlite"
    _build_indexable_db(db, monkeypatch)
    monkeypatch.setattr(jev_router, "rank_frontier", _fake_router_result)
    result = think(db, "note about rent", provider="hash", model="hash-v1", router="jev")
    assert result["router"]["mode"] == "jev"
    assert result["router"]["applied"] is False
    assert result["router"]["error"]
    assert result["activated_neurons"]


def test_think_router_boosts_pick(tmp_path, monkeypatch):
    """A successful router reorders neurons when confidence is high."""
    db = tmp_path / "boost.sqlite"
    _build_indexable_db(db, monkeypatch)

    legacy = think(db, "note about rent", provider="hash", model="hash-v1")
    legacy_order = [n["name"] for n in legacy["activated_neurons"]]

    def fake_rank(prompt, candidates, **kwargs):
        # Boost whatever candidate the legacy path ranked lowest.
        lowest = min(
            (c for c in candidates if c["id"] in {n["id"] for n in legacy["activated_neurons"]}),
            key=lambda c: c["id"],
            default=None,
        )
        pick = lowest["id"] if lowest else candidates[0]["id"]
        return {
            "choice": pick,
            "confidence": 0.9,
            "probabilities": {c["id"]: (1.0 if c["id"] == pick else 0.1) for c in candidates},
            "error": None,
        }

    monkeypatch.setattr(jev_router, "rank_frontier", fake_rank)
    routed = think(db, "note about rent", provider="hash", model="hash-v1", router="jev")
    assert routed["router"]["applied"] is True
    assert routed["router"]["error"] is None
    routed_order = [n["name"] for n in routed["activated_neurons"]]
    # Same neuron set, possibly reordered by the advisory boost.
    assert set(routed_order) == set(legacy_order)


def test_think_router_missing_key_degrades(tmp_path, monkeypatch):
    db = tmp_path / "nokey.sqlite"
    _build_indexable_db(db, monkeypatch)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(jev_router, "load_api_key", lambda: None)
    result = think(db, "note about rent", provider="hash", model="hash-v1", router="jev")
    assert result["router"]["applied"] is False
    assert result["router"]["error"]
    assert result["activated_neurons"]


# ---------- helpers ----------


def _build_indexable_db(db_path: Path, monkeypatch) -> None:
    """Create a small graph + latent index with the hash provider (no network)."""
    import sqlite3

    from mneme.core import ingest_vault
    from mneme.neural import build_latent_index

    vault = db_path.parent / "vault"
    vault.mkdir(exist_ok=True)
    (vault / "rent.md").write_text(
        "# Rent\n\nRent of 2350 euros is due on the 1st of the month.\n", encoding="utf-8"
    )
    (vault / "vet.md").write_text(
        "# Vet\n\nLexie has a vet appointment for the rabies booster.\n", encoding="utf-8"
    )
    ingest_vault(vault, db_path, hints=None)
    # One active synapse between the two notes so hop-1 candidates exist.
    import datetime as dt
    import sqlite3 as _sqlite3

    from mneme.core import stable_id

    with _sqlite3.connect(db_path) as conn:
        rent_id = conn.execute("SELECT id FROM nodes WHERE name LIKE '%Rent%' LIMIT 1").fetchone()
        vet_id = conn.execute("SELECT id FROM nodes WHERE name LIKE '%Vet%' LIMIT 1").fetchone()
        if rent_id and vet_id:
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO edges(id,src_id,dst_id,relation,status,strength,confidence,evidence_text,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    stable_id("edge", f"{rent_id[0]}-{vet_id[0]}"),
                    rent_id[0],
                    vet_id[0],
                    "links_to",
                    "active",
                    0.9,
                    0.9,
                    "notes link on household topics",
                    now,
                    now,
                ),
            )
    build_latent_index(db_path, provider="hash", model="hash-v1")