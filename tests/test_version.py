import re
from pathlib import Path

import mneme


def test_runtime_version_matches_project_metadata():
    project = Path(__file__).parents[1] / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)

    assert match is not None
    assert mneme.__version__ == match.group(1)


def test_major_release_is_marked_stable():
    project = Path(__file__).parents[1] / "pyproject.toml"
    text = project.read_text(encoding="utf-8")

    assert 'Development Status :: 5 - Production/Stable' in text
    assert "**Mneme v1.0** is stable" in (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
