import sqlite3
from pathlib import Path

from mneme.core import init_db
from mneme.neural import build_latent_index, think


def _seed(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("travel", "project", "Athens family travel", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("passport", "task", "Renew passport", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("invoice", "task", "Pay studio invoice", "Projects/business.md", "2026-01-01", "2026-01-01"),
            ("noise", "note", "Garden plants", "Notes/garden.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.executemany(
        """INSERT INTO edges(id,src_id,dst_id,relation,strength,confidence,status,source_path,evidence_text,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("e1", "travel", "passport", "requires", 1.0, 1.0, "active", "Projects/travel.md", "Passport is required before travel", "2026-01-01", "2026-01-01"),
            ("e2", "travel", "noise", "mentions", 1.0, 1.0, "killed", "Notes/garden.md", "Wrong historical link", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_latent_index_is_incremental_and_local(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    first = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    second = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert first["indexed"] == 4
    assert second["indexed"] == 0
    assert second["unchanged"] == 4


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
    passport = next(item for item in result["activated_neurons"] if item["name"] == "Renew passport")
    assert passport["reason"]["kind"] == "synapse"
    assert passport["reason"]["relation"] == "requires"
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
