import sqlite3
import unittest
from pathlib import Path

from mneme.core import init_db, upsert_edge, upsert_node
from mneme.physarum import PhysarumRunConfig, run_physarum, top_physarum_edges


class PhysarumTests(unittest.TestCase):
    def test_run_physarum_reinforces_edges_without_changing_status(self):
        tmp = Path(self._testMethodName + ".sqlite")
        try:
            conn = sqlite3.connect(tmp)
            init_db(conn)
            a = upsert_node(conn, "note", "Alpha", "alpha.md")
            b = upsert_node(conn, "note", "Beta", "beta.md")
            c = upsert_node(conn, "observation", "Useful bridge", "alpha.md", metadata={"kind": "blocked"})
            e1 = upsert_edge(conn, a, c, "has_blocked", "alpha.md", "Useful bridge", 0.9, status="candidate")
            e2 = upsert_edge(conn, c, b, "links_to", "beta.md", "[[Beta]]", 0.9, status="candidate")
            conn.commit()
            conn.close()

            result = run_physarum(
                tmp,
                PhysarumRunConfig(iterations=8, terminals=3, paths_per_iteration=4, seed=7),
            )

            self.assertEqual(result["edges"], 2)
            self.assertGreater(result["reinforced_edges"], 0)
            top = top_physarum_edges(tmp, result["run_id"], limit=2)
            self.assertTrue(top)

            conn = sqlite3.connect(tmp)
            statuses = dict(conn.execute("SELECT id,status FROM edges WHERE id IN (?,?)", (e1, e2)).fetchall())
            run_count = conn.execute("SELECT count(*) FROM physarum_runs").fetchone()[0]
            conn.close()

            self.assertEqual(statuses[e1], "candidate")
            self.assertEqual(statuses[e2], "candidate")
            self.assertEqual(run_count, 1)
        finally:
            if tmp.exists():
                tmp.unlink()


if __name__ == "__main__":
    unittest.main()
