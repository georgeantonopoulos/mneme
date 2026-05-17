import io
import sys
import unittest
from contextlib import redirect_stdout

from mneme.cli import main
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


if __name__ == "__main__":
    unittest.main()
