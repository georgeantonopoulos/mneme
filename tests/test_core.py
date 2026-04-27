import sqlite3
from pathlib import Path

from mneme.core import create_config, doctor, explain_edge, generate_proactive_thought, generate_thought, ingest_vault, init_db, list_thought_candidates, load_config, log_edge_event, relationship_type, stable_id, update_vault, upsert_edge, upsert_node, walk_graph, write_note, write_research_resolution
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


def test_proactive_candidates_rank_open_loops_with_evidence(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Journal").mkdir()
    (vault / "Journal" / "casual.md").write_text("# Casual\n\n- Nice idea for later\n", encoding="utf-8")
    (vault / "Projects" / "launch.md").write_text(
        "# Launch\n\n- [ ] Follow up with supplier by Apr 15\n- Risk: contract deadline due May 1\nRelated: [[Supplier]]\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["deadline", "supplier"])

    candidates = list_thought_candidates(db, limit=3, hints=["deadline", "supplier"])

    assert candidates
    top = candidates[0]
    assert top["seed"]["name"] == "Launch"
    assert top["score"] > 0
    assert any("deadline" in reason.lower() or "open loop" in reason.lower() for reason in top["reasons"])
    assert top["evidence"]
    assert top["path"][0]["name"] == "Launch"


def test_generate_proactive_thought_uses_candidate_why_now(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "renewal.md").write_text(
        "# Renewal\n\n- [ ] Decide renewal owner\n- Deadline due Jun 3\nRelated: [[Budget]]\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["deadline", "renewal"])

    thought = generate_proactive_thought(db, hints=["deadline", "renewal"])

    assert thought["title"] in {"Open loop hiding in the graph", "Deadline path worth checking", "Reasoned graph walk"}
    assert thought["why_now"]
    assert "Renewal" in thought["insight"]
    assert thought["score"] > 0
    assert thought["evidence"]
    assert thought["insight"].startswith("Why this matters:")
    assert thought["action"] != thought["evidence"][0]
    assert thought["action"].startswith(("Ask", "Check"))


def test_init_db_migrates_old_edge_schema(tmp_path: Path):
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE edges(id TEXT PRIMARY KEY,src_id TEXT,dst_id TEXT,relation TEXT,source_path TEXT,confidence REAL,evidence_text TEXT,created_at TEXT,updated_at TEXT);
    """)
    conn.close()

    conn = sqlite3.connect(db)
    from mneme.core import init_db
    init_db(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(edges)")}
    conn.close()

    assert {"status", "strength", "source_type", "metadata_json"}.issubset(columns)
    assert "idx_edges_status" in indexes


def test_research_resolution_writes_note_and_weighted_edges(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    payload = {
        "slug": "school-clubs",
        "title": "School clubs resolved",
        "date": "2026-04-26",
        "links": ["People/example-child"],
        "sources_checked": ["email", "payment", "calendar", "vault"],
        "claims": [
            {
                "subject": "Example Child",
                "subject_type": "person",
                "predicate": "attends_activity",
                "object": "Handwriting Club",
                "object_type": "activity",
                "confidence": 0.94,
                "strength": 0.93,
                "certainty": "confirmed",
                "source_type": "payment",
                "evidence": "Payment receipt and school brochure confirm the club timing.",
            },
            {
                "subject": "Example Child",
                "subject_type": "person",
                "predicate": "requested_activity",
                "object": "Art Club",
                "object_type": "activity",
                "confidence": 0.76,
                "strength": 0.72,
                "certainty": "pending",
                "source_type": "email",
                "evidence": "Email asked school to add the club if a place is still available.",
            },
        ],
        "unresolved": ["Morning club paid but child assignment is unclear."],
    }

    result = write_research_resolution(vault, db, payload)

    assert result["note_path"] == "Sources/2026-04-26_school-clubs-resolution.md"
    note = (vault / result["note_path"]).read_text(encoding="utf-8")
    assert "Payment receipt and school brochure" in note
    conn = sqlite3.connect(db)
    rows = conn.execute(
        """
        SELECT a.name,e.relation,b.name,e.status,e.strength,e.confidence,e.source_type,e.evidence_text,e.source_path
        FROM edges e JOIN nodes a ON a.id=e.src_id JOIN nodes b ON b.id=e.dst_id
        ORDER BY e.relation
        """
    ).fetchall()
    debug_count = conn.execute("SELECT count(*) FROM edge_debug_log WHERE event='research_writeback'").fetchone()[0]
    conn.close()
    assert ("Example Child", "attends_activity", "Handwriting Club", "active", 0.93, 0.94, "payment", "Payment receipt and school brochure confirm the club timing.", result["note_path"]) in rows
    assert ("Example Child", "requested_activity", "Art Club", "candidate", 0.72, 0.76, "email", "Email asked school to add the club if a place is still available.", result["note_path"]) in rows
    assert debug_count == 2


def test_research_resolution_missing_evidence_stays_candidate_and_candidates_do_not_drive_walk(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    payload = {
        "slug": "unsupported",
        "title": "Unsupported claim",
        "date": "2026-04-26",
        "sources_checked": ["vault"],
        "claims": [
            {
                "subject": "Example Child",
                "subject_type": "person",
                "predicate": "attends_activity",
                "object": "Unsupported Club",
                "object_type": "activity",
                "confidence": 0.98,
                "strength": 0.98,
                "certainty": "confirmed",
                "source_type": "user_confirmed",
                "evidence": "",
            }
        ],
    }

    write_research_resolution(vault, db, payload)

    conn = sqlite3.connect(db)
    status = conn.execute("SELECT status FROM edges").fetchone()[0]
    child_id = stable_id("person", "Example Child")
    conn.close()
    path = walk_graph(db, seed_id=child_id, hops=2)
    assert status == "candidate"
    assert [node["name"] for node in path] == ["Example Child"]


def test_research_resolution_explicit_active_without_evidence_is_candidate(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    payload = {
        "slug": "explicit-active-unsupported",
        "title": "Explicit active unsupported",
        "date": "2026-04-26",
        "claims": [
            {
                "subject": "Example Child",
                "predicate": "attends_activity",
                "object": "Unsupported Club",
                "confidence": 0.99,
                "certainty": "confirmed",
                "status": "active",
                "evidence": "",
            }
        ],
    }

    write_research_resolution(vault, db, payload)

    conn = sqlite3.connect(db)
    status = conn.execute("SELECT status FROM edges WHERE relation='attends_activity'").fetchone()[0]
    conn.close()
    assert status == "candidate"


def test_research_resolution_edges_survive_update_rebuild(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    payload = {
        "slug": "durable-resolution",
        "title": "Durable resolution",
        "date": "2026-04-26",
        "sources_checked": ["receipt"],
        "claims": [
            {
                "subject": "Example Child",
                "subject_type": "person",
                "predicate": "attends_activity",
                "object": "Handwriting Club",
                "object_type": "activity",
                "confidence": 0.95,
                "strength": 0.91,
                "certainty": "confirmed",
                "source_type": "receipt",
                "evidence": "A receipt confirms Example Child for Handwriting Club, including literal --> and } --> marker text.",
            }
        ],
    }

    write_research_resolution(vault, db, payload)
    update_vault(vault, db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        """
        SELECT a.name,e.relation,b.name,e.status,e.strength,e.confidence,e.source_type
        FROM edges e JOIN nodes a ON a.id=e.src_id JOIN nodes b ON b.id=e.dst_id
        WHERE e.relation='attends_activity'
        """
    ).fetchone()
    debug_count = conn.execute("SELECT count(*) FROM edge_debug_log WHERE event='research_writeback'").fetchone()[0]
    conn.close()
    assert row == ("Example Child", "attends_activity", "Handwriting Club", "active", 0.91, 0.95, "receipt")
    assert debug_count == 1


def test_thought_walk_prefers_semantic_edge_over_date_index_plumbing(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    source = "test.md"
    seed = upsert_node(conn, "note", "Alpha", source)
    date = upsert_node(conn, "date", "2026-04-18", source)
    index = upsert_node(conn, "note", "index", source)
    useful = upsert_node(conn, "project", "Useful Project", source)
    upsert_edge(conn, seed, date, "links_to", source, "[[2026-04-18]]", 0.99)
    upsert_edge(conn, date, index, "links_to", source, "[[index]]", 0.99)
    upsert_edge(conn, seed, useful, "relates_to", source, "Alpha relates to Useful Project", 0.8)
    conn.commit()
    conn.close()

    path = walk_graph(db, seed_id=seed, hops=2)

    names = [node["name"] for node in path]
    assert "Useful Project" in names
    assert "2026-04-18" not in names
    assert "index" not in names


def test_candidate_paths_skip_low_value_wikilink_index_when_better_step_exists(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    source = "test.md"
    note = upsert_node(conn, "note", "Launch", source)
    obs = upsert_node(conn, "observation", "Waiting for owner by 2026-05-01", source)
    index = upsert_node(conn, "wikilink", "index", source)
    project = upsert_node(conn, "project", "Owner Plan", source)
    upsert_edge(conn, note, obs, "has_blocked", source, "Waiting for owner by 2026-05-01", 0.95)
    upsert_edge(conn, note, index, "links_to", source, "[[index]]", 0.99)
    upsert_edge(conn, note, project, "relates_to", source, "Owner Plan", 0.8)
    conn.execute(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        ("obs1", note, "blocked", "Waiting for owner by 2026-05-01", source, 5, "now"),
    )
    conn.commit()
    conn.close()

    candidates = list_thought_candidates(db, limit=1)

    names = [node["name"] for node in candidates[0]["path"]]
    assert "Owner Plan" in names
    assert "index" not in names


def test_candidate_observation_edges_are_not_used_in_thought_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Project.md").write_text("# Project\n\n- [ ] Waiting for confirmation by 2026-05-01\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    conn.execute("UPDATE edges SET status='candidate' WHERE relation='has_blocked'")
    conn.commit()
    conn.close()

    candidates = list_thought_candidates(db, limit=1)
    names = [node["name"] for node in candidates[0]["path"]]
    assert names == ["Project"]


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
    svg = image.read_text(encoding="utf-8")
    assert "Reasoning" in svg
    assert "Next" in svg
    assert "Possible next move" not in svg
