import json
import sqlite3

import pytest

from mneme.cli import main
from mneme.core import init_db


@pytest.mark.parametrize(
    "argv",
    [
        ["doctor", "--json"],
        ["retrieve", "--json"],
        ["brain", "report", "--json"],
    ],
)
def test_commands_that_already_emit_json_reject_json_flag(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 2
    assert "unrecognized arguments: --json" in capsys.readouterr().err


def test_surface_render_requires_absolute_out_path(tmp_path):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.close()

    with pytest.raises(SystemExit) as exc:
        main(["surface", "--db", str(db), "--render", "--out", "relative-out"])

    assert "--out must be an absolute path" in str(exc.value)


def test_surface_without_render_ignores_relative_out_env(tmp_path, monkeypatch, capsys):
    db = tmp_path / "mneme.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.close()
    monkeypatch.setenv("MNEME_OUT", "relative-out")

    main(["surface", "--db", str(db)])

    result = json.loads(capsys.readouterr().out)

    assert result == []


def test_run_once_requires_absolute_out_path(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n\n- [ ] Follow up by 2026-07-01\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main([
            "run-once",
            "--vault", str(vault),
            "--db", str(tmp_path / "mneme.sqlite"),
            "--out", "relative-out",
        ])

    assert "--out must be an absolute path" in str(exc.value)
