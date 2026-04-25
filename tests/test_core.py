import sqlite3
from pathlib import Path

from mneme.core import generate_thought, ingest_vault, walk_graph
from mneme.render import render_card, safe_basename


def test_ingest_and_walk(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "example.md").write_text(
        "# Example\n\n- [ ] Follow up by Apr 15\n- Waiting for confirmation\nRelated: [[Other]]\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    stats = ingest_vault(vault, db)
    assert stats["notes_read"] == 1
    assert stats["nodes"] >= 3
    assert stats["observations"] >= 1
    path = walk_graph(db, hops=3)
    assert path
    thought = generate_thought(db, path)
    assert thought["title"] and thought["insight"]


def test_rebuild_removes_stale_private_content(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"

    private_note = vault / "private.md"
    private_note.write_text("# Secret Person\n\nContact PRIVATE_MARKER\n", encoding="utf-8")
    ingest_vault(vault, db)

    private_note.unlink()
    (vault / "public.md").write_text("# Public Note\n\n- Safe public task\n", encoding="utf-8")
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    leaked = conn.execute(
        "SELECT count(*) FROM nodes WHERE name LIKE '%Secret Person%' OR name LIKE '%PRIVATE_MARKER%'"
    ).fetchone()[0]
    conn.close()
    assert leaked == 0


def test_task_checkbox_not_duplicated_as_generic_bullet(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "todo.md").write_text("# Todo\n\n- [ ] Book movers by Apr 15\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT text FROM observations").fetchall()
    conn.close()
    assert [row[0] for row in rows] == ["Book movers by Apr 15"]


def test_symlink_escape_is_skipped(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n\nPRIVATE_MARKER\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "safe.md").write_text("# Safe\n", encoding="utf-8")
    (vault / "escape.md").symlink_to(outside)
    db = tmp_path / "mneme.sqlite"

    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    names = {row[0] for row in conn.execute("SELECT name FROM nodes")}
    conn.close()
    assert "Outside" not in names
    assert "PRIVATE_MARKER" not in names


def test_render_basename_is_sanitized_and_svg_fallback(tmp_path: Path, monkeypatch):
    thought = {
        "title": "Safe",
        "insight": "Safe insight",
        "action": "Safe action",
        "path": [{"name": "Node", "type": "note"}],
    }
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: "/missing/convert")
    image = render_card(thought, tmp_path, basename="../../escape")

    assert image.parent == tmp_path
    assert image.name == "thought_escape.svg"
    assert safe_basename("../../escape") == "escape"
