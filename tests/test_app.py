"""The setup / learn / ask / status front door, driven the way an agent would drive it (flags and --json)."""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from test_cortex import ScriptedMind, _vault

from mneme.cortex import app
from mneme.cortex.senses import read_sources


@pytest.fixture(autouse=True)
def _no_earlier_install(tmp_path, monkeypatch):
    """Setup looks for an earlier `mneme init`; tests must never find the developer's real one."""
    monkeypatch.setenv("MNEME_CONFIG", str(tmp_path / "no-earlier-install.json"))


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


def _earlier_graph(tmp_path: Path) -> Path:
    """A graph database written by the earlier Mneme's own schema code."""
    import sqlite3

    from mneme.core import init_db
    from mneme.world_model.aliases import ensure_alias_schema
    from mneme.world_model.schema import ensure_world_model_schema

    db = tmp_path / "old" / "mneme.sqlite"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_world_model_schema(conn)
    ensure_alias_schema(conn)
    at = "2026-05-10T09:00:00+00:00"
    conn.executemany("INSERT INTO nodes(id,type,name,source_path,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                     [("n1", "person", "Tom Wren", "Projects/Boat.md", at, at), ("n2", "place", "Harbour", "Projects/Boat.md", at, at),
                      ("n3", "email", "Mooring invoice", "gmail:abc", at, at), ("n4", "task", "Temp", "mneme://test/x", at, at)])
    edge = "INSERT INTO edges(id,src_id,dst_id,relation,source_path,evidence_text,created_at,updated_at,status,source_type) VALUES (?,?,?,?,?,?,?,?,?,?)"
    conn.executemany(edge, [("e1", "n1", "n2", "manages", "research:1", "Tom runs the harbour office", at, at, "active", "research"),
                            ("e2", "n1", "n3", "sent", "gmail:abc", "", at, at, "killed", "gws"),
                            ("e3", "n1", "n2", "lives_at", "research:2", "", at, at, "candidate", "research"),
                            ("e4", "n1", "n2", "links_to", "Projects/Boat.md", "", at, at, "active", "vault")])
    conn.execute("INSERT INTO world_state_assertions(id,subject_name,predicate,object_value,status,evidence_text,source_path,"
                 "created_at,updated_at) VALUES ('s1','Mooring','renewal_due','2026-06-15','current','Harbour chat','chat:1',?,?)", (at, at))
    conn.execute("INSERT INTO world_actions(id,actor,action_type,title,side_effect_level,external_ref,created_at) VALUES "
                 "('a1','hermes','email','Sent the mooring renewal form','external','gmail:sent-1',?)", (at,))
    conn.execute("INSERT INTO world_predictions(id,title,match_json,check_after,expires_at,created_at,updated_at) VALUES "
                 "('p1','Harbour confirms the renewal','{}','2026-06-16','2026-07-01',?,?)", (at, at))
    conn.execute("INSERT INTO entity_aliases VALUES ('the harbourmaster','the harbourmaster','Tom Wren','tom wren','manual',1.0,?,?)", (at, at))
    conn.executemany("INSERT INTO observations(id,note_id,kind,text,source_path,created_at,sense_event_id) VALUES (?,?,?,?,?,?,?)",
                     [("o1", "n3", "fact", "Invoice for mooring, £320, due 15 June", "gmail:abc", at, "se1"),
                      ("o2", "n4", "fact", "temporary agent note", "mneme://test/x", at, "se2"),
                      ("o3", "n1", "fact", "from a note", "Projects/Boat.md", at, None)])
    conn.commit()
    conn.close()
    return db


def test_an_earlier_graph_becomes_memories_read_only(tmp_path: Path):
    import hashlib

    from mneme.cortex.senses import read_graph_db

    db = _earlier_graph(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    episodes = {e.id: e for e in read_graph_db(db)}
    assert set(episodes) == {"state:s1", "action:a1", "prediction:p1", "alias:the harbourmaster", "relation:e1", "relation:e2", "sensed:n3"}
    assert "renewal due 2026-06-15" in episodes["state:s1"].text.replace("_", " ")
    assert episodes["relation:e2"].text.startswith("It is false that Tom Wren sent Mooring invoice")  # a killed edge is a correction
    assert "£320" in episodes["sensed:n3"].text  # what the email sense saw, which no note holds
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before  # never written to


def test_setup_carries_over_an_earlier_install(tmp_path: Path, capsys, monkeypatch):
    root = _vault(tmp_path)
    db = _earlier_graph(tmp_path)
    earlier = tmp_path / "old-config.json"
    earlier.write_text(json.dumps({"vault": str(root), "db": str(db)}), encoding="utf-8")
    monkeypatch.setenv("MNEME_CONFIG", str(earlier))
    home = tmp_path / "home"
    code, out = _run(capsys, "setup", "--home", str(home), "--mind", "command", "--command", "true", "--skip-test", "--yes", "--json")
    config = json.loads((home / "brain.json").read_text())
    assert code == 0 and config["notes"] == [str(root.resolve())] and config["graph_db"] == str(db.resolve())
    assert out["memories"] == 4 + 7  # the vault's memories plus the graph's
    monkeypatch.setattr(app, "build_mind", lambda config, home: AnsweringMind())
    assert _run(capsys, "learn", "--home", str(home), "--json")[1]["new"] == 11
    assert _run(capsys, "learn", "--home", str(home), "--json")[1]["new"] == 0  # nothing re-added on the next run
    assert _run(capsys, "setup", "--home", str(tmp_path / "h2"), "--mind", "command", "--command", "true", "--skip-test",
                "--yes", "--no-graph", "--json")[1]["memories"] == 4
