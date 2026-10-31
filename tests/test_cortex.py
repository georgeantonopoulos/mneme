"""The cortex core is LLM-agnostic: these tests drive it with a scripted mind."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mneme.cortex import AwaitingMind, Brain, FileMind, FunctionMind, Task
from mneme.cortex.mind import parse_json_reply


def _vault(root: Path) -> Path:
    notes = root / "vault" / "Projects"
    notes.mkdir(parents=True)
    (notes / "Boat.md").write_text("---\nupdated: 2026-05-02\n---\n# Boat\n\n- Mooring renewal due 2026-06-01\n", encoding="utf-8")
    (notes / "Garden.md").write_text("---\nupdated: 2026-05-20\n---\n# Garden\n\n- Plant beans in May\n", encoding="utf-8")
    chat = root / "sources" / "chat"
    chat.mkdir(parents=True)
    (chat / "messages.jsonl").write_text(
        json.dumps({"ts": "2026-05-03T10:00", "chat": "Harbour", "from": "Harbour", "text": "Mooring renewal is now due 2026-06-15"}) + "\n"
        + json.dumps({"ts": "2026-07-01T10:00", "chat": "Harbour", "from": "Harbour", "text": "Thanks, renewal received"}) + "\n",
        encoding="utf-8",
    )
    return root


class ScriptedMind:
    """Answers each task kind deterministically, the way an LLM would be asked to."""

    def __init__(self):
        self.seen: list[Task] = []

    def ask_many(self, tasks):
        self.seen.extend(tasks)
        return [getattr(self, task.kind)(task.payload) for task in tasks]

    def regions(self, payload):
        return {"areas": [{"id": "a1", "title": "Home", "description": "", "topics": [
            {"id": "a1.t1", "title": "Boat", "description": ""}, {"id": "a1.t2", "title": "Garden", "description": ""}]}]}

    def perceive(self, payload):
        out = []
        for n in payload["neurons"]:
            garden = "Garden" in n["title"]
            synapses = [{"to": c["id"], "relation": "updates", "weight": 0.9} for c in n["candidates"] if "Mooring" in c["summary"] and not garden]
            out.append({"id": n["id"], "topics": ["a1.t2" if garden else "a1.t1"], "trust": "ok", "trust_reason": "",
                        "synapses": synapses + [{"to": "not-a-neuron", "relation": "x", "weight": 1}]})
        return {"neurons": out}

    def topic_gist(self, payload):
        return {"gist": f"{payload['topic']['title']}: {len(payload['neurons'])} memories"}

    def area_gist(self, payload):
        return {"gist": "home things"}

    def zoom_areas(self, payload):
        return {"areas": ["a1"], "lookups": ["mooring renewal"]}

    def zoom_topics(self, payload):
        return {"topics": ["a1.t1"]}

    def skim_neurons(self, payload):
        return {"open": [c["id"] for c in payload["candidates"]] + ["invented-id"], "note": ""}

    def read_neurons(self, payload):
        ids = [m["id"] for m in payload["memories"]]
        assert all("text" in m for m in payload["memories"])  # opened memories are read in full
        return {"evidence": list(reversed(ids)) + ["invented-id"], "note": ""}


def test_perceive_and_recall_with_any_mind(tmp_path: Path):
    mind = ScriptedMind()
    brain = Brain(tmp_path / "c.sqlite", mind)
    assert brain.ingest_sources(_vault(tmp_path))["neurons"] == 4
    stats = brain.perceive()
    assert stats["regions"] == 1
    assert brain.conn.execute("SELECT count(*) FROM synapses WHERE dst = 'not-a-neuron'").fetchone()[0] == 0
    assert brain.conn.execute("SELECT count(*) FROM synapses").fetchone()[0] > 0
    gists = dict(brain.conn.execute("SELECT id, gist FROM regions"))
    assert gists["a1.t1"].startswith("Boat") and gists["a1"] == "home things"

    hits = brain.recall("When is the mooring renewal due?", as_of="2026-06-01T00:00:00+00:00")
    ids = [h.id for h in hits]
    assert ids and "invented-id" not in ids
    assert all("Garden" not in h.title for h in hits)  # only the chosen topic and lookups
    assert not any(h.text.startswith("Harbour: Thanks") for h in hits)  # known only after as_of
    assert {t.kind for t in mind.seen} >= {"regions", "perceive", "topic_gist", "zoom_areas", "zoom_topics", "skim_neurons", "read_neurons"}


def test_file_mind_defers_then_resumes(tmp_path: Path):
    mind = FileMind(tmp_path / "mind")
    task = Task("demo", "Say hi", {"x": 1}, {"reply": "..."})
    with pytest.raises(AwaitingMind) as waiting:
        mind.ask_many([task])
    assert waiting.value.pending == [task.id]
    queued = json.loads((mind.outbox / f"{task.id}.json").read_text())
    assert "Say hi" in queued["prompt"]
    (mind.answers / f"{task.id}.json").write_text('```json\n{"reply": "hi"}\n```')
    assert mind.ask_many([task]) == [{"reply": "hi"}]


def test_function_mind_caches_answers(tmp_path: Path):
    calls = []
    mind = FunctionMind(lambda prompt: calls.append(prompt) or 'Sure! {"ok": true}', cache=FileMind(tmp_path / "mind"))
    task = Task("demo", "Answer", {"q": 1}, {"ok": True})
    assert mind.ask_many([task]) == [{"ok": True}]
    assert mind.ask_many([task]) == [{"ok": True}]
    assert len(calls) == 1


def test_task_ids_are_content_hashes():
    a = Task("k", "i", {"x": 1})
    assert a.id == Task("k", "i", {"x": 1}).id != Task("k", "i", {"x": 2}).id


def test_parse_json_reply_rejects_non_json():
    with pytest.raises(ValueError):
        parse_json_reply("no json here")


def test_openai_compatible_mind_talks_to_any_endpoint(tmp_path: Path):
    import http.server
    import threading

    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["auth"] = self.headers.get("Authorization")
            reply = {"choices": [{"message": {"content": '{"ok": true}'}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from mneme.cortex.mind import mind_from_config
        import os
        os.environ["TEST_MIND_KEY"] = "secret"
        mind = mind_from_config({"provider": "openai-compatible", "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                                 "model": "local-model", "api_key_env": "TEST_MIND_KEY"})
        assert mind.ask_many([Task("demo", "Answer", {"q": 1}, {"ok": True})]) == [{"ok": True}]
        assert seen["body"]["model"] == "local-model" and seen["auth"] == "Bearer secret"
    finally:
        server.shutdown()


def test_command_mind_and_role_routing(tmp_path: Path):
    import sys
    from mneme.cortex.mind import CommandMind, MeteredMind, RoleMind

    echo = CommandMind(f"{sys.executable} -c \"import sys; sys.stdin.read(); print('{{\\\"who\\\": \\\"cmd\\\"}}')\"")
    other = FunctionMind(lambda prompt: '{"who": "fn"}')
    mind = MeteredMind(RoleMind(other, {"special": echo}))
    out = mind.ask_many([Task("plain", "a", {}), Task("special", "b", {}), Task("plain", "c", {})])
    assert [o["who"] for o in out] == ["fn", "cmd", "fn"]
    assert mind.calls == {"plain": 2, "special": 1}


def test_suspicious_content_never_reaches_gists(tmp_path: Path):
    class Suspicious(ScriptedMind):
        def perceive(self, payload):
            out = super().perceive(payload)
            for item in out["neurons"]:
                if "Garden" in next(n["title"] for n in payload["neurons"] if n["id"] == item["id"]):
                    item["trust"], item["trust_reason"] = "suspicious", "instructions aimed at an assistant"
            return out

    mind = Suspicious()
    brain = Brain(tmp_path / "c.sqlite", mind)
    brain.ingest_sources(_vault(tmp_path))
    brain.perceive()
    gist_inputs = json.dumps([t.payload for t in mind.seen if t.kind == "topic_gist"])
    assert "Plant beans" not in gist_inputs
    assert "instructions aimed at an assistant" in gist_inputs

    # Recall: even an exact-text hit shows only a caption and the warning until the mind opens it.
    mind.zoom_areas = lambda payload: {"areas": ["a1"], "lookups": ["Plant beans"]}
    before = len(mind.seen)
    brain.recall("What should I plant?", as_of="2026-06-01T00:00:00+00:00")
    skim = next(t for t in mind.seen[before:] if t.kind == "skim_neurons")
    garden = [c for c in skim.payload["candidates"] if c.get("trust")]
    assert garden and "Plant beans" not in json.dumps(skim.payload)
    read = next(t for t in mind.seen[before:] if t.kind == "read_neurons")
    assert "Plant beans" in json.dumps(read.payload)  # opened on purpose: read in full, still labelled


def test_incremental_perception_only_touches_what_changed(tmp_path: Path):
    from mneme.cortex.senses import read_sources

    root = _vault(tmp_path)
    mind = ScriptedMind()
    brain = Brain(tmp_path / "c.sqlite", mind)
    brain.ingest_sources(root)
    brain.perceive()
    first = len(mind.seen)

    # Nothing new: perceiving again asks the mind nothing.
    assert brain.ingest(read_sources(root), incremental=True)["added"] == 0
    brain.perceive()
    assert len(mind.seen) == first

    # A new memory plus an edited note: one new neuron, one new version, old version kept.
    (root / "vault" / "Projects" / "Boat.md").write_text("---\nupdated: 2026-06-20\n---\n# Boat\n\n- Mooring renewed until 2027\n", encoding="utf-8")
    (root / "vault" / "Projects" / "Kayak.md").write_text("---\nupdated: 2026-06-21\n---\n# Kayak\n\n- Bought a kayak\n", encoding="utf-8")
    stats = brain.ingest(read_sources(root), incremental=True)
    assert stats == {"neurons": 6, "added": 2, "new_versions": 1}
    brain.perceive()
    new = mind.seen[first:]
    assert [t.kind for t in new if t.kind == "regions"] == []  # the map is kept
    assert sum(len(t.payload["neurons"]) for t in new if t.kind == "perceive") == 2
    assert {t.payload["topic"]["title"] for t in new if t.kind == "topic_gist"} <= {"Boat", "Garden"}
    old = brain.recall("mooring", as_of="2026-06-01T00:00:00+00:00")
    assert all("2027" not in h.text for h in old)  # the past still answers as it was



def test_broad_recall_sees_every_chosen_topic_within_the_cap(tmp_path: Path):
    brain = Brain(tmp_path / "c.sqlite", ScriptedMind())
    brain.ingest_sources(_vault(tmp_path))
    brain.perceive()
    pool, _ = brain._candidate_pool(["a1.t1", "a1.t2"], [], "2026-12-31T00:00:00+00:00", 2)
    topics = {r["region"] for nid in pool for r in brain.conn.execute("SELECT region FROM membership WHERE neuron = ?", (nid,))}
    assert topics == {"a1.t1", "a1.t2"}
