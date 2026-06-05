from __future__ import annotations

import sqlite3
from pathlib import Path

from mneme.cli import main
from mneme.consolidate import consolidate_graph
from mneme.core import add_observation, init_db, retrieve_context, upsert_edge, upsert_node
from mneme.hierarchy import derive_path, get_node_path, get_subtree_node_ids, mark_cross_boundary_edges, migrate_add_paths, set_node_path


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.commit()
    conn.close()
    return db


def test_derive_path_patterns():
    assert derive_path("projects/Alpha Project.md", "project", "Alpha Project") == "projects/alpha-project"
    assert derive_path("people/Person A.md", "person", "Person A") == "people/person-a"
    assert derive_path("memory/2026-01-02.md", "note", "2026-01-02") == "memory/2026-01-02"
    assert derive_path("vendors/Vendor B.md", "vendor", "Vendor B") == "vendors/vendor-b"
    assert derive_path("events/Event C.md", "event", "Event C") == "events/event-c"
    assert derive_path("daily/2026-01-03.md", "note", "2026-01-03") == "daily/2026-01-03"
    assert derive_path("gws://calendar/event-a", "event", "Calendar Event A") == "event/calendar-event-a"
    assert derive_path("email://inbox/message-a", "person", "Sender A") == "email"
    assert derive_path("mneme://memory/item-a", "entity", "Memory Item A") == "agent/memory"
    assert derive_path("misc/freeform.md", "entity", "Loose Item") == "uncategorized/freeform"


def test_set_node_path_and_subtree_index(tmp_path: Path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    node = upsert_node(conn, "project", "Project A", "projects/project-a.md")
    set_node_path(conn, node, "projects/project-a/repairs")
    conn.commit()

    assert get_node_path(conn, node) == "projects/project-a/repairs"
    assert get_subtree_node_ids(conn, "projects") == {node}
    assert get_subtree_node_ids(conn, "projects/project-a") == {node}
    assert get_subtree_node_ids(conn, "projects/project-b") == set()
    rows = conn.execute("SELECT path,depth FROM path_index WHERE node_id=? ORDER BY depth", (node,)).fetchall()
    conn.close()
    assert rows == [("projects", 1), ("projects/project-a", 2), ("projects/project-a/repairs", 3)]


def test_mark_cross_boundary_edges(tmp_path: Path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    property_a = upsert_node(conn, "project", "Property A", "projects/property-a.md")
    property_b = upsert_node(conn, "vendor", "Vendor A", "vendors/vendor-a.md")
    property_c = upsert_node(conn, "project", "Property B", "projects/property-b.md")
    set_node_path(conn, property_a, "properties/property-a")
    set_node_path(conn, property_b, "vendors/vendor-a")
    set_node_path(conn, property_c, "properties/property-b")
    cross = upsert_edge(conn, property_a, property_b, "relates_to", "projects/property-a.md", "Property A uses Vendor A.", 0.9, status="active")
    same = upsert_edge(conn, property_a, property_c, "relates_to", "projects/property-a.md", "Property A compares with Property B.", 0.9, status="active")
    mark_cross_boundary_edges(conn)
    rows = dict(conn.execute("SELECT id,cross_boundary FROM edges").fetchall())
    conn.close()
    assert rows[cross] == 1
    assert rows[same] == 0


def test_path_aware_retrieval_prunes_to_subtree_and_cross_boundary(tmp_path: Path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    target = upsert_node(conn, "project", "Property Alpha Repair", "projects/property-alpha.md")
    vendor = upsert_node(conn, "vendor", "Vendor Bridge", "vendors/vendor-bridge.md")
    unrelated = upsert_node(conn, "project", "Project Zeta", "projects/project-zeta.md")
    set_node_path(conn, target, "properties/property-alpha/repairs")
    set_node_path(conn, vendor, "vendors/vendor-bridge")
    set_node_path(conn, unrelated, "projects/project-zeta")
    add_observation(conn, target, "blocked", "Property Alpha repair requires updated appointment.", "projects/property-alpha.md", 8.0)
    add_observation(conn, unrelated, "blocked", "Project Zeta has unrelated archive material.", "projects/project-zeta.md", 10.0)
    edge = upsert_edge(conn, target, vendor, "relates_to", "projects/property-alpha.md", "Vendor Bridge is tied to Property Alpha repair.", 0.9, status="active", strength=0.9)
    mark_cross_boundary_edges(conn)
    conn.commit()
    conn.close()

    result = retrieve_context(db, "Property Alpha repair", max_items=6)
    text = "\n".join(f"{item.get('title')} {item.get('snippet')}" for item in result["items"])
    assert result["retrieval"]["path_filter_active"] is True
    assert "Property Alpha Repair" in text
    assert edge in {item["id"] for item in result["items"]}
    assert "Project Zeta" not in text


def test_retrieval_fallback_without_path_match_still_scans(tmp_path: Path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    node = upsert_node(conn, "project", "Fallback Topic", "projects/fallback-topic.md")
    add_observation(conn, node, "blocked", "Unique fallback token remains discoverable.", "projects/fallback-topic.md", 8.0)
    conn.commit()
    conn.close()

    result = retrieve_context(db, "unique fallback token", max_items=3)
    assert result["retrieval"]["path_filter_active"] is False
    assert any("Fallback Topic" in item.get("title", "") for item in result["items"])


def test_migrate_and_consolidation_generate_paths(tmp_path: Path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    a = upsert_node(conn, "project", "Project Cluster A", "projects/project-cluster-a.md")
    b = upsert_node(conn, "project", "Project Cluster B", "projects/project-cluster-b.md")
    upsert_edge(conn, a, b, "relates_to", "projects/project-cluster-a.md", "Project Cluster A relates to Project Cluster B.", 0.9, status="active", strength=0.9)
    conn.commit()
    conn.close()

    result = migrate_add_paths(db)
    assert result["nodes_assigned"] == 2
    conn = sqlite3.connect(db)
    conn.execute("UPDATE nodes SET path=NULL")
    conn.execute("DELETE FROM path_index")
    conn.commit()
    conn.close()

    summary = consolidate_graph(db, min_cluster_size=2, iterations=2)
    assert summary["clusters"] >= 1
    conn = sqlite3.connect(db)
    paths = conn.execute("SELECT COUNT(*) FROM nodes WHERE path IS NOT NULL AND path != ''").fetchone()[0]
    index_rows = conn.execute("SELECT COUNT(*) FROM path_index").fetchone()[0]
    conn.close()
    assert paths == 2
    assert index_rows >= 2


def test_cli_path_commands(tmp_path: Path, capsys):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    node = upsert_node(conn, "project", "CLI Node A", "projects/cli-node-a.md")
    conn.commit()
    conn.close()

    main(["path", "set", "--db", str(db), "--node", "CLI Node A", "--path", "projects/cli-node-a"])
    assert "cli-node-a" in capsys.readouterr().out
    main(["path", "get", "--db", str(db), "--node", node])
    assert "projects/cli-node-a" in capsys.readouterr().out
    main(["path", "ls", "--db", str(db), "--prefix", "projects"])
    assert "projects" in capsys.readouterr().out
    main(["path", "tree", "--db", str(db)])
    assert "projects/cli-node-a" in capsys.readouterr().out
    main(["path", "migrate", "--db", str(db)])
    assert '"ok": true' in capsys.readouterr().out
    main(["path", "validate", "--db", str(db)])
    assert '"ok": true' in capsys.readouterr().out
