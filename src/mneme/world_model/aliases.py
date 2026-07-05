from __future__ import annotations

"""Canonical entity resolution for the world model.

Motivation
----------
World-state assertions key on ``subject_name`` (see ``state.assertion_id`` and
``state.recompute_current``). Reconciliation of *current* vs *superseded* is
done with ``WHERE lower(subject_name)=lower(?)``. That means three surface
forms of the *same* entity — "St James", "Berkeley Group", "the landlord" —
produce three independent current-assertion chains that never meet. Cortex
routing, label matching, and prediction subjects all inherit that fragmentation.

This module adds a small, durable alias table and a resolver so that writes can
be normalised to a single canonical name, plus a retroactive ``merge_subject``
that rewrites already-stored rows and recomputes the affected current pointers.

Design rules
------------
* Aliases are stored **flat**: an alias always points directly at a canonical
  name, never at another alias. ``add_alias`` collapses chains on insert so
  resolution is a single lookup and cycles are impossible.
* The table lives outside ``init_db`` like the rest of the world model; callers
  that only touch the rebuildable graph never create it. ``resolve_subject`` is
  a no-op that returns its input unchanged when the table is absent, so existing
  graph-only and world-model callers keep working with zero behaviour change
  until an alias is actually registered.
"""

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _norm(value: str) -> str:
    # Identical normalisation to world_model.state._norm so canonical keys line
    # up with the existing subject_name reconciliation.
    return " ".join(str(value or "").strip().casefold().split())


def ensure_alias_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_aliases(
          alias_norm TEXT PRIMARY KEY,
          alias_name TEXT NOT NULL,
          canonical_name TEXT NOT NULL,
          canonical_norm TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          confidence REAL NOT NULL DEFAULT 1.0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alias_canonical ON entity_aliases(canonical_norm)"
    )


def _alias_table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_aliases'"
        ).fetchone()
        is not None
    )


def resolve_subject(conn: sqlite3.Connection, name: str) -> str:
    """Return the canonical display name for ``name``.

    Safe to call unconditionally: returns ``name`` unchanged when there is no
    alias table or no matching alias. Never follows more than one hop because
    ``add_alias`` keeps the table flat.
    """

    if not _alias_table_exists(conn):
        return name
    row = conn.execute(
        "SELECT canonical_name FROM entity_aliases WHERE alias_norm=?",
        (_norm(name),),
    ).fetchone()
    if row is None:
        return name
    canonical = row[0] if not isinstance(row, sqlite3.Row) else row["canonical_name"]
    return str(canonical)


def add_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    *,
    source: str = "manual",
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Register ``alias`` -> ``canonical``.

    Chain-collapsing: if ``canonical`` is itself an alias, the ultimate
    canonical is used, so the table stays one hop deep. Refuses no-ops and
    self-references. Existing aliases that already pointed at ``alias`` are
    repointed at the new canonical so nothing is left dangling.
    """

    ensure_alias_schema(conn)
    alias_norm = _norm(alias)
    if not alias_norm:
        raise ValueError("alias must be non-empty")
    # Collapse: canonical may already be an alias of something more canonical.
    canonical = resolve_subject(conn, canonical)
    canonical_norm = _norm(canonical)
    if not canonical_norm:
        raise ValueError("canonical must be non-empty")
    if alias_norm == canonical_norm:
        raise ValueError("alias and canonical resolve to the same entity")
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO entity_aliases(alias_norm,alias_name,canonical_name,canonical_norm,source,confidence,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(alias_norm) DO UPDATE SET
          alias_name=excluded.alias_name,
          canonical_name=excluded.canonical_name,
          canonical_norm=excluded.canonical_norm,
          source=excluded.source,
          confidence=excluded.confidence,
          updated_at=excluded.updated_at
        """,
        (alias_norm, alias, canonical, canonical_norm, source, float(confidence), now, now),
    )
    # Repoint any aliases that used to resolve to `alias` (which is now itself an
    # alias) onto the ultimate canonical, keeping the table flat.
    conn.execute(
        """
        UPDATE entity_aliases SET canonical_name=?, canonical_norm=?, updated_at=?
        WHERE canonical_norm=? AND alias_norm != ?
        """,
        (canonical, canonical_norm, now, alias_norm, alias_norm),
    )
    return {"alias": alias, "canonical": canonical, "source": source, "confidence": float(confidence)}


def remove_alias(conn: sqlite3.Connection, alias: str) -> bool:
    if not _alias_table_exists(conn):
        return False
    cur = conn.execute("DELETE FROM entity_aliases WHERE alias_norm=?", (_norm(alias),))
    return cur.rowcount > 0


def list_aliases(conn: sqlite3.Connection, *, canonical: str | None = None) -> list[dict[str, Any]]:
    if not _alias_table_exists(conn):
        return []
    if canonical:
        rows = conn.execute(
            "SELECT alias_name,canonical_name,source,confidence FROM entity_aliases WHERE canonical_norm=? ORDER BY alias_norm",
            (_norm(canonical),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT alias_name,canonical_name,source,confidence FROM entity_aliases ORDER BY canonical_norm,alias_norm"
        ).fetchall()
    return [
        {"alias": r[0], "canonical": r[1], "source": r[2], "confidence": r[3]}
        for r in rows
    ]


def merge_subject(
    conn_or_path: sqlite3.Connection | Path | str,
    from_name: str,
    into_name: str,
    *,
    source: str = "manual",
    confidence: float = 1.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Alias ``from_name`` to ``into_name`` and reconcile existing rows.

    This is the retroactive half of alias resolution. Registering the alias only
    fixes *future* writes; already-stored assertions keep their old
    ``subject_name`` and stay fragmented. So we also rewrite existing
    ``world_state_assertions`` rows and recompute the current pointer for every
    affected ``(subject, predicate)`` pair.
    """

    from .schema import ensure_world_model_schema
    from .state import recompute_current

    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        ensure_world_model_schema(conn)
        ensure_alias_schema(conn)
        canonical = resolve_subject(conn, into_name)
        preview = add_alias(conn, from_name, canonical, source=source, confidence=confidence) if not dry_run else {
            "alias": from_name,
            "canonical": canonical,
        }
        if dry_run:
            # Register on a savepoint so resolution/planning is accurate, then roll back.
            conn.execute("SAVEPOINT mneme_alias_dry_run")
            add_alias(conn, from_name, canonical, source=source, confidence=confidence)

        affected = conn.execute(
            "SELECT DISTINCT predicate FROM world_state_assertions WHERE lower(subject_name)=lower(?)",
            (from_name,),
        ).fetchall()
        predicates = [row["predicate"] for row in affected]
        rewritten = conn.execute(
            "SELECT COUNT(*) FROM world_state_assertions WHERE lower(subject_name)=lower(?)",
            (from_name,),
        ).fetchone()[0]

        if not dry_run:
            now = _now_iso()
            conn.execute(
                "UPDATE world_state_assertions SET subject_name=?, updated_at=? WHERE lower(subject_name)=lower(?)",
                (canonical, now, from_name),
            )
            recomputed = [recompute_current(conn, canonical, predicate) for predicate in predicates]
            if close:
                conn.commit()
        else:
            recomputed = []
            conn.execute("ROLLBACK TO mneme_alias_dry_run")
            conn.execute("RELEASE mneme_alias_dry_run")

        return {
            "ok": True,
            "dry_run": dry_run,
            "alias": preview.get("alias", from_name),
            "canonical": canonical,
            "assertions_rewritten": int(rewritten),
            "predicates_recomputed": predicates,
            "current_ids": [cid for cid in recomputed if cid],
        }
    finally:
        if close:
            conn.close()

