import sqlite3
from pathlib import Path

import pytest

import mneme.neural as neural
from mneme.core import init_db
from mneme.neural import _neuron_rows, _neuron_text, build_latent_index, think


def _seed(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("travel", "project", "Athens family travel", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("passport", "task", "Renew passport", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("invoice", "task", "Pay studio invoice", "Projects/business.md", "2026-01-01", "2026-01-01"),
            ("noise", "note", "Garden plants", "Notes/garden.md", "2026-01-01", "2026-01-01"),
            ("rumor", "task", "Unverified airport rumor", "Notes/rumor.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.executemany(
        """INSERT INTO edges(id,src_id,dst_id,relation,strength,confidence,status,source_path,evidence_text,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("e1", "travel", "passport", "requires", 1.0, 1.0, "active", "Projects/travel.md", "Passport is required before travel", "2026-01-01", "2026-01-01"),
            ("e2", "travel", "noise", "mentions", 1.0, 1.0, "killed", "Notes/garden.md", "Wrong historical link", "2026-01-01", "2026-01-01"),
            ("e3", "travel", "rumor", "might_require", 1.0, 1.0, "candidate", "Notes/rumor.md", "Unverified candidate", "2026-01-01", "2026-01-01"),
            ("e4", "travel", "noise", "forgotten_link", 0.0, 1.0, "active", "Notes/garden.md", "Forgotten evidence", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_latent_index_is_incremental_and_local(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    first = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    second = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert first["indexed"] == 5
    assert second["indexed"] == 0
    assert second["unchanged"] == 5
    assert second["dimensions"] == 64
    conn.execute("DELETE FROM nodes WHERE id='noise'")
    third = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert third["removed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM latent_neurons").fetchone()[0] == 4


def test_dimension_change_reindexes_all_hash_vectors(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)

    first = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    second = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=32)

    assert first["indexed"] == 5
    assert second["indexed"] == 5
    assert second["unchanged"] == 0
    assert {row[0] for row in conn.execute("SELECT dimensions FROM latent_neurons")} == {32}


def test_think_rejects_changed_ollama_embedding_dimensions(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)

    monkeypatch.setattr(
        neural,
        "embed_texts",
        lambda texts, **_kwargs: [[1.0, 0.0, 0.0] for _text in texts],
    )
    build_latent_index(conn, provider="ollama", model="mutable-model")

    monkeypatch.setattr(
        neural,
        "embed_texts",
        lambda texts, **_kwargs: [[1.0, 0.0] for _text in texts],
    )
    with pytest.raises(ValueError, match=r"embedding dimensions changed from 3 to 2.*--rebuild"):
        think(conn, "family travel", provider="ollama", model="mutable-model")


def test_zero_weight_edges_are_not_indexed_as_synaptic_evidence(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _seed(conn)

    travel = next(row for row in _neuron_rows(conn) if row["id"] == "travel")

    assert "Forgotten evidence" not in _neuron_text(travel)


def test_public_neural_apis_preserve_caller_row_factory(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    original = lambda _cursor, row: tuple(row)
    conn.row_factory = original

    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert conn.row_factory is original
    think(conn, "family travel", provider="hash", model="hash-v1", seeds=1, hops=0)
    assert conn.row_factory is original


def test_think_seeds_latently_and_spreads_through_active_synapses(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "family travel to Athens", provider="hash", model="hash-v1", seeds=1, hops=2)
    names = [item["name"] for item in result["activated_neurons"]]
    assert names[0] == "Athens family travel"
    assert "Renew passport" in names
    assert "Garden plants" not in names
    assert "Unverified airport rumor" not in names
    passport = next(item for item in result["activated_neurons"] if item["name"] == "Renew passport")
    assert passport["reason"]["kind"] == "synapse"
    assert passport["reason"]["relation"] == "requires"
    assert all(item["truth_policy"] == "provenance_not_fact" for item in result["activated_neurons"])
    assert result["contract"] == {"name": "mneme-agent-brain", "version": "mneme-agent-brain-v1"}
    assert result["instructions"].startswith("Use these activations")


def test_think_refuses_an_unbuilt_index(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    try:
        think(conn, "travel", provider="hash", model="hash-v1")
    except ValueError as exc:
        assert "run `mneme index` first" in str(exc)
    else:
        raise AssertionError("think should require an explicit latent index")
