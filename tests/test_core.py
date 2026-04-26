import sqlite3
from pathlib import Path

from mneme.core import create_config, doctor, explain_edge, generate_thought, ingest_vault, load_config, log_edge_event, relationship_type, update_vault, walk_graph, write_note
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


def test_edge_debug_log_records_creation_thinking(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nRelated: [[Beta]]\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT id FROM edges WHERE relation='links_to'").fetchone()
    assert row is not None
    debug = conn.execute(
        "SELECT event, actor, thinking_json FROM edge_debug_log WHERE edge_id=?",
        (row[0],),
    ).fetchone()
    conn.close()

    assert debug is not None
    assert debug[0] == "created"
    assert debug[1] == "ingest"
    thinking = __import__("json").loads(debug[2])
    assert thinking["relation"] == "links_to"
    assert thinking["source_path"] == "alpha.md"
    assert thinking["evidence_text"] == "[[Beta]]"
    assert "Extracted from an explicit Markdown wikilink" in thinking["rationale"]


def test_explain_edge_returns_debug_timeline(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- Waiting for [[Beta]]\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    edge_id = conn.execute("SELECT id FROM edges WHERE relation='links_to'").fetchone()[0]
    log_edge_event(
        conn,
        edge_id,
        "validated",
        "test",
        {"rationale": "Example validation rationale", "source_paths": ["alpha.md"]},
    )
    conn.commit()
    conn.close()

    explanation = explain_edge(db, edge_id)
    assert explanation["edge"]["id"] == edge_id
    assert explanation["edge"]["src"]["name"] == "Alpha"
    assert explanation["edge"]["dst"]["name"] == "Beta"
    assert [event["event"] for event in explanation["debug_log"]] == ["created", "validated"]
    assert explanation["debug_log"][1]["thinking"]["rationale"] == "Example validation rationale"


def test_relationship_ontology_is_seeded_and_explained(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nRelated: [[Beta]]\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    ontology = {
        row[0]: {"category": row[1], "requires_validation": row[2], "inverse": row[3]}
        for row in conn.execute(
            "SELECT id, category, requires_validation, inverse_id FROM relationship_types"
        )
    }
    edge_id = conn.execute("SELECT id FROM edges WHERE relation='links_to'").fetchone()[0]
    conn.close()

    assert ontology["links_to"] == {"category": "reference", "requires_validation": 0, "inverse": "linked_from"}
    assert ontology["belongs_to"] == {"category": "semantic", "requires_validation": 1, "inverse": "has_part"}
    assert ontology["located_in"] == {"category": "semantic", "requires_validation": 1, "inverse": "contains_location"}

    explanation = explain_edge(db, edge_id)
    assert explanation["edge"]["relationship_type"]["id"] == "links_to"
    assert explanation["edge"]["relationship_type"]["category"] == "reference"
    assert "not necessarily a semantic" in explanation["edge"]["relationship_type"]["description"]


def test_relationship_type_helper_returns_default_unknown():
    rel = relationship_type("made_up_relation")
    assert rel["id"] == "made_up_relation"
    assert rel["category"] == "unknown"
    assert rel["requires_validation"] is True


def test_update_vault_removes_deleted_note_without_deleting_thoughts(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    alpha = vault / "alpha.md"
    beta = vault / "beta.md"
    alpha.write_text("# Alpha\n\nRelated: [[Beta]]\n", encoding="utf-8")
    beta.write_text("# Beta\n\n- Waiting for reply\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO thoughts(id, seed_id, path_json, title, insight, action, image_path, created_at) VALUES('t1', NULL, '[]', 'Old', 'Keep', '', NULL, 'now')"
    )
    conn.commit()
    conn.close()

    beta.unlink()
    stats = update_vault(vault, db)

    conn = sqlite3.connect(db)
    observations = {row[0] for row in conn.execute("SELECT text FROM observations")}
    thought_count = conn.execute("SELECT count(*) FROM thoughts").fetchone()[0]
    conn.close()
    assert stats["notes_read"] == 1
    assert "Waiting for reply" not in observations
    assert thought_count == 1


def test_write_note_create_append_and_reject_path_escape(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    created = write_note(vault, "Projects/alpha.md", "# Alpha\n", mode="create")
    assert created["path"] == "Projects/alpha.md"
    assert (vault / "Projects" / "alpha.md").read_text(encoding="utf-8") == "# Alpha\n"

    appended = write_note(vault, "Projects/alpha.md", "- Next action\n", mode="append")
    assert appended["mode"] == "append"
    assert (vault / "Projects" / "alpha.md").read_text(encoding="utf-8").endswith("\n- Next action\n")

    try:
        write_note(vault, "../escape.md", "bad", mode="create")
    except ValueError as exc:
        assert "inside the vault" in str(exc)
    else:
        raise AssertionError("path escape was accepted")


def test_installer_script_exists_and_mentions_pipx_or_pip():
    script = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
    text = script.read_text(encoding="utf-8")
    assert "mneme" in text.lower()
    assert "pipx" in text or "pip install" in text


def test_create_config_and_doctor_reports_ready(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n\n- Due May 1\n", encoding="utf-8")
    config_path = tmp_path / "mneme.json"

    created = create_config(config_path, vault=vault, db=tmp_path / "mneme.sqlite", out=tmp_path / "out", hints=["due", "project"])
    loaded = load_config(config_path)

    assert created["config"] == str(config_path)
    assert loaded["vault"] == str(vault)
    assert loaded["db"].endswith("mneme.sqlite")
    assert loaded["out"].endswith("out")
    assert loaded["hints"] == ["due", "project"]

    report = doctor(config_path=config_path)
    assert report["ok"] is True
    assert report["checks"]["vault"]["ok"] is True
    assert report["checks"]["markdown_notes"]["count"] == 1
    assert "next" in report


def test_doctor_reports_missing_vault(tmp_path: Path):
    config_path = tmp_path / "mneme.json"
    create_config(config_path, vault=tmp_path / "missing", db=tmp_path / "mneme.sqlite", out=tmp_path / "out")

    report = doctor(config_path=config_path)

    assert report["ok"] is False
    assert report["checks"]["vault"]["ok"] is False
    assert "does not exist" in report["checks"]["vault"]["message"]


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
