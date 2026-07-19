import json
import math
import sqlite3
from pathlib import Path

import pytest

import mneme.neural as neural
from mneme.core import init_db
from mneme.neural import _neuron_rows, _neuron_text, build_latent_index, think


def _seed(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("travel", "project", "Athens family travel", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("passport", "task", "Renew passport", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("invoice", "task", "Pay studio invoice", "Projects/business.md", "2026-01-01", "2026-01-01"),
            ("noise", "note", "Garden plants", "Notes/garden.md", "2026-01-01", "2026-01-01"),
            ("rumor", "task", "Unverified airport rumor", "Notes/rumor.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.executemany(
        """INSERT INTO edges(id,src_id,dst_id,relation,strength,confidence,status,source_path,evidence_text,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("e1", "travel", "passport", "requires", 1.0, 1.0, "active", "Projects/travel.md", "Passport is required before travel", "2026-01-01", "2026-01-01"),
            ("e2", "travel", "noise", "mentions", 1.0, 1.0, "killed", "Notes/garden.md", "Wrong historical link", "2026-01-01", "2026-01-01"),
            ("e3", "travel", "rumor", "might_require", 1.0, 1.0, "candidate", "Notes/rumor.md", "Unverified candidate", "2026-01-01", "2026-01-01"),
            ("e4", "travel", "noise", "forgotten_link", 0.0, 1.0, "active", "Notes/garden.md", "Forgotten evidence", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_latent_index_is_incremental_and_local(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    first = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    second = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert first["indexed"] == 5
    assert second["indexed"] == 0
    assert second["unchanged"] == 5
    assert second["dimensions"] == 64
    conn.execute("DELETE FROM nodes WHERE id='noise'")
    third = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert third["removed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM latent_neurons").fetchone()[0] == 4


def test_dimension_change_reindexes_all_hash_vectors(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)

    first = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    second = build_latent_index(conn, provider="hash", model="hash-v1", dimensions=32)

    assert first["indexed"] == 5
    assert second["indexed"] == 5
    assert second["unchanged"] == 0
    assert {row[0] for row in conn.execute("SELECT dimensions FROM latent_neurons")} == {32}


def test_think_rejects_changed_ollama_embedding_dimensions(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)

    monkeypatch.setattr(
        neural,
        "embed_texts",
        lambda texts, **_kwargs: [[1.0, 0.0, 0.0] for _text in texts],
    )
    build_latent_index(conn, provider="ollama", model="mutable-model")

    monkeypatch.setattr(
        neural,
        "embed_texts",
        lambda texts, **_kwargs: [[1.0, 0.0] for _text in texts],
    )
    with pytest.raises(ValueError, match=r"embedding dimensions changed from 3 to 2.*--rebuild"):
        think(conn, "family travel", provider="ollama", model="mutable-model")


def test_zero_weight_edges_are_not_indexed_as_synaptic_evidence(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _seed(conn)

    travel = next(row for row in _neuron_rows(conn) if row["id"] == "travel")

    assert "Forgotten evidence" not in _neuron_text(travel)


def test_public_neural_apis_preserve_caller_row_factory(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    original = lambda _cursor, row: tuple(row)
    conn.row_factory = original

    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)
    assert conn.row_factory is original
    think(conn, "family travel", provider="hash", model="hash-v1", seeds=1, hops=0)
    assert conn.row_factory is original


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
    assert "Unverified airport rumor" not in names
    passport = next(item for item in result["activated_neurons"] if item["name"] == "Renew passport")
    assert passport["reason"]["kind"] == "synapse"
    assert passport["reason"]["relation"] == "requires"
    assert all(item["truth_policy"] == "provenance_not_fact" for item in result["activated_neurons"])
    assert result["contract"] == {"name": "mneme-agent-brain", "version": "mneme-agent-brain-v1"}
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


def _seed_named_entities(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("kestrelwood", "person", "Kestrelwood expedition contact", "People/kestrelwood.md", "2026-01-01", "2026-01-01"),
            ("similar1", "note", "Coastal trip notes", "Notes/coastal.md", "2026-01-01", "2026-01-01"),
            ("similar2", "note", "Highland expedition plan", "Notes/highland.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_exact_lexical_match_rescues_node_with_poor_embedding(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_named_entities(conn)

    def index_embed(texts, **_kwargs):
        return [[0.0, 0.0, 1.0] if "Kestrelwood" in text else [1.0, 0.0, 0.0] for text in texts]

    monkeypatch.setattr(neural, "embed_texts", index_embed)
    build_latent_index(conn, provider="ollama", model="fixed-vec")

    def query_embed(texts, **_kwargs):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(neural, "embed_texts", query_embed)
    result = think(conn, "Find notes about Kestrelwood", provider="ollama", model="fixed-vec", seeds=2, hops=0)

    names = [item["name"] for item in result["activated_neurons"]]
    assert "Kestrelwood expedition contact" in names
    rescued = next(item for item in result["activated_neurons"] if item["name"] == "Kestrelwood expedition contact")
    assert rescued["reason"]["kind"] in {"lexical_seed", "hybrid_seed"}
    assert rescued["activation"] > 0
    assert "kestrelwood" in rescued["reason"]["signals"]["lexical"]["matched_tokens"]


def _seed_stopword_bait(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("bait", "note", "Status update for review", "Notes/status.md", "2026-01-01", "2026-01-01"),
            ("filler1", "note", "Garden watering schedule", "Notes/garden.md", "2026-01-01", "2026-01-01"),
            ("filler2", "note", "Recipe collection", "Notes/recipes.md", "2026-01-01", "2026-01-01"),
            ("target", "task", "Plan quarterly offsite", "Projects/offsite.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_stopword_only_overlap_does_not_create_lexical_seed(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_stopword_bait(conn)

    def index_embed(texts, **_kwargs):
        return [[1.0, 0.0] if "Plan quarterly offsite" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(neural, "embed_texts", index_embed)
    build_latent_index(conn, provider="ollama", model="stopword-v1")

    def query_embed(texts, **_kwargs):
        return [[0.0, 0.0] for _ in texts]

    monkeypatch.setattr(neural, "embed_texts", query_embed)
    result = think(
        conn, "reserve a slot for the quarterly offsite", provider="ollama", model="stopword-v1", seeds=3, hops=0
    )

    names = [item["name"] for item in result["activated_neurons"]]
    assert "Status update for review" not in names
    assert "Plan quarterly offsite" in names
    rescued = next(item for item in result["activated_neurons"] if item["name"] == "Plan quarterly offsite")
    assert rescued["reason"]["kind"] in {"lexical_seed", "hybrid_seed"}
    matched = rescued["reason"]["signals"]["lexical"]["matched_tokens"]
    assert "for" not in matched
    assert "the" not in matched
    assert "a" not in matched


def test_semantic_retrieval_without_lexical_overlap_still_works(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("flight", "task", "Book flight reservation", "Projects/travel.md", "2026-01-01", "2026-01-01"),
            ("groceries", "task", "Buy groceries", "Notes/home.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()

    def fixed_embed(texts, **_kwargs):
        return [
            [1.0, 0.0] if ("flight" in text.lower() or "airplane" in text.lower()) else [0.0, 1.0]
            for text in texts
        ]

    monkeypatch.setattr(neural, "embed_texts", fixed_embed)
    build_latent_index(conn, provider="ollama", model="semantic-v1")

    result = think(conn, "need airplane transport arrangements", provider="ollama", model="semantic-v1", seeds=1, hops=0)

    names = [item["name"] for item in result["activated_neurons"]]
    assert names == ["Book flight reservation"]
    assert result["activated_neurons"][0]["reason"]["kind"] == "latent_seed"


def _seed_generic_tokens(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("a", "task", "Alpha item", "Notes/alpha.md", "2026-01-01", "2026-01-01"),
            ("b", "task", "Beta item", "Notes/beta.md", "2026-01-01", "2026-01-01"),
            ("c", "task", "Gamma item", "Notes/gamma.md", "2026-01-01", "2026-01-01"),
            ("target", "task", "Delta item", "Notes/delta.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_ubiquitous_token_does_not_trigger_lexical_seeding(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_generic_tokens(conn)

    def fixed_embed(texts, **_kwargs):
        return [[1.0, 0.0] if "Delta item" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(neural, "embed_texts", fixed_embed)
    build_latent_index(conn, provider="ollama", model="generic-v1")

    result = think(conn, "looking for a task", provider="ollama", model="generic-v1", seeds=1, hops=0)

    names = [item["name"] for item in result["activated_neurons"]]
    assert "Delta item" not in names
    assert names == ["Alpha item"]


def _add_observations(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        [
            ("o1", "travel", "fact", "Trip is planned for August 2026.", "Projects/travel.md", 1.0, "2026-01-01"),
            ("o2", "passport", "fact", "Passport appointment booked for March.", "Projects/travel.md", 1.0, "2026-01-01"),
        ],
    )
    conn.commit()


def test_activated_neurons_are_hydrated_with_grounded_evidence(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    _add_observations(conn)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "family travel to Athens", provider="hash", model="hash-v1", seeds=1, hops=2)

    travel = next(item for item in result["activated_neurons"] if item["name"] == "Athens family travel")
    travel_texts = {item["text"] for item in travel["evidence"]}
    assert "Trip is planned for August 2026." in travel_texts
    assert "Passport is required before travel" in travel_texts

    passport = next(item for item in result["activated_neurons"] if item["name"] == "Renew passport")
    passport_texts = {item["text"] for item in passport["evidence"]}
    assert "Passport appointment booked for March." in passport_texts

    assert "Trip is planned for August 2026." in result["context"]


def test_evidence_excludes_candidate_killed_and_zero_weight_edges(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "family travel to Athens", provider="hash", model="hash-v1", seeds=1, hops=2)

    travel = next(item for item in result["activated_neurons"] if item["name"] == "Athens family travel")
    texts = {item["text"] for item in travel["evidence"]}
    assert "Wrong historical link" not in texts
    assert "Unverified candidate" not in texts
    assert "Forgotten evidence" not in texts


def test_evidence_is_deduplicated_and_capped(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    conn.executemany(
        "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
        [
            ("o1", "travel", "fact", "Repeated travel fact.", "Projects/travel.md", 1.0, "2026-01-01"),
            ("o2", "travel", "fact", "Repeated travel fact.", "Projects/travel.md", 1.0, "2026-01-01"),
            ("o3", "travel", "fact", "Second travel fact.", "Projects/travel.md", 1.0, "2026-01-01"),
            ("o4", "travel", "fact", "Third travel fact.", "Projects/travel.md", 1.0, "2026-01-01"),
            ("o5", "travel", "fact", "Fourth travel fact.", "Projects/travel.md", 1.0, "2026-01-01"),
        ],
    )
    conn.commit()
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "family travel to Athens", provider="hash", model="hash-v1", seeds=1, hops=0)

    travel = next(item for item in result["activated_neurons"] if item["name"] == "Athens family travel")
    texts = [item["text"] for item in travel["evidence"]]
    assert texts.count("Repeated travel fact.") == 1
    assert len(travel["evidence"]) <= 3


def _seed_calendar_node(conn: sqlite3.Connection, metadata_json: str) -> None:
    init_db(conn)
    conn.execute(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        ("appt", "task", "Doctor appointment", "gws://calendar/appt-1", "2026-01-01", "2026-01-01"),
    )
    conn.execute(
        """INSERT INTO sense_events(id,sense_id,sense_type,source_id,source_uri,event_type,title,text_hash,
                                     observed_at,ingested_at,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "se1",
            "gws",
            "gws",
            "calendar_event:appt-1",
            "gws://calendar/appt-1",
            "calendar_event",
            "Doctor appointment",
            "hash",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            metadata_json,
        ),
    )
    conn.commit()


def test_calendar_node_evidence_hydrates_from_matching_sense_event(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    metadata_json = json.dumps(
        {
            "gws": {
                "summary": "Doctor appointment",
                "start": {"dateTime": "2026-08-03T09:00:00-04:00"},
                "end": {"dateTime": "2026-08-03T09:30:00-04:00"},
                "description": "Bring insurance card and prior test results.",
            }
        }
    )
    _seed_calendar_node(conn, metadata_json)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0)

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    sense_items = [item for item in appt["evidence"] if item["kind"] == "sense_event"]
    assert len(sense_items) == 1
    item = sense_items[0]
    assert item["event_type"] == "calendar_event"
    assert "Doctor appointment" in item["text"]
    assert "2026-08-03T09:00:00-04:00" in item["text"]
    assert "2026-08-03T09:30:00-04:00" in item["text"]
    assert "Bring insurance card" in item["text"]
    assert "2026-01-01T00:00:00Z" not in item["text"]


def test_calendar_node_evidence_handles_malformed_metadata_safely(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_calendar_node(conn, "not valid json{{")
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0)

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    sense_items = [item for item in appt["evidence"] if item["kind"] == "sense_event"]
    assert len(sense_items) == 1
    assert sense_items[0]["text"] == "Doctor appointment"


def test_calendar_node_evidence_with_empty_metadata_uses_title_only(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_calendar_node(conn, "{}")
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0)

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    sense_items = [item for item in appt["evidence"] if item["kind"] == "sense_event"]
    assert len(sense_items) == 1
    assert sense_items[0]["text"] == "Doctor appointment"


def _seed_decay_node(
    conn: sqlite3.Connection,
    *,
    node_name: str = "Doctor appointment",
    metadata_json: str,
    observed_at: str = "2000-01-01T00:00:00Z",
) -> None:
    init_db(conn)
    conn.execute(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        ("appt-decay", "task", node_name, "gws://calendar/appt-decay", "2026-01-01", "2026-01-01"),
    )
    conn.execute(
        """INSERT INTO sense_events(id,sense_id,sense_type,source_id,source_uri,event_type,title,text_hash,
                                     observed_at,ingested_at,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "se-decay",
            "gws",
            "gws",
            "calendar_event:appt-decay",
            "gws://calendar/appt-decay",
            "calendar_event",
            "Doctor appointment",
            "hash",
            observed_at,
            "2026-01-01T00:00:00Z",
            metadata_json,
        ),
    )
    conn.commit()


def test_past_calendar_event_decays_based_on_structured_event_time(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    metadata_json = json.dumps(
        {
            "gws": {
                # A stale start should be ignored in favor of the end time.
                "start": {"dateTime": "2020-01-01T00:00:00Z"},
                "end": {"dateTime": "2026-06-01T09:30:00Z"},
            }
        }
    )
    _seed_decay_node(conn, metadata_json=metadata_json)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(
        conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now="2026-07-01T00:00:00Z"
    )

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    assert appt["reason"]["temporal_decay"] == pytest.approx(0.513417, abs=1e-5)
    assert appt["activation"] < 1.0


def test_future_calendar_event_is_not_decayed(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    metadata_json = json.dumps(
        {
            "gws": {
                "start": {"dateTime": "2026-12-01T09:00:00Z"},
                "end": {"dateTime": "2026-12-01T10:00:00Z"},
            }
        }
    )
    _seed_decay_node(conn, metadata_json=metadata_json)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(
        conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now="2026-07-01T00:00:00Z"
    )

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    assert appt["reason"]["temporal_decay"] == pytest.approx(1.0)


def test_sense_event_observed_at_alone_does_not_cause_event_time_decay(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    # No gws start/end at all -- only an ancient observed_at (ingestion time).
    _seed_decay_node(conn, metadata_json="{}", observed_at="2000-01-01T00:00:00Z")
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(
        conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now="2026-07-01T00:00:00Z"
    )

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
    assert appt["reason"]["temporal_decay"] == pytest.approx(1.0)


def test_malformed_gws_dates_degrade_safely_to_name_source_path_decay(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    metadata_json = json.dumps({"gws": {"start": {"dateTime": "not-a-date"}, "end": {"dateTime": "also-bad"}}})
    # Name carries an old regex-matchable date so the fallback path is exercised.
    _seed_decay_node(conn, node_name="Doctor appointment 2020-01-01", metadata_json=metadata_json)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(
        conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now="2026-07-01T00:00:00Z"
    )

    appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment 2020-01-01")
    # Old, non-project source path floors at 0.15 -- confirms the legacy path ran (not 1.0).
    assert appt["reason"]["temporal_decay"] == pytest.approx(0.15)


def _seed_rescue_lane(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executemany(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        [
            ("semantic-a", "project", "Market expansion plan", "Projects/market.md", "2026-01-01", "2026-01-01"),
            ("semantic-b", "project", "Customer acquisition plan", "Projects/customers.md", "2026-01-01", "2026-01-01"),
            ("lexical-a", "note", "Orchid software handbook", "Notes/orchid-a.md", "2026-01-01", "2026-01-01"),
            ("lexical-b", "note", "Orchid software checklist", "Notes/orchid-b.md", "2026-01-01", "2026-01-01"),
            ("lexical-c", "note", "Orchid software archive", "Notes/orchid-c.md", "2026-01-01", "2026-01-01"),
        ],
    )
    conn.commit()


def test_broad_lexical_overlap_does_not_outrank_stronger_semantic_match(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_rescue_lane(conn)

    def fixed_embed(texts, **_kwargs):
        vectors = []
        for text in texts:
            if "Market expansion" in text or "commercial opportunity" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    monkeypatch.setattr(neural, "embed_texts", fixed_embed)
    build_latent_index(conn, provider="ollama", model="rescue-v1")

    result = think(
        conn,
        "commercial opportunity for software",
        provider="ollama",
        model="rescue-v1",
        seeds=1,
        lexical_seeds=1,
        hops=0,
    )

    assert result["activated_neurons"][0]["name"] == "Market expansion plan"


def test_lexical_rescue_quota_preserves_requested_latent_seeds(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed_rescue_lane(conn)

    def fixed_embed(texts, **_kwargs):
        vectors = []
        for text in texts:
            if "Market expansion" in text or "Customer acquisition" in text or "commercial strategy" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    monkeypatch.setattr(neural, "embed_texts", fixed_embed)
    build_latent_index(conn, provider="ollama", model="quota-v1")

    result = think(
        conn,
        "orchid commercial strategy",
        provider="ollama",
        model="quota-v1",
        seeds=2,
        lexical_seeds=1,
        hops=0,
        limit=10,
    )

    names = [item["name"] for item in result["activated_neurons"]]
    assert "Market expansion plan" in names
    assert "Customer acquisition plan" in names
    lexical_only = [item for item in result["activated_neurons"] if item["reason"]["kind"] == "lexical_seed"]
    assert len(lexical_only) == 1
    assert lexical_only[0]["reason"]["signals"]["lexical"]["raw_score"] > 0
    assert lexical_only[0]["reason"]["signals"]["lexical"]["calibrated_score"] < 1


def test_latest_sense_event_revision_controls_decay_and_hydrated_evidence(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    stale = json.dumps(
        {"gws": {"end": {"dateTime": "2025-01-01T10:00:00Z"}, "description": "Stale appointment details."}}
    )
    _seed_calendar_node(conn, stale)
    current = json.dumps(
        {"gws": {"end": {"dateTime": "2026-08-01T10:00:00Z"}, "description": "Current appointment details."}}
    )
    conn.execute(
        """INSERT INTO sense_events(id,sense_id,sense_type,source_id,source_uri,event_type,title,text_hash,
                                     observed_at,ingested_at,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "se2",
            "gws",
            "gws",
            "calendar_event:appt-1",
            "gws://calendar/appt-1",
            "calendar_event",
            "Doctor appointment",
            "hash-2",
            "2026-06-01T00:00:00Z",
            "2026-06-01T00:00:00Z",
            current,
        ),
    )
    conn.commit()
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    def run():
        result = think(
            conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now="2026-07-01T00:00:00Z"
        )
        return next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")

    before = run()
    conn.execute("CREATE INDEX sense_events_revision_probe ON sense_events(source_uri,observed_at)")
    after = run()

    for appt in (before, after):
        assert appt["reason"]["temporal_decay"] == pytest.approx(1.0)
        sense_items = [item for item in appt["evidence"] if item["kind"] == "sense_event"]
        assert len(sense_items) == 1
        assert "Current appointment details." in sense_items[0]["text"]
        assert "Stale appointment details." not in sense_items[0]["text"]


def test_hydrated_evidence_is_size_bounded(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    conn.execute(
        """INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("long", "travel", "fact", "x" * 10_000, "Projects/travel.md", 1.0, "2026-01-01"),
    )
    conn.commit()
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    result = think(conn, "Athens family travel", provider="hash", model="hash-v1", seeds=1, hops=0)

    travel = next(item for item in result["activated_neurons"] if item["name"] == "Athens family travel")
    assert len(travel["evidence"][0]["text"]) <= neural.EVIDENCE_TEXT_LIMIT
    assert travel["evidence"][0]["text"].endswith("...")


def test_exact_full_name_rescues_single_neuron_index(tmp_path: Path, monkeypatch):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.execute(
        "INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        ("only", "project", "Quillhaven", "Projects/quillhaven.md", "2026-01-01", "2026-01-01"),
    )
    conn.commit()

    def fixed_embed(texts, **_kwargs):
        return [[1.0, 0.0] if "Quillhaven" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(neural, "embed_texts", fixed_embed)
    build_latent_index(conn, provider="ollama", model="single-v1")

    result = think(conn, "What is Quillhaven?", provider="ollama", model="single-v1", seeds=1, hops=0)

    reason = result["activated_neurons"][0]["reason"]
    assert reason["kind"] == "hybrid_seed"
    assert reason["signals"]["lexical"]["matched_tokens"] == ["quillhaven"]


def test_negative_evidence_cap_is_rejected(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    _seed(conn)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    with pytest.raises(ValueError, match="evidence_cap"):
        think(conn, "travel", provider="hash", model="hash-v1", evidence_cap=-1)


def test_timestamped_event_decay_is_invariant_across_equivalent_now_offsets(tmp_path: Path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    metadata_json = json.dumps({"gws": {"end": {"dateTime": "2026-07-01T00:30:00+03:00"}}})
    _seed_decay_node(conn, metadata_json=metadata_json)
    build_latent_index(conn, provider="hash", model="hash-v1", dimensions=64)

    def decay(now: str) -> float:
        result = think(conn, "doctor appointment", provider="hash", model="hash-v1", seeds=1, hops=0, now=now)
        appt = next(item for item in result["activated_neurons"] if item["name"] == "Doctor appointment")
        return appt["reason"]["temporal_decay"]

    utc_decay = decay("2026-07-01T00:15:00Z")
    athens_decay = decay("2026-07-01T03:15:00+03:00")

    assert utc_decay == pytest.approx(math.exp(-1 / 45), abs=1e-6)
    assert athens_decay == pytest.approx(utc_decay)
