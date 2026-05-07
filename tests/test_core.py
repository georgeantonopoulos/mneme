import datetime as dt
import sqlite3
from pathlib import Path

from mneme.core import actionability_from_candidate, activate_candidate_edges, contract_from_candidate, create_config, dismiss_thought_task, doctor, explain_edge, generate_proactive_thought, generate_thought, ingest_vault, init_db, list_thought_candidates, list_thought_tasks, load_config, log_edge_event, record_thought_reminder, record_thought_writeback, relationship_type, save_thought, stable_id, tick, update_thought_task, update_vault, upsert_edge, upsert_node, walk_graph, write_note, write_research_resolution
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


def test_thought_candidate_emits_contract_with_internal_lifecycle_tag(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "alpha.md").write_text(
        "# Alpha\n\n- [ ] Ask Casey for the signed agreement by Apr 15\nRelated: [[Casey]]\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    candidate = list_thought_candidates(db, limit=1)[0]
    contract = contract_from_candidate(candidate)
    thought = generate_proactive_thought(db)

    assert contract["mission"].startswith("Finish this unfinished loop:")
    assert contract["done_when"] == "A human-visible next action, note update, scheduled reminder, or explicit dismissal exists."
    assert contract["lifecycle_tag"] == "mneme:thought/open_loop"
    assert contract["writeback_target"].startswith("Thoughts/")
    assert "ask_user" in contract["allowed_actions"]
    assert thought["contract"]["mission"]
    assert "Finish" in thought["action"] or "first move" in thought["action"].lower()


def test_actionability_score_uses_internal_tags_not_resolved_word_matching():
    candidate = {
        "base_score": 2.0,
        "score": 99.0,
        "observation": {"kind": "blocked", "text": "Casey item is resolved confirmed closed done", "source_path": "Projects/alpha.md"},
        "path": [
            {"type": "project", "name": "Alpha"},
            {"type": "person", "name": "Casey"},
        ],
        "reasons": [],
    }

    score, tags, reasons = actionability_from_candidate(candidate)
    contract = contract_from_candidate({**candidate, "score": score, "internal_tags": tags})

    assert score == 10.5
    assert contract["actionability_score"] == score
    assert "mneme:thought/open_loop" in tags
    assert "mneme:near_human" in tags
    assert not any("resolved" in reason.lower() for reason in reasons)


def test_saving_contract_creates_explicit_lifecycle_task_not_lexical_closure(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- [ ] Ask Casey by Apr 15\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)
    thought = generate_proactive_thought(db)

    thought_id = save_thought(db, thought, image_path="thought.png")
    tasks = list_thought_tasks(db)

    assert tasks[0]["thought_id"] == thought_id
    assert tasks[0]["status"] == "open"
    assert tasks[0]["lifecycle_tag"] == thought["contract"]["lifecycle_tag"]
    assert tasks[0]["done_when"] == thought["contract"]["done_when"]

    updated = update_thought_task(db, tasks[0]["id"], status="resolved", evidence="user dismissed explicitly")
    assert updated["status"] == "resolved"
    assert list_thought_tasks(db, status="open") == []


def test_thought_task_lifecycle_events_close_loops_explicitly(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- [ ] Ask Casey by Apr 15\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    task_id = list_thought_tasks(db)[0]["id"] if list_thought_tasks(db) else None
    if task_id is None:
        save_thought(db, generate_proactive_thought(db), image_path="thought.png")
        task_id = list_thought_tasks(db)[0]["id"]
    acted = record_thought_writeback(db, task_id, target="Projects/alpha.md", evidence="Added next action note")
    assert acted["status"] == "acted"
    assert "writeback:Projects/alpha.md" in acted["evidence"]

    save_thought(db, generate_proactive_thought(db), image_path="thought2.png")
    reminder_task = list_thought_tasks(db, status="open")[0]
    reminded = record_thought_reminder(db, reminder_task["id"], reminder_id="cal-123", evidence="Calendar reminder created")
    assert reminded["status"] == "resolved"
    assert "reminder:cal-123" in reminded["evidence"]

    save_thought(db, generate_proactive_thought(db), image_path="thought3.png")
    dismiss_task = list_thought_tasks(db, status="open")[0]
    dismissed = dismiss_thought_task(db, dismiss_task["id"], reason="not relevant after review")
    assert dismissed["status"] == "dismissed"
    assert "dismissed:not relevant after review" in dismissed["evidence"]
    assert list_thought_tasks(db, status="open") == []


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


def test_deterministic_ingest_keeps_navigation_edges_candidate(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n## Context\n\nRelated: [[Beta]]\n- Risk due May 1\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    statuses = dict(conn.execute("SELECT relation,status FROM edges").fetchall())
    conn.close()

    assert statuses["links_to"] == "candidate"
    assert statuses["has_heading"] == "candidate"
    assert statuses["has_risk"] == "active"
    assert statuses["mentions_date"] == "candidate"


def test_promote_candidates_is_explicit_and_dry_run_safe(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    src = upsert_node(conn, "note", "Alpha", "alpha.md")
    dst = upsert_node(conn, "wikilink", "Beta", "alpha.md")
    edge = upsert_edge(conn, src, dst, "links_to", "alpha.md", "[[Beta]]", 0.9, status="candidate")
    conn.commit()
    conn.close()

    dry = activate_candidate_edges(db, mode="all", dry_run=True)
    conn = sqlite3.connect(db)
    before = conn.execute("SELECT status FROM edges WHERE id=?", (edge,)).fetchone()[0]
    conn.close()
    live = activate_candidate_edges(db, mode="all", dry_run=False)
    conn = sqlite3.connect(db)
    after = conn.execute("SELECT status FROM edges WHERE id=?", (edge,)).fetchone()[0]
    conn.close()

    assert dry["would_activate"] == 1
    assert dry["activated"] == 0
    assert before == "candidate"
    assert live["activated"] == 1
    assert after == "active"


def test_rebuild_preserves_durable_active_edges_and_killed_tombstones(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    durable_src = upsert_node(conn, "person", "Validated Person", "research")
    durable_dst = upsert_node(conn, "activity", "Validated Activity", "research")
    stale_src = upsert_node(conn, "note", "Stale Secret", "stale.md")
    stale_dst = upsert_node(conn, "wikilink", "PRIVATE_MARKER", "stale.md")
    durable_edge = upsert_edge(
        conn,
        durable_src,
        durable_dst,
        "attends_activity",
        "Sources/resolution.md",
        "Receipt-backed validation",
        0.95,
        status="active",
        strength=0.95,
        source_type="receipt",
    )
    killed_edge = upsert_edge(
        conn,
        durable_dst,
        durable_src,
        "bad_relation",
        "Sources/resolution.md",
        "Rejected claim",
        0.0,
        status="killed",
        strength=0.0,
        source_type="receipt",
    )
    stale_edge = upsert_edge(conn, stale_src, stale_dst, "links_to", "stale.md", "[[PRIVATE_MARKER]]", 0.9)
    conn.commit()
    conn.close()

    (vault / "public.md").write_text("# Public\n\nRelated: [[Safe]]\n", encoding="utf-8")
    stats = ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    statuses = dict(conn.execute("SELECT id,status FROM edges WHERE id IN (?,?,?)", (durable_edge, killed_edge, stale_edge)).fetchall())
    names = {row[0] for row in conn.execute("SELECT name FROM nodes")}
    debug_count = conn.execute("SELECT count(*) FROM edge_debug_log WHERE edge_id IN (?,?)", (durable_edge, killed_edge)).fetchone()[0]
    conn.close()

    assert stats["preserved_active_edges"] == 1
    assert stats["preserved_killed_edges"] == 1
    assert statuses[durable_edge] == "active"
    assert statuses[killed_edge] == "killed"
    assert stale_edge not in statuses
    assert "PRIVATE_MARKER" not in names
    assert "Stale Secret" not in names
    assert debug_count == 2


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

    assert thought["title"] in {"Unfinished loop with a first move", "Time-sensitive item to verify", "Open loop hiding in the graph", "Deadline path worth checking", "Reasoned graph walk"}
    assert thought["why_now"]
    assert "Renewal" in thought["insight"]
    assert thought["score"] > 0
    assert thought["evidence"]
    assert thought["insight"].startswith("Why this matters:")
    assert thought["action"] != thought["evidence"][0]
    assert thought["action"].startswith(("Ask", "Check", "Finish"))
    assert thought.get("contract", {}).get("mission")


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


def test_guardrail_observation_suppresses_stale_open_loop(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "old.md").write_text(
        "# Old Tracker\n\n- Widget records translation still open and overdue\n",
        encoding="utf-8",
    )
    (vault / "correction.md").write_text(
        "# Correction\n\n- Correction: Widget records translation was hallucinated. Do not treat old tracker rows as active unless fresh source evidence explicitly reactivates it.\n",
        encoding="utf-8",
    )
    (vault / "fresh.md").write_text(
        "# Fresh Work\n\n- [ ] Follow up with supplier by 2026-05-01\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["translation", "supplier"])

    candidates = list_thought_candidates(db, limit=10, hints=["translation", "supplier"])
    texts = [candidate["observation"]["text"] for candidate in candidates]

    assert "Widget records translation still open and overdue" not in texts
    assert all("hallucinated" not in text.lower() for text in texts)
    assert "Follow up with supplier by 2026-05-01" in texts


def test_guardrail_without_topic_overlap_does_not_hide_other_tasks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "guardrail.md").write_text(
        "# Guardrail\n\n- Correction: Widget records translation was hallucinated. Do not treat old tracker rows as active unless fresh evidence exists.\n",
        encoding="utf-8",
    )
    (vault / "ops.md").write_text(
        "# Ops\n\n- [ ] Renew vendor insurance by 2026-06-01\n",
        encoding="utf-8",
    )
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["insurance", "vendor"])

    candidates = list_thought_candidates(db, limit=5, hints=["insurance", "vendor"])
    texts = [candidate["observation"]["text"] for candidate in candidates]

    assert "Renew vendor insurance by 2026-06-01" in texts


def test_tick_temporal_decay_uses_source_dates_not_rebuild_timestamps(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    now = dt.datetime.now(dt.timezone.utc)
    created_at = now.isoformat(timespec="seconds")
    old_day = (now - dt.timedelta(days=30)).date().isoformat()
    today = now.date().isoformat()
    old_source = f"memory/{old_day}.md"
    current_source = f"memory/{today}.md"
    old_note = upsert_node(conn, "note", "Old Daily", old_source)
    current_note = upsert_node(conn, "note", "Current Daily", current_source)
    conn.execute(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        ("old-risk", old_note, "risk", "Blueground move-out TOMORROW deadline", old_source, 10, created_at),
    )
    conn.execute(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        ("current-risk", current_note, "risk", "Renew vendor insurance by today", current_source, 10, created_at),
    )
    conn.commit()
    conn.close()

    tick(db, hints=["deadline", "insurance"], limit=10)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = {
        row["seed_observation_id"]: row
        for row in conn.execute("SELECT seed_observation_id,activation_score,why_now_json FROM thought_candidates")
    }
    conn.close()
    old_why = rows["old-risk"]["why_now_json"]

    assert rows["current-risk"]["activation_score"] > rows["old-risk"]["activation_score"]
    assert rows["old-risk"]["activation_score"] < 0
    assert "temporal_age_penalty" in old_why
    assert "source_path" in old_why


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
