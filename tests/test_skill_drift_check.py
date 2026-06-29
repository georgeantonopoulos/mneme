from pathlib import Path

from scripts.skill_drift_check import DEFAULT_PRIVATE_SECTION, check_drift, main


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_skill_drift_allows_exact_match(tmp_path):
    public = _write(tmp_path / "public.md", "# Mneme\n\nBody\n")
    private = _write(tmp_path / "private.md", "# Mneme\n\nBody\n")

    assert check_drift(public, private) == []


def test_skill_drift_allows_fenced_private_appendix(tmp_path):
    public = _write(tmp_path / "public.md", "# Mneme\n\nBody\n")
    private = _write(
        tmp_path / "private.md",
        f"# Mneme\n\nBody\n\n{DEFAULT_PRIVATE_SECTION}\n\nLocal-only runtime notes.\n",
    )

    assert check_drift(public, private) == []


def test_skill_drift_rejects_unfenced_private_changes(tmp_path):
    public = _write(tmp_path / "public.md", "# Mneme\n\nBody\n")
    private = _write(tmp_path / "private.md", "# Mneme\n\nBody changed privately\n")

    failures = check_drift(public, private)

    assert failures
    assert "without fenced section" in failures[0]


def test_skill_drift_rejects_public_section_edits_before_private_appendix(tmp_path):
    public = _write(tmp_path / "public.md", "# Mneme\n\nBody\n")
    private = _write(
        tmp_path / "private.md",
        f"# Mneme\n\nBody changed privately\n\n{DEFAULT_PRIVATE_SECTION}\n\nLocal-only runtime notes.\n",
    )

    failures = check_drift(public, private)

    assert failures
    assert "before the private section" in failures[0]


def test_skill_drift_cli_skips_when_private_path_omitted(capsys):
    assert main([]) == 0
    assert "skipped" in capsys.readouterr().out
