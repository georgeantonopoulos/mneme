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


def test_reflect_and_thoughts_from_the_command_line(tmp_path: Path, capsys, monkeypatch):
    from test_cortex import ReflectingMind

    class Mind(ReflectingMind, AnsweringMind):
        pass

    root = _vault(tmp_path)
    home = tmp_path / "home"
    assert _run(capsys, "setup", "--home", str(home), "--notes", str(root), "--mind", "command", "--command", "true",
                "--skip-test", "--yes", "--json")[0] == 0
    monkeypatch.setattr(app, "build_mind", lambda config, home: Mind())
    assert _run(capsys, "reflect", "--home", str(home), "--json")[1]["ok"] is False  # nothing learned yet
    assert _run(capsys, "learn", "--home", str(home), "--json")[0] == 0
    code, out = _run(capsys, "reflect", "--home", str(home), "--as-of", "2026-07-02", "--json")
    assert code == 0 and out["raised"] == 1 and out["links"] == 1
    (thought,) = out["thoughts"]
    assert thought["text"] == "Mooring renewal is due soon" and thought["evidence"][0]["refs"]
    code, listed = _run(capsys, "thoughts", "--home", str(home), "--json")
    assert code == 0 and [t["id"] for t in listed["thoughts"]] == [thought["id"]]
    app.run(["thoughts", "--home", str(home)])
    drawn = capsys.readouterr().out
    assert "Mooring renewal is due soon" in drawn and f"#{thought['id']}" in drawn
    assert _run(capsys, "thoughts", "--home", str(home), "--dismiss", str(thought["id"]), "--json")[1] == {"ok": True, "dismissed": thought["id"]}
    assert _run(capsys, "thoughts", "--home", str(home), "--json")[1]["thoughts"] == []
    assert _run(capsys, "thoughts", "--home", str(home), "--dismiss", "999", "--json")[0] == 1
    app.run(["thoughts", "--home", str(home)])  # the drawn view renders without error
    assert "Nothing needs your attention" in capsys.readouterr().out


def test_learn_json_prints_one_json_object(tmp_path: Path, capsys, monkeypatch):
    root = _vault(tmp_path)
    home = tmp_path / "home"
    assert _run(capsys, "setup", "--home", str(home), "--notes", str(root), "--mind", "command", "--command", "true",
                "--skip-test", "--yes", "--json")[0] == 0
    monkeypatch.setattr(app, "build_mind", lambda config, home: AnsweringMind())
    assert app.run(["learn", "--home", str(home), "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["perceived"] == 4  # the whole of stdout parses: progress went to stderr


def test_two_notes_folders_with_the_same_file_stay_separate(tmp_path: Path, capsys, monkeypatch):
    for name, text in (("work", "Quarterly plan for the studio"), ("home", "Garden plan for spring")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "Plan.md").write_text(f"# Plan\n\n{text}\n", encoding="utf-8")
    home = tmp_path / "mneme"
    assert _run(capsys, "setup", "--home", str(home), "--notes", str(tmp_path / "work"), "--notes", str(tmp_path / "home"),
                "--mind", "command", "--command", "true", "--skip-test", "--yes", "--json")[0] == 0
    monkeypatch.setattr(app, "build_mind", lambda config, home: AnsweringMind())
    assert _run(capsys, "learn", "--home", str(home), "--json")[1]["new"] == 2
    assert _run(capsys, "learn", "--home", str(home), "--json")[1]["new"] == 0  # and nothing is mistaken for an edit


def test_a_file_mind_resumes_the_same_question_after_the_clock_moves(tmp_path: Path, capsys, monkeypatch):
    import datetime as real_dt

    root = _vault(tmp_path)
    home = tmp_path / "home"
    assert _run(capsys, "setup", "--home", str(home), "--notes", str(root), "--mind", "file", "--skip-test", "--yes", "--json")[0] == 0
    config = json.loads((home / "brain.json").read_text())
    outbox, answers = Path(config["mind"]["path"]) / "outbox", Path(config["mind"]["path"]) / "answers"
    from test_cortex import ReflectingMind

    class Mind(ReflectingMind, AnsweringMind):
        pass

    mind = Mind()

    def answer_all():
        for task in outbox.glob("*.json"):
            prompt = json.loads(task.read_text())["prompt"]
            payload = json.loads(prompt.split("INPUT (JSON):\n", 1)[1].strip())
            (answers / task.name).write_text(json.dumps(getattr(mind, task.name.rsplit("-", 1)[0])(payload)))
            task.unlink()

    for _ in range(6):  # learn takes a few rounds of answering
        if _run(capsys, "learn", "--home", str(home), "--json")[0] == 0:
            break
        answer_all()

    clock = {"now": real_dt.datetime(2026, 6, 1, 9, 0, tzinfo=real_dt.timezone.utc)}

    class FakeDateTime(real_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(app.dt, "datetime", FakeDateTime)
    asked = ["ask", "--home", str(home), "When is the mooring renewal due?", "--json"]
    code = _run(capsys, *asked)[0]
    rounds = 0
    while code == 2 and rounds < 6:
        answer_all()
        clock["now"] += real_dt.timedelta(minutes=7)  # the agent takes a while to answer
        code, out = _run(capsys, *asked)
        rounds += 1
    assert code == 0 and out["as_of"] == "2026-06-01T09:00:00+00:00" and out["evidence"]
    import sqlite3

    pinned = sqlite3.connect(config["db"]).execute("SELECT value FROM meta WHERE key LIKE 'pending:%'").fetchall()
    assert pinned == [("",)]  # settled once answered

    reflect = ["reflect", "--home", str(home), "--json"]  # a reflection resumes the same way
    code, rounds = _run(capsys, *reflect)[0], 0
    while code == 2 and rounds < 6:
        answer_all()
        clock["now"] += real_dt.timedelta(minutes=7)
        code, out = _run(capsys, *reflect)
        rounds += 1
    assert code == 0 and out["raised"] >= 1
