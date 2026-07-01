import json
import sqlite3

from mneme.core import forget_past_dates, forget_source, ingest_vault, init_db, update_vault
from mneme.world_model import ensure_world_model_schema


def _seed_world_model_rows(db_path):
    conn = sqlite3.connect(db_path)
    init_db(conn)
    ensure_world_model_schema(conn)
    conn.execute(
        """
        INSERT INTO world_state_assertions(
          id, subject_name, predicate, object_value, evidence_text, source_path,
          confidence, certainty, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "wsa-fictional-deadline",
            "Fictional Project",
            "has_due_date",
            "2026-08-01",
            "Fictional receipt confirms the due date.",
            "mneme://test/fictional-project",
            0.95,
            "confirmed",
            "2026-07-01T00:00:00+00:00",
            "2026-07-01T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO world_predictions(
          id, title, subject_assertion_id, match_json, check_after, expires_at,
          confidence, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            "wp-fictional-check",
            "Fictional confirmation appears",
            "wsa-fictional-deadline",
            json.dumps({"sense_type": "md", "title_terms": ["fictional"], "text_terms": ["deadline"]}),
            "2026-07-02T00:00:00+00:00",
            "2026-08-02T00:00:00+00:00",
            0.7,
            "2026-07-01T00:00:00+00:00",
            "2026-07-01T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO world_actions(
          id, actor, action_type, title, side_effect_level, source_path, created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            "wa-fictional-note",
            "mneme",
            "note_written",
            "Fictional note recorded",
            "local_write",
            "mneme://test/fictional-project",
            "2026-07-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()


def _world_counts(db_path):
    conn = sqlite3.connect(db_path)
    counts = dict(
        conn.execute(
            """
            SELECT 'assertions', COUNT(*) FROM world_state_assertions
            UNION ALL SELECT 'predictions', COUNT(*) FROM world_predictions
            UNION ALL SELECT 'actions', COUNT(*) FROM world_actions
            """
        ).fetchall()
    )
    conn.close()
    return counts


def test_rebuild_update_and_soft_forget_preserve_world_model_rows(tmp_path):
    db = tmp_path / "mneme.sqlite"
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "project.md").write_text(
        "# Fictional Project\n\n- [ ] Confirm fictional deadline by 2026-08-01\n",
        encoding="utf-8",
    )
    _seed_world_model_rows(db)

    before = _world_counts(db)
    ingest_vault(vault, db, hints=["deadline"])
    after_rebuild = _world_counts(db)
    update_vault(vault, db, hints=["deadline"])
    after_update = _world_counts(db)
    forget_past_dates(db, days_threshold=1)
    after_soft_forget = _world_counts(db)

    assert before == {"assertions": 1, "predictions": 1, "actions": 1}
    assert after_rebuild == before
    assert after_update == before
    assert after_soft_forget == before


def test_world_model_schema_does_not_require_generated_artifacts_or_private_vault_paths(tmp_path):
    db = tmp_path / "mneme.sqlite"
    _seed_world_model_rows(db)

    conn = sqlite3.connect(db)
    source_paths = [row[0] for row in conn.execute("SELECT source_path FROM world_state_assertions")]
    action_paths = [row[0] for row in conn.execute("SELECT source_path FROM world_actions")]
    conn.close()

    assert source_paths == ["mneme://test/fictional-project"]
    assert action_paths == ["mneme://test/fictional-project"]
    assert not list(tmp_path.glob("world-model-export*.json"))
    assert not list(tmp_path.glob("thought_*.png"))


def test_explicit_scoped_forget_cascades_world_model_rows(tmp_path):
    db = tmp_path / "mneme.sqlite"
    _seed_world_model_rows(db)

    result = forget_source(db, "mneme://test/fictional-project")

    assert result["world_model_removed"] == {
        "world_state_assertions": 1,
        "world_predictions": 1,
        "world_actions": 1,
    }
    assert _world_counts(db) == {"assertions": 0, "predictions": 0, "actions": 0}


def test_explicit_scoped_forget_dry_run_preserves_world_model_rows(tmp_path):
    db = tmp_path / "mneme.sqlite"
    _seed_world_model_rows(db)

    result = forget_source(db, "mneme://test/fictional-project", dry_run=True)

    assert result["dry_run"] is True
    assert result["world_model_removed"] == {
        "world_state_assertions": 1,
        "world_predictions": 1,
        "world_actions": 1,
    }
    assert _world_counts(db) == {"assertions": 1, "predictions": 1, "actions": 1}
