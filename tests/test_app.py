"""The setup / learn / ask / status front door, driven the way an agent would drive it (flags and --json)."""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

from test_cortex import ScriptedMind, _vault

from mneme.cortex import app
from mneme.cortex.senses import read_sources


class AnsweringMind(ScriptedMind):
    def answer(self, payload):
        return {"answer": f"From {len(payload['memories'])} memories.", "cites": [payload["memories"][0]["id"]]}


def _run(capsys, *argv) -> tuple[int, dict]:
    code = app.run(list(argv))
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def _ollama_stub():
    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, payload):
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"models": [{"name": "tiny:1b"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/tags":
                return self._send({"models": [{"name": "tiny:1b"}]})
            assert body["format"] == "json" and body["model"] == "tiny:1b"
            self._send({"message": {"content": '{"ok": true}'}})

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_setup_without_prompts_tests_the_mind_and_saves(tmp_path: Path, capsys):
    root = _vault(tmp_path)
    server = _ollama_stub()
    try:
        code, out = _run(capsys, "setup", "--home", str(tmp_path / "home"), "--notes", str(root), "--mind", "ollama",
                         "--model", "tiny:1b", "--url", f"http://127.0.0.1:{server.server_port}", "--yes", "--json")
    finally:
        server.shutdown()
    assert code == 0 and out["ok"] and out["memories"] == 4 and out["test_seconds"] is not None
    config = json.loads((tmp_path / "home" / "brain.json").read_text())
    assert config["mind"] == {"provider": "ollama", "host": f"http://127.0.0.1:{server.server_port}", "model": "tiny:1b"}


def test_setup_reports_an_unreachable_mind_and_saves_nothing(tmp_path: Path, capsys):
    root = _vault(tmp_path)
    code, out = _run(capsys, "setup", "--home", str(tmp_path / "home"), "--notes", str(root), "--mind", "ollama",
                     "--model", "x", "--url", "http://127.0.0.1:9", "--yes", "--json")
    assert code == 1 and "Could not reach" in out["error"]
    assert not (tmp_path / "home" / "brain.json").exists()


def test_learn_ask_status_end_to_end(tmp_path: Path, capsys, monkeypatch):
    root = _vault(tmp_path)
    home = tmp_path / "home"
    assert _run(capsys, "setup", "--home", str(home), "--notes", str(root), "--mind", "command", "--command", "true",
                "--skip-test", "--yes", "--json")[0] == 0
    monkeypatch.setattr(app, "build_mind", lambda config, home: AnsweringMind())

    code, learned = _run(capsys, "learn", "--home", str(home), "--json")
    assert code == 0 and learned["memories"] == 4 and learned["perceived"] == 4

    code, again = _run(capsys, "learn", "--home", str(home), "--json")
    assert code == 0 and again["new"] == 0 and again["perceived"] == 0  # nothing new, nothing re-perceived

    code, asked = _run(capsys, "ask", "--home", str(home), "--json", "When", "is", "the", "mooring", "renewal?",
                       "--as-of", "2026-06-10")
    assert code == 0 and asked["evidence"] and asked["answer"].startswith("From") and asked["cites"] == ["m1"]

    code, status = _run(capsys, "status", "--home", str(home), "--json")
    assert code == 0 and status["brain"]["neurons"] == 4 and status["brain"]["pending"] == 0


def test_commands_explain_what_to_do_before_setup(tmp_path: Path, capsys):
    assert _run(capsys, "status", "--home", str(tmp_path), "--json") == (1, {"ok": False, "set_up": False, "home": str(tmp_path)})
    code, out = _run(capsys, "ask", "--home", str(tmp_path), "--json", "anything")
    assert code == 1 and "mneme setup" in out["error"]


def test_a_plain_notes_folder_is_a_vault(tmp_path: Path):
    (tmp_path / "Ideas.md").write_text("# Ideas\n\nBuild a boat.\n", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "Hidden.md").write_text("# Hidden\n\nskip me\n", encoding="utf-8")
    titles = [e.title for e in read_sources(tmp_path)]
    assert titles == ["Ideas"]


def test_welcome_screen_without_arguments(capsys):
    assert app.run([]) == 0
    assert "mneme setup" in capsys.readouterr().out
