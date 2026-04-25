from pathlib import Path
from mneme.core import ingest_vault, walk_graph, generate_thought


def test_ingest_and_walk(tmp_path: Path):
    vault = tmp_path / "vault"; (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "example.md").write_text("# Example\n\n- [ ] Follow up by Apr 15\n- Waiting for confirmation\nRelated: [[Other]]\n", encoding="utf-8")
    db = tmp_path / "mneme.sqlite"
    stats = ingest_vault(vault, db)
    assert stats["notes_read"] == 1
    assert stats["nodes"] >= 3
    assert stats["observations"] >= 1
    path = walk_graph(db, hops=3)
    assert path
    thought = generate_thought(db, path)
    assert thought["title"] and thought["insight"]
