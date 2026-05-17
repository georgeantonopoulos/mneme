import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mneme.cli import main
from mneme.core import init_db, upsert_edge, upsert_node
from mneme.harness import prepare_command, run_llm


class HarnessTests(unittest.TestCase):
    def test_echo_provider_round_trips_prompt(self):
        result = run_llm("hello harness", provider="echo")

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "hello harness")
        self.assertEqual(result.exit_code, 0)

    def test_custom_command_uses_stdin_by_default(self):
        result = run_llm(
            "hello stdin",
            provider="custom",
            command=[sys.executable, "-c", "import sys; print('IN:' + sys.stdin.read())"],
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "IN:hello stdin\n")

    def test_prompt_placeholder_uses_argument_instead_of_stdin(self):
        result = run_llm(
            "hello argv",
            provider="custom",
            command=[
                sys.executable,
                "-c",
                "import sys; print('ARG:' + sys.argv[1]); print('STDIN:' + sys.stdin.read())",
                "{prompt}",
            ],
        )

        self.assertTrue(result.ok)
        self.assertIn("ARG:hello argv", result.stdout)
        self.assertIn("STDIN:", result.stdout)

    def test_prepare_command_without_placeholder_sends_stdin(self):
        argv, stdin = prepare_command(["llm", "run"], "hello")

        self.assertEqual(argv, ["llm", "run"])
        self.assertEqual(stdin, "hello")

    def test_cli_harness_run_outputs_json(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            main(["harness", "run", "hello cli", "--provider", "echo"])

        output = stream.getvalue()
        self.assertIn('"ok": true', output)
        self.assertIn('"stdout": "hello cli"', output)

    def test_cli_retrieve_outputs_candidate_synapse_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mneme.sqlite"
            conn = sqlite3.connect(db)
            init_db(conn)
            src = upsert_node(conn, "person", "Example Child", "source")
            dst = upsert_node(conn, "activity", "Art Club", "source")
            upsert_edge(conn, src, dst, "requested_activity", "Sources/art.md", "Art Club request is pending.", 0.7, status="candidate")
            conn.commit()
            conn.close()

            stream = io.StringIO()
            with redirect_stdout(stream):
                main(["retrieve", "--db", str(db), "--prompt", "Art Club"])

        output = stream.getvalue()
        self.assertIn('"truth_policy": "candidate_only"', output)
        self.assertIn('"requested_activity"', output)

    def test_cli_debug_candidates_outputs_empty_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mneme.sqlite"
            conn = sqlite3.connect(db)
            init_db(conn)
            conn.commit()
            conn.close()

            stream = io.StringIO()
            with redirect_stdout(stream):
                main(["debug-candidates", "--db", str(db), "--include-skipped"])

        output = stream.getvalue()
        self.assertIn('"empty_reason"', output)

    def test_cli_brain_report_handles_empty_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mneme.sqlite"
            conn = sqlite3.connect(db)
            init_db(conn)
            conn.commit()
            conn.close()

            stream = io.StringIO()
            with redirect_stdout(stream):
                main(["brain", "report", "--db", str(db)])

        output = stream.getvalue()
        self.assertIn('"empty_reason"', output)


if __name__ == "__main__":
    unittest.main()
