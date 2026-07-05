from __future__ import annotations

import sqlite3
from pathlib import Path

from mneme.core import init_db
from mneme.world_model.aliases import (
    add_alias,
    ensure_alias_schema,
    list_aliases,
    merge_subject,
    resolve_subject,
)
from mneme.world_model.schema import ensure_world_model_schema
from mneme.world_model.state import recompute_current


def _conn(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    ensure_world_model_schema(conn)
    return conn


def test_resolve_is_identity_without_table(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    init_db(conn)
    # No alias table created yet -> resolver must be a safe no-op.
    assert resolve_subject(conn, "St James") == "St James"


def test_add_and_resolve(tmp_path: Path):
    conn = _conn(tmp_path / "m.sqlite")
    add_alias(conn, "the landlord", "Berkeley Group")
    add_alias(conn, "St James", "Berkeley Group")
    assert resolve_subject(conn, "the landlord") == "Berkeley Group"
    assert resolve_subject(conn, "St James") == "Berkeley Group"
    # Case/space-insensitive.
    assert resolve_subject(conn, "  THE   Landlord ") == "Berkeley Group"
    # Unknown name is returned unchanged.
    assert resolve_subject(conn, "Someone Else") == "Someone Else"


def test_chain_is_collapsed_flat(tmp_path: Path):
    conn = _conn(tmp_path / "m.sqlite")
    add_alias(conn, "SJ", "St James")
    # Now make St James itself an alias -> SJ must repoint to the ultimate canonical.
    add_alias(conn, "St James", "Berkeley Group")
    assert resolve_subject(conn, "SJ") == "Berkeley Group"
    assert resolve_subject(conn, "St James") == "Berkeley Group"


def test_merge_subject_reconciles_existing_assertions(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    conn = _conn(db)
    ensure_alias_schema(conn)
    # Two 'current' assertions about the same real entity under different names.
    for sid, subject in (("a1", "St James"), ("a2", "the landlord")):
        conn.execute(
            """INSERT INTO world_state_assertions(
                 id,subject_name,subject_type,predicate,object_value,state_type,status,
                 confidence,evidence_text,source_path,source_type,created_at,updated_at,valid_from
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, subject, "entity", "dispute_status", "open", "belief", "current",
             0.9, "evidence", f"notes/{sid}.md", "research", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", f"2026-01-0{1 if sid=='a1' else 2}T00:00:00+00:00"),
        )
    conn.commit()

    # Before merge: two independent current chains.
    current_before = conn.execute(
        "SELECT COUNT(*) FROM world_state_assertions WHERE status='current'"
    ).fetchone()[0]
    assert current_before == 2

    result = merge_subject(conn, "the landlord", "St James")
    conn.commit()
    assert result["assertions_rewritten"] == 1
    assert result["canonical"] == "St James"

    # After merge: single current for the canonical subject+predicate.
    rows = conn.execute(
        "SELECT status FROM world_state_assertions WHERE lower(subject_name)='st james' AND predicate='dispute_status'"
    ).fetchall()
    statuses = sorted(r[0] for r in rows)
    assert statuses.count("current") == 1
    assert statuses.count("superseded") == 1
    assert resolve_subject(conn, "the landlord") == "St James"


def test_merge_subject_dry_run_mutates_nothing(tmp_path: Path):
    db = tmp_path / "m.sqlite"
    conn = _conn(db)
    conn.execute(
        """INSERT INTO world_state_assertions(
             id,subject_name,subject_type,predicate,object_value,state_type,status,
             confidence,evidence_text,source_path,source_type,created_at,updated_at
           ) VALUES('x','the landlord','entity','pays','no','belief','current',0.9,'e','n.md','research','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')""",
    )
    conn.commit()
    result = merge_subject(conn, "the landlord", "St James", dry_run=True)
    assert result["dry_run"] is True
    assert result["assertions_rewritten"] == 1
    # No alias persisted, no row rewritten.
    assert list_aliases(conn) == []
    row = conn.execute("SELECT subject_name FROM world_state_assertions WHERE id='x'").fetchone()
    assert row[0] == "the landlord"

