from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def slug(value: str | None, *, fallback: str = "item") -> str:
    text = " ".join(TOKEN_RE.findall(value or "")).strip().lower()
    text = re.sub(r"[_\s]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or fallback


def normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    parts = [slug(part) for part in str(path).replace("\\", "/").split("/") if slug(part)]
    return "/".join(parts) if parts else None


def _prefix_rows(path: str, node_id: str) -> list[tuple[str, str, int]]:
    parts = [part for part in path.split("/") if part]
    return [("/".join(parts[:depth]), node_id, depth) for depth in range(1, len(parts) + 1)]


def ensure_hierarchy_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS path_index(path TEXT NOT NULL,node_id TEXT NOT NULL,depth INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(path,node_id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_path_index_prefix ON path_index(path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_path_index_node ON path_index(node_id)")
    for ddl in (
        "ALTER TABLE nodes ADD COLUMN path TEXT DEFAULT NULL",
        "ALTER TABLE edges ADD COLUMN cross_boundary INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def set_node_path(conn: sqlite3.Connection, node_id: str, path: str | None) -> None:
    ensure_hierarchy_schema(conn)
    normalized = normalize_path(path)
    conn.execute("UPDATE nodes SET path=? WHERE id=?", (normalized, node_id))
    conn.execute("DELETE FROM path_index WHERE node_id=?", (node_id,))
    if normalized:
        conn.executemany(
            "INSERT OR REPLACE INTO path_index(path,node_id,depth) VALUES(?,?,?)",
            _prefix_rows(normalized, node_id),
        )


def rebuild_path_index(conn: sqlite3.Connection) -> int:
    ensure_hierarchy_schema(conn)
    conn.execute("DELETE FROM path_index")
    rows: list[tuple[str, str, int]] = []
    for node_id, path in conn.execute("SELECT id,path FROM nodes WHERE path IS NOT NULL AND path != ''"):
        normalized = normalize_path(path)
        if normalized and normalized != path:
            conn.execute("UPDATE nodes SET path=? WHERE id=?", (normalized, node_id))
        if normalized:
            rows.extend(_prefix_rows(normalized, node_id))
    conn.executemany("INSERT OR REPLACE INTO path_index(path,node_id,depth) VALUES(?,?,?)", rows)
    return len(rows)


def get_subtree_node_ids(conn: sqlite3.Connection, path_prefix: str) -> set[str]:
    ensure_hierarchy_schema(conn)
    normalized = normalize_path(path_prefix)
    if not normalized:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT node_id FROM path_index WHERE path=? OR path LIKE ?",
        (normalized, normalized + "/%"),
    ).fetchall()
    return {str(row[0]) for row in rows}


def get_node_path(conn: sqlite3.Connection, node_id: str) -> str | None:
    ensure_hierarchy_schema(conn)
    row = conn.execute("SELECT path FROM nodes WHERE id=?", (node_id,)).fetchone()
    return str(row[0]) if row and row[0] else None


def top_level(path: str | None) -> str | None:
    normalized = normalize_path(path)
    if not normalized:
        return None
    return normalized.split("/", 1)[0]


def mark_cross_boundary_edges(conn: sqlite3.Connection) -> int:
    ensure_hierarchy_schema(conn)
    rows = conn.execute(
        """SELECT e.id,s.path,d.path
           FROM edges e
           JOIN nodes s ON s.id=e.src_id
           JOIN nodes d ON d.id=e.dst_id
           WHERE COALESCE(e.status,'candidate') != 'killed'"""
    ).fetchall()
    changed = 0
    for edge_id, src_path, dst_path in rows:
        src_top = top_level(src_path)
        dst_top = top_level(dst_path)
        is_cross = int(bool(src_top and dst_top and src_top != dst_top))
        conn.execute("UPDATE edges SET cross_boundary=? WHERE id=?", (is_cross, edge_id))
        changed += 1
    return changed


def derive_path(source_path: str | None, node_type: str | None, node_name: str | None) -> str:
    source = str(source_path or "").strip().replace("\\", "/")
    source_lower = source.lower()
    name_slug = slug(node_name or Path(source).stem)
    type_slug = slug(node_type or "entity", fallback="entity")

    if source_lower.startswith("gws://"):
        return normalize_path(f"{type_slug}/{name_slug}") or f"{type_slug}/{name_slug}"
    if source_lower.startswith("email://"):
        return "email"
    if source_lower.startswith("mneme://"):
        return "agent/memory"

    path = Path(source)
    parts = [part for part in source.split("/") if part]
    if parts:
        first = parts[0].lower()
        stem = slug(Path(parts[-1]).stem)
        mapping = {
            "projects": "projects",
            "people": "people",
            "memory": "memory",
            "vendors": "vendors",
            "events": "events",
            "daily": "daily",
        }
        if first in mapping and stem:
            return f"{mapping[first]}/{stem}"
    if path.stem:
        name_slug = slug(path.stem, fallback=name_slug)
    return normalize_path(f"uncategorized/{name_slug}") or "uncategorized/item"


def inherit_entity_paths(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id,name FROM nodes WHERE type='entity' AND (path IS NULL OR path='')").fetchall()
    assigned = 0
    for node_id, name in rows:
        candidates: list[str] = []
        for (path,) in conn.execute(
            """SELECT n.path
               FROM edges e
               JOIN nodes n ON n.id=CASE WHEN e.src_id=? THEN e.dst_id ELSE e.src_id END
               WHERE (e.src_id=? OR e.dst_id=?) AND n.path IS NOT NULL AND n.path != ''
                 AND COALESCE(e.status,'candidate') != 'killed'""",
            (node_id, node_id, node_id),
        ):
            if path:
                candidates.append(str(path))
        if not candidates:
            continue
        parent = Counter(candidates).most_common(1)[0][0]
        set_node_path(conn, node_id, f"{parent}/{slug(name)}")
        assigned += 1
    return assigned


def migrate_add_paths(db_path: str | Path, conn: sqlite3.Connection | None = None) -> dict:
    own_conn = conn is None
    connection = conn or sqlite3.connect(db_path)
    try:
        ensure_hierarchy_schema(connection)
        assigned = 0
        for node_id, node_type, name, source_path in connection.execute(
            "SELECT id,type,name,source_path FROM nodes WHERE (path IS NULL OR path='') AND type != 'entity'"
        ).fetchall():
            set_node_path(connection, node_id, derive_path(source_path, node_type, name))
            assigned += 1
        inherited = inherit_entity_paths(connection)
        for node_id, node_type, name, source_path in connection.execute(
            "SELECT id,type,name,source_path FROM nodes WHERE path IS NULL OR path=''"
        ).fetchall():
            set_node_path(connection, node_id, derive_path(source_path, node_type, name))
            assigned += 1
        index_rows = rebuild_path_index(connection)
        edges_checked = mark_cross_boundary_edges(connection)
        if own_conn:
            connection.commit()
        return {
            "ok": True,
            "db": str(db_path),
            "nodes_assigned": assigned + inherited,
            "path_index_rows": index_rows,
            "edges_checked": edges_checked,
        }
    finally:
        if own_conn:
            connection.close()


def path_tree(conn: sqlite3.Connection, prefix: str | None = None) -> dict:
    ensure_hierarchy_schema(conn)
    normalized = normalize_path(prefix) if prefix else None
    if normalized:
        rows = conn.execute(
            "SELECT path,COUNT(DISTINCT node_id) FROM path_index WHERE path=? OR path LIKE ? GROUP BY path ORDER BY path",
            (normalized, normalized + "/%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT path,COUNT(DISTINCT node_id) FROM path_index GROUP BY path ORDER BY path").fetchall()
    return {str(path): int(count) for path, count in rows}


def validate_paths(conn: sqlite3.Connection) -> dict:
    ensure_hierarchy_schema(conn)
    missing_path = int(conn.execute("SELECT COUNT(*) FROM nodes WHERE path IS NULL OR path=''").fetchone()[0])
    missing_index = int(
        conn.execute(
            """SELECT COUNT(*) FROM nodes n
               WHERE n.path IS NOT NULL AND n.path != ''
                 AND NOT EXISTS (SELECT 1 FROM path_index pi WHERE pi.node_id=n.id AND pi.path=n.path)"""
        ).fetchone()[0]
    )
    stale_index = int(
        conn.execute(
            """SELECT COUNT(*) FROM path_index pi
               WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id=pi.node_id)"""
        ).fetchone()[0]
    )
    return {
        "ok": missing_path == 0 and missing_index == 0 and stale_index == 0,
        "orphan_nodes": missing_path,
        "missing_path_index_entries": missing_index,
        "stale_path_index_entries": stale_index,
    }
