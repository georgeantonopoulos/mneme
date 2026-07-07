import json
import subprocess
import sys
from pathlib import Path

import pytest

from mneme import md_edit


def test_safe_markdown_editor_rejects_path_escape_and_non_markdown(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError):
        md_edit.safe_resolve(vault, "/etc/passwd")
    with pytest.raises(ValueError):
        md_edit.safe_resolve(vault, "../escape.md")
    with pytest.raises(ValueError):
        md_edit.safe_resolve(vault, "raw.txt")

    assert md_edit.safe_resolve(vault, "Projects/Foo").name == "Foo.md"


def test_note_upsert_replace_add_bullet_and_dry_run(tmp_path: Path):
    vault = tmp_path / "vault"

    upsert = md_edit.upsert_section(vault, "Projects/Foo.md", "Status", "Ready\n")
    assert upsert["ok"] is True
    assert upsert["operation"] == "upsert-section"
    assert upsert["path"] == "Projects/Foo.md"

    dry = md_edit.replace_exact(vault, "Projects/Foo.md", "Ready", "Done", dry_run=True)
    assert dry["changed"] is True
    assert "-Ready" in dry["diff"]
    assert "+Done" in dry["diff"]
    assert "Ready" in (vault / "Projects/Foo.md").read_text(encoding="utf-8")

    bullet = md_edit.add_bullet(vault, "Projects/Foo.md", "Tasks", "Review docs")
    deduped = md_edit.add_bullet(vault, "Projects/Foo.md", "Tasks", "Review docs")
    text = (vault / "Projects/Foo.md").read_text(encoding="utf-8")
    assert bullet["changed"] is True
    assert deduped["changed"] is False
    assert text.count("- Review docs") == 1
    assert list((vault / "Projects").glob("Foo.md.*.bak"))


def test_cli_note_subcommands_return_json(tmp_path: Path):
    vault = tmp_path / "vault"

    upsert = subprocess.run(
        [sys.executable, "-m", "mneme.cli", "note", "upsert-section", "Projects/Foo.md", "--heading", "Status", "--content", "Ready", "--vault", str(vault)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert json.loads(upsert.stdout)["operation"] == "upsert-section"

    read = subprocess.run(
        [sys.executable, "-m", "mneme.cli", "note", "read", "Projects/Foo.md", "--vault", str(vault)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "Ready" in json.loads(read.stdout)["content"]


def test_note_append_adds_newline_and_core_append_missing_still_fails(tmp_path: Path):
    vault = tmp_path / "vault"
    md_edit.write_note(vault, "Notes/Foo.md", "# Foo", mode="create")

    result = md_edit.write_note(vault, "Notes/Foo.md", "- item\n", mode="append")

    assert result["changed"] is True
    assert (vault / "Notes/Foo.md").read_text(encoding="utf-8") == "# Foo\n- item\n"

    from mneme.core import write_note
    with pytest.raises(FileNotFoundError):
        write_note(vault, "Notes/Missing.md", "nope", mode="append")


def test_backup_paths_are_relative_and_unique(tmp_path: Path):
    vault = tmp_path / "vault"
    md_edit.write_note(vault, "Notes/Foo.md", "one\n", mode="create")

    first = md_edit.write_note(vault, "Notes/Foo.md", "two\n", mode="overwrite")
    second = md_edit.write_note(vault, "Notes/Foo.md", "three\n", mode="overwrite")

    assert first["backup"] != second["backup"]
    assert first["backup"].startswith("Notes/Foo.md.")
    assert not Path(first["backup"]).is_absolute()
    assert (vault / first["backup"]).exists()


def test_cli_note_errors_are_json(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "mneme.cli", "note", "read", "../escape.md", "--vault", str(tmp_path / "vault")],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert proc.returncode != 0
    payload = json.loads(proc.stderr)
    assert payload["ok"] is False
    assert "path" in payload["error"].lower()


def test_move_note_updates_wikilinks_only_when_requested(tmp_path: Path):
    vault = tmp_path / "vault"
    md_edit.write_note(vault, "Projects/Old.md", "# Old\n", mode="create")
    md_edit.write_note(vault, "Index.md", "See [[Old]].\n", mode="create")

    moved = md_edit.move_note(vault, "Projects/Old.md", "Archive/New.md")

    assert moved["update_links"] is False
    assert moved["links_updated"] == 0
    assert not (vault / "Projects" / "Old.md").exists()
    assert (vault / "Archive" / "New.md").exists()
    assert (vault / "Index.md").read_text(encoding="utf-8") == "See [[Old]].\n"

    md_edit.move_note(vault, "Archive/New.md", "Projects/Old.md")
    updated = md_edit.move_note(vault, "Projects/Old.md", "Archive/New.md", update_links=True)

    assert updated["update_links"] is True
    assert updated["links_updated"] == 1
    assert (vault / "Index.md").read_text(encoding="utf-8") == "See [[New]].\n"


def test_search_content_treats_dash_prefixed_query_as_text(tmp_path: Path):
    vault = tmp_path / "vault"
    md_edit.write_note(vault, "Tasks.md", "- [ ] Pay invoice\n", mode="create")

    result = md_edit.search_content(vault, "- [ ]")

    assert result["matches"]
    assert result["matches"][0]["path"] == "Tasks.md"
    assert result["matches"][0]["line_text"] == "- [ ] Pay invoice"


def test_readme_and_installer_explain_note_editing():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    installer = (root / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert "mneme note upsert-section" in readme
    assert "mneme note add-bullet" in readme
    assert "path-safe" in readme
    assert "mneme note --help" in installer
