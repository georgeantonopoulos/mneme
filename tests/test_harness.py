import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mneme.cli import main
from mneme.core import init_db, upsert_edge, upsert_node
from mneme.harness import prepare_command, run_llm


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


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

    def test_run_llm_merges_env_overrides_with_process_env(self):
        result = run_llm(
            "hello env",
            provider="custom",
            command=[
                sys.executable,
                "-c",
                "import os,sys; sys.stdin.read(); print(os.environ.get('PATH','')); print(os.environ.get('MNEME_TEST_ENV',''))",
            ],
            env={"MNEME_TEST_ENV": "present"},
        )

        self.assertTrue(result.ok)
        self.assertIn(os.environ.get("PATH", ""), result.stdout)
        self.assertIn("present", result.stdout)

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

    def test_cli_surface_and_remember_use_scoped_graph_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mneme.sqlite"
            payload = {
                "source_path": "mneme://test/cli-surface",
                "nodes": [{"ref": "task", "type": "task", "name": "CLI surface validation"}],
                "observations": [{"node": "task", "kind": "fact", "text": "CLI surface validation should appear.", "score": 5}],
            }

            stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(__import__("json").dumps(payload))
                stream = io.StringIO()
                with redirect_stdout(stream):
                    main(["remember", "add", "--db", str(db)])

                stream = io.StringIO()
                with redirect_stdout(stream):
                    main(["surface", "--db", str(db), "--prompt", "CLI surface validation"])

                output = stream.getvalue()
                self.assertIn('"thoughts"', output)
                self.assertIn('"source_path": "mneme://test/cli-surface"', output)

                stream = io.StringIO()
                with redirect_stdout(stream):
                    main(["remember", "remove", "--db", str(db), "--source-path", "mneme://test/cli-surface"])
                self.assertIn('"nodes": 1', stream.getvalue())
            finally:
                sys.stdin = stdin

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

    def test_hermes_brain_ready_fails_fast_for_missing_db(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "hermes_brain_ready.sh"
        result = subprocess.run(
            [str(script), "/path/to/missing.sqlite"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DB_PATH must be an existing readable SQLite file", result.stderr)

    def test_hermes_brain_ready_runs_surface_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mneme.sqlite"
            conn = sqlite3.connect(db)
            init_db(conn)
            note = upsert_node(conn, "note", "Hermes Surface Validation", "validation.md")
            conn.execute(
                "INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)",
                ("obs-hermes-surface", note, "fact", "Hermes surface validation should appear.", "validation.md", 5, "now"),
            )
            conn.commit()
            conn.close()

            script = Path(__file__).resolve().parents[1] / "scripts" / "hermes_brain_ready.sh"
            result = subprocess.run(
                [str(script), str(db), "Hermes surface validation"],
                env={
                    **__import__("os").environ,
                    "PYTHON": sys.executable,
                    "MNEME_BRAIN_DEPTH": "smoke",
                    "MNEME_LABEL_PROVIDER": "test-labeler",
                    "MNEME_LABEL_COMMAND": f"{sys.executable} -c \"import json,sys; sys.stdin.read(); print(json.dumps({{'labels':['hermes surface'],'summary':'script label','intent':'surface validation','ignore':False}}))\"",
                    "MNEME_SURFACE_LIMIT": "2",
                },
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"thoughts"', result.stdout)
        self.assertIn('"surface"', result.stdout)
        self.assertIn('"prompt": "Hermes surface validation"', result.stdout)

    def test_repo_contains_hermes_mneme_skill_bundle(self):
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "skills" / "mneme-agent-brain"
        skill = skill_dir / "SKILL.md"
        reference = skill_dir / "references" / "operator-flow.md"
        helper = skill_dir / "scripts" / "mneme_brain_smoke.sh"

        skill_text = skill.read_text(encoding="utf-8")
        reference_text = reference.read_text(encoding="utf-8")
        helper_text = helper.read_text(encoding="utf-8")
        meta = _frontmatter(skill_text)

        self.assertEqual(meta["name"], "mneme-agent-brain")
        self.assertIn("description", meta)
        self.assertIn("mneme retrieve", skill_text)
        self.assertIn("mneme surface", skill_text)
        self.assertIn("mneme remember add", skill_text)
        self.assertIn("scripts/hermes_brain_ready.sh", skill_text)
        self.assertIn("truth_policy", reference_text)
        self.assertIn("mneme://", reference_text)
        self.assertIn("hermes_brain_ready.sh", helper_text)
        self.assertTrue(helper.stat().st_mode & 0o111)
        self.assertEqual(skill.parent.parent, root / "skills")


if __name__ == "__main__":
    unittest.main()
