import json
import sqlite3
import sys
from pathlib import Path

from mneme.brain import brain_label_matches, brain_report, label_brain
from mneme.core import activate_candidate_edges, create_config, debug_candidates, doctor, explain_edge, generate_proactive_thought, generate_thought, ingest_vault, init_db, list_thought_candidates, load_config, log_edge_event, relationship_type, retrieve_context, stable_id, update_vault, upsert_edge, upsert_node, walk_graph, write_note, write_research_resolution
from mneme.consolidate import LabelerConfig, consolidate_graph, retrieval_cluster_matches
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


def test_notes_with_same_title_keep_source_specific_identities(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "alpha").mkdir(parents=True)
    (vault / "beta").mkdir()
    (vault / "alpha" / "Run Log.md").write_text("# Run Log\n\n- Alpha follow up\n", encoding="utf-8")
    (vault / "beta" / "Run Log.md").write_text("# Run Log\n\n- Beta follow up\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name,source_path FROM nodes WHERE type='note' AND name='Run Log' ORDER BY source_path").fetchall()
    conn.close()

    assert rows == [("Run Log", "alpha/Run Log.md"), ("Run Log", "beta/Run Log.md")]


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


def test_candidates_expose_shared_score_breakdown_for_thoughts(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Project.md").write_text("# Project\n\n- [ ] Waiting for owner by 2026-05-01\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["owner"])

    candidate = list_thought_candidates(db, limit=1, hints=["owner"])[0]
    thought = generate_proactive_thought(db, hints=["owner"])

    assert candidate["score_breakdown"]["factors"]
    assert candidate["score_breakdown"]["freshness"]["basis"] == "explicit_date"
    assert thought["score"] == candidate["score"]
    assert "Waiting for owner" in thought["evidence"][0]


def test_debug_candidates_explains_suppressed_low_quality_sources(tmp_path: Path):
    vault = tmp_path / "vault"
    archive = vault / "Project Memory" / "demo" / "Archive" / "Runs"
    archive.mkdir(parents=True)
    (archive / "2026-01-01-old.md").write_text("# Old\n\n- [ ] Waiting for archived owner\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["missing"])

    report = debug_candidates(db, include_skipped=True, limit=5)

    assert report["candidates"]
    first = report["candidates"][0]
    assert any(p["label"] == "source quality" for p in first["score_breakdown"]["penalties"])
    assert "Archive/Runs" in first["seed"]["source_path"]


def test_retrieve_returns_prompt_context_without_promoting_candidate_synapses(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    child = upsert_node(conn, "person", "Example Child", "research")
    club = upsert_node(conn, "activity", "Art Club", "research")
    killed = upsert_node(conn, "activity", "Wrong Club", "research")
    candidate_edge = upsert_edge(
        conn,
        child,
        club,
        "requested_activity",
        "Sources/art.md",
        "Email asked school to add Art Club if a place opens.",
        0.76,
        status="candidate",
        strength=0.72,
        source_type="email",
    )
    killed_edge = upsert_edge(
        conn,
        child,
        killed,
        "attends_activity",
        "Sources/wrong.md",
        "User correction says this was wrong.",
        0.0,
        status="killed",
        strength=0.0,
        source_type="user_confirmed",
    )
    conn.commit()
    conn.close()

    result = retrieve_context(db, "What is going on with Art Club?", max_items=5)
    edge_items = [item for item in result["items"] if item["kind"] == "edge"]

    assert any(item["id"] == candidate_edge and item["truth_policy"] == "candidate_only" for item in edge_items)
    assert killed_edge not in {item["id"] for item in edge_items}


def test_retrieve_finds_observations_and_budgeted_evidence(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Launch.md").write_text("# Launch\n\n- [ ] Follow up with supplier by 2026-05-20\n- General note\n", encoding="utf-8")
    (vault / "Noise.md").write_text("# Noise\n\n- [ ] Urgent deadline due 2026-05-18 for unrelated archive\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["supplier"])

    result = retrieve_context(db, "supplier follow up", budget=200, max_items=3, hints=["supplier"])

    assert result["items"]
    top = result["items"][0]
    assert top["kind"] == "observation"
    assert "supplier" in top["snippet"].lower()
    assert top["score_breakdown"]["freshness"]["basis"] == "explicit_date"
    assert all("supplier" in item["snippet"].lower() for item in result["items"] if item["kind"] == "observation")


def test_consolidate_assigns_procedural_roles_without_name_blacklist(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    center = upsert_node(conn, "note", "Central Switchboard", "Switchboard.md")
    for index in range(6):
        project = upsert_node(conn, "project", f"Project {index}", f"Project-{index}.md")
        detail = upsert_node(conn, "observation", f"Project {index} owner follow up", f"Project-{index}.md")
        upsert_edge(conn, center, project, "links_to", "Switchboard.md", f"[[Project {index}]]", 0.95, strength=0.95)
        upsert_edge(conn, project, detail, "has_blocked", f"Project-{index}.md", f"Project {index} owner follow up", 0.95, strength=0.95)
    conn.commit()
    conn.close()

    summary = consolidate_graph(db, iterations=8, min_cluster_size=2)

    conn = sqlite3.connect(db)
    role = conn.execute(
        "SELECT role FROM cluster_memberships WHERE run_id=? AND node_id=?",
        (summary["run_id"], center),
    ).fetchone()[0]
    hubness = conn.execute(
        "SELECT hubness FROM cluster_memberships WHERE run_id=? AND node_id=?",
        (summary["run_id"], center),
    ).fetchone()[0]
    conn.close()
    assert role in {"hub", "bridge"}
    assert hubness > 1.0


def test_retrieve_uses_consolidated_cluster_context(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Launch.md").write_text("# Launch\n\n- [ ] Follow up with supplier by 2026-05-20\n\nSupplier plan relates to launch readiness.\n", encoding="utf-8")
    (vault / "Supplier.md").write_text("# Supplier\n\n- [ ] Waiting for owner confirmation on supplier plan\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    ingest_vault(vault, db, hints=["supplier"])
    consolidate_graph(db, iterations=8, min_cluster_size=2)

    result = retrieve_context(db, "supplier owner follow up", budget=500, max_items=5, hints=["supplier"])

    assert result["clusters"]
    assert result["items"]
    assert any(item.get("cluster") for item in result["items"])


def test_consolidate_can_label_clusters_through_harness_provider(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    note = upsert_node(conn, "note", "Supplier Launch Plan", "Launch.md")
    owner = upsert_node(conn, "person", "Launch Owner", "Launch.md")
    blocked = upsert_node(conn, "observation", "Supplier launch owner follow up", "Launch.md")
    upsert_edge(conn, note, owner, "relates_to", "Launch.md", "Launch owner owns supplier readiness", 0.9, strength=0.9)
    upsert_edge(conn, note, blocked, "has_blocked", "Launch.md", "Supplier launch owner follow up", 0.95, strength=0.95)
    conn.commit()
    conn.close()

    command = [
        sys.executable,
        "-c",
        "import json,sys; sys.stdin.read(); print(json.dumps({'labels':['supplier launch','owner followup'], 'summary':'Supplier launch follow-up cluster.', 'intent':'follow up', 'ignore':False}))",
    ]
    summary = consolidate_graph(
        db,
        iterations=4,
        min_cluster_size=2,
        labeler=LabelerConfig(provider="test-labeler", command=command, max_clusters=1, timeout=10),
    )

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT label_json,summary_json FROM memory_clusters WHERE run_id=? LIMIT 1", (summary["run_id"],)).fetchone()
    conn.close()
    labels = json.loads(row[0])
    cluster_summary = json.loads(row[1])
    assert labels == ["supplier launch", "owner followup"]
    assert cluster_summary["label_meta"]["source"] == "llm"
    assert summary["labeling"]["clusters_labelled"] == 1

    conn = sqlite3.connect(db)
    matches = retrieval_cluster_matches(conn, "supplier launch handoff", limit=3)
    conn.close()
    assert matches["clusters"]
    assert matches["clusters"][0]["matched_terms"] == ["launch", "supplier"]


def test_brain_label_pass_covers_nodes_synapses_relationships_and_retrieval(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    note = upsert_node(conn, "note", "Supplier Launch Plan", "Launch.md")
    owner = upsert_node(conn, "person", "Launch Owner", "Launch.md")
    edge = upsert_edge(conn, note, owner, "relates_to", "Launch.md", "Supplier launch owner owns readiness", 0.9, strength=0.9)
    conn.execute(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        ("obs-launch", note, "blocked", "Supplier launch owner follow up", "Launch.md", 5, "now"),
    )
    conn.commit()
    conn.close()
    consolidate_graph(db, iterations=4, min_cluster_size=2)

    command = [
        sys.executable,
        "-c",
        "import json,sys; text=sys.stdin.read().lower(); labels=['supplier launch','owner readiness'] if 'supplier' in text else ['relationship semantics','graph traversal']; print(json.dumps({'labels':labels,'summary':'brain target label','intent':'retrieval routing','ignore':False}))",
    ]
    result = label_brain(
        db,
        labeler=LabelerConfig(provider="test-labeler", command=command, timeout=10),
        targets=["node", "synapse", "relationship"],
        max_nodes=3,
        max_synapses=3,
        max_relationships=3,
    )

    assert result["targets"]["node"] == 2
    assert result["targets"]["synapse"] == 1
    assert result["targets"]["relationship"] == 3
    conn = sqlite3.connect(db)
    matches = brain_label_matches(conn, "supplier launch readiness", limit=5)
    conn.close()
    assert any(item["target_type"] in {"node", "synapse"} for item in matches["matches"])

    retrieved = retrieve_context(db, "supplier launch readiness", max_items=5)
    assert retrieved["brain_labels"]
    assert any(item.get("brain_label") for item in retrieved["items"])
    report = brain_report(db)
    assert report["counts"]["node"] == 2
    assert report["coverage"]["node"]["labelled"] == 2
    assert report["coverage"]["node"]["available"] == 2
    assert report["coverage"]["node"]["depth"] == "deep"
    assert report["coverage"]["synapse"]["labelled"] == 1


def test_consolidation_does_not_promote_candidate_edges(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    child = upsert_node(conn, "person", "Example Child", "child.md")
    activity = upsert_node(conn, "project", "Chess Club", "activity.md")
    candidate_edge = upsert_edge(
        conn,
        child,
        activity,
        "requested_activity",
        "email.md",
        "Email asked about Chess Club availability.",
        0.72,
        status="candidate",
        strength=0.7,
        source_type="email",
    )
    conn.commit()
    conn.close()

    consolidate_graph(db, iterations=4, min_cluster_size=2)
    result = retrieve_context(db, "Chess Club availability", max_items=5)
    edge_items = [item for item in result["items"] if item["id"] == candidate_edge]

    assert edge_items
    assert edge_items[0]["truth_policy"] == "candidate_only"
    assert edge_items[0]["status"] == "candidate"


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
