import json
import sqlite3
from pathlib import Path

from mneme.cli import main


def test_action_record_cli_requires_external_handle_for_side_effects(tmp_path: Path, capsys):
    db = tmp_path / "mneme.sqlite"
    missing = tmp_path / "missing.json"
    missing.write_text(
        json.dumps(
            {
                "id": "act-missing-handle",
                "actor": "test-agent",
                "action_type": "calendar_event_created",
                "title": "Created calendar event without handle",
                "side_effect_level": "private_external",
                "reversibility": "reversible",
            }
        ),
        encoding="utf-8",
    )

    try:
        main(["action", "record", "--db", str(db), "--file", str(missing)])
    except ValueError as exc:
        assert "external_ref or tool_call_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected missing handle to fail")

    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps(
            {
                "id": "act-with-handle",
                "actor": "test-agent",
                "action_type": "calendar_event_created",
                "title": "Created calendar event",
                "tool_name": "gws calendar events insert",
                "tool_call_id": "tool-call-123",
                "side_effect_level": "private_external",
                "reversibility": "reversible",
                "external_ref": "calendar:event:abc123",
                "status": "recorded",
                "metadata": {"source": "test"},
            }
        ),
        encoding="utf-8",
    )

    main(["action", "record", "--db", str(db), "--file", str(valid)])
    result = json.loads(capsys.readouterr().out)

    assert result["id"] == "act-with-handle"
    assert result["external_ref"] == "calendar:event:abc123"
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM world_actions WHERE id='act-with-handle'").fetchone()[0]
    conn.close()
    assert count == 1
