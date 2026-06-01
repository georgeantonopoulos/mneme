"""Tests for the beautified Mneme thought card.

These cover the new rendering surface that was added when the SVG card
was redesigned (classification badge, evidence block, reasoning tint,
edge labels, theme support, larger card). They sit alongside the
existing legacy tests in tests/test_core.py which guard the
backward-compatible contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mneme.render import (
    NODE_COLORS,
    PATH_CLASS_BADGES,
    THEMES,
    _classify,
    _edge_label,
    _truncate_middle,
    render_card,
    render_svg,
    safe_basename,
    wrap_text,
)


SAMPLE_THOUGHT = {
    "title": "Open loop hiding in the graph",
    "insight": "Why this matters: Project A is connected to unresolved language along the chain.",
    "action": "Ask whether this is still pending, then choose the smallest next action.",
    "path": [
        {"name": "Project A", "type": "project", "via": None},
        {"name": "Task alpha (blocked)", "type": "task", "via": "blocks"},
        {"name": "Person Beth", "type": "person", "via": "mentions"},
        {"name": "Vendor Acme", "type": "finance", "via": "is_due"},
        {"name": "Project A review", "type": "note", "via": "references"},
    ],
    "why_now": "weighted random graph traversal surfaced this path; open-loop terms detected",
    "score": 7.42,
    "observations": ["blocked", "needs review", "deadline 2026-06-30"],
    "evidence": ["waiting for confirmation by 2026-05-01 (Project.md)"],
    "surface": {
        "source_path": "mneme://thoughts/abc123",
        "score": 7.42,
        "matched_terms": ["blocked", "deadline"],
        "truth_policy": "candidate",
    },
}


# --- helpers --------------------------------------------------------------


def _read_svg(svg_path: Path) -> str:
    assert svg_path.is_file(), f"expected svg at {svg_path}"
    return svg_path.read_text(encoding="utf-8")


# --- core invariants (regression contract) --------------------------------


def test_legacy_reasoning_and_next_strings_still_render(tmp_path: Path, monkeypatch):
    """The existing test_core.py contract: 'Reasoning' and 'Next' must
    be in the SVG, and the spurious 'Possible next move' string must
    not be (regression guard against a string I used during iteration)."""
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Safe",
        "insight": "Safe insight",
        "action": "Safe action",
        "path": [{"name": "Node", "type": "note"}],
    }
    out = render_card(thought, tmp_path, basename="legacy")
    svg = _read_svg(out)
    assert "Reasoning" in svg
    assert "Next" in svg
    assert "Possible next move" not in svg


# --- new capabilities -----------------------------------------------------


def test_evidence_block_renders_when_observations_present(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="evidence")
    svg = _read_svg(out)
    assert "Evidence" in svg
    # The deduped bullets must all be present.
    assert "blocked" in svg
    assert "needs review" in svg
    assert "deadline 2026-06-30" in svg
    assert "waiting for confirmation" in svg


def test_evidence_block_absent_when_no_observations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Reasoned graph walk",
        "insight": "Test insight",
        "action": "Test action",
        "path": [{"name": "Node", "type": "note"}],
    }
    out = render_card(thought, tmp_path, basename="no_evidence")
    svg = _read_svg(out)
    # No observations/evidence: the Evidence block is omitted entirely.
    assert "Evidence" not in svg


def test_classification_badge_appears_for_open_loop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="badge_open")
    svg = _read_svg(out)
    assert "Open loop" in svg
    # Badge uses the saturated amber color from the palette.
    assert PATH_CLASS_BADGES["open_loop"][1] in svg


def test_classification_badge_appears_for_deadline(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {**SAMPLE_THOUGHT, "title": "Deadline path worth checking"}
    out = render_card(thought, tmp_path, basename="badge_deadline")
    svg = _read_svg(out)
    assert "Deadline" in svg


def test_classification_badge_appears_for_surface(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Surface match",
        "insight": "x",
        "action": "x",
        "path": [{"name": "P", "type": "project"}],
        "surface": {"source_path": "mneme://thoughts/abc"},
    }
    out = render_card(thought, tmp_path, basename="badge_surface")
    svg = _read_svg(out)
    assert "Surface match" in svg


def test_classification_badge_falls_back_to_reasoned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Reasoned graph walk",
        "insight": "x",
        "action": "x",
        "path": [{"name": "P", "type": "project"}],
    }
    out = render_card(thought, tmp_path, basename="badge_reasoned")
    svg = _read_svg(out)
    assert "Reasoned walk" in svg


def test_score_chip_appears_in_header(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="score")
    svg = _read_svg(out)
    # The score is rendered as "7.42".
    assert ">7.42<" in svg


def test_score_chip_handles_int_and_float(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    for value, expected in [(5, ">5.00<"), (3.14159, ">3.14<"), ("9", ">9<")]:
        thought = {**SAMPLE_THOUGHT, "score": value}
        out = render_card(thought, tmp_path, basename=f"score_{value}")
        svg = _read_svg(out)
        assert expected in svg, f"score={value!r} should render as {expected!r}"


def test_edge_labels_rendered_on_path_edges(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="edges")
    svg = _read_svg(out)
    for label in ("blocks", "mentions", "is_due", "references"):
        # Edge labels are wrapped in chip rects; the text appears in <text> elements.
        assert f">{label.replace('_', ' ')}<" in svg, f"missing edge label: {label}"


def test_long_path_truncates_with_overflow_chip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    long_path = [
        {"name": f"Node {i}", "type": "note", "via": f"rel_{i}"}
        for i in range(1, 20)  # 19 nodes; max visible is 12
    ]
    thought = {
        "title": "Long path test",
        "insight": "x",
        "action": "x",
        "path": long_path,
    }
    out = render_card(thought, tmp_path, basename="long")
    svg = _read_svg(out)
    # The overflow chip should read "+7 more" (19 - 12 = 7).
    assert "+7 more" in svg


def test_path_with_single_node_does_not_crash(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Single node",
        "insight": "x",
        "action": "x",
        "path": [{"name": "Lone", "type": "project"}],
    }
    out = render_card(thought, tmp_path, basename="single")
    svg = _read_svg(out)
    assert ">1<" in svg  # step number badge


def test_path_with_zero_nodes_renders_friendly_message(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Empty path",
        "insight": "x",
        "action": "x",
        "path": [],
    }
    out = render_card(thought, tmp_path, basename="empty")
    svg = _read_svg(out)
    assert "No graph path" in svg


def test_footer_renders_why_now_and_source(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="footer")
    svg = _read_svg(out)
    assert "Why now:" in svg
    assert "src: mneme://thoughts/abc123" in svg
    assert "matched:" in svg


def test_footer_absent_when_no_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Reasoned graph walk",
        "insight": "x",
        "action": "x",
        "path": [{"name": "P", "type": "project"}],
    }
    out = render_card(thought, tmp_path, basename="no_footer")
    svg = _read_svg(out)
    # Without why_now or surface, the meta block is omitted; only the
    # generated timestamp should remain.
    assert "Why now:" not in svg
    assert "src:" not in svg


def test_light_theme_changes_palette(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out_dark = render_card(SAMPLE_THOUGHT, tmp_path, basename="dark", theme="dark")
    out_light = render_card(SAMPLE_THOUGHT, Path("/tmp/_mneme_test_light"), basename="light", theme="light")
    svg_dark = _read_svg(out_dark)
    svg_light = _read_svg(out_light)
    # Dark uses #070b14 as bg; light uses #f8fafc.
    assert "#070b14" in svg_dark
    assert "#f8fafc" in svg_light


def test_unknown_theme_falls_back_to_dark(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="unknown", theme="neon-pink")
    svg = _read_svg(out)
    # Should still render the dark bg color and not crash.
    assert "#070b14" in svg


def test_env_var_picks_theme(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEME_CARD_THEME", "light")
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    out = render_card(SAMPLE_THOUGHT, tmp_path, basename="env_light")
    svg = _read_svg(out)
    assert "#f8fafc" in svg


def test_html_in_user_text_is_escaped(tmp_path: Path, monkeypatch):
    """Untrusted text in title/insight/action/names must be escaped
    so it can't break the SVG markup."""
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "<script>alert(1)</script>",
        "insight": "evil & < > \" ' chars",
        "action": "<img onerror=x>",
        "path": [{"name": "<danger>", "type": "note", "via": "<rel>"}],
    }
    out = render_card(thought, tmp_path, basename="escape")
    svg = _read_svg(out)
    # The raw script tag must NOT appear unescaped.
    assert "<script>alert(1)</script>" not in svg
    # The escaped form must be present.
    assert "&lt;script&gt;" in svg
    assert "&lt;danger&gt;" in svg
    assert "&amp;" in svg


def test_thoughts_with_no_optional_fields_still_render(tmp_path: Path, monkeypatch):
    """Backward compatibility: a thought dict with only the legacy
    required keys (title, insight, action, path) must still produce a
    valid card with no exceptions."""
    monkeypatch.setattr("mneme.render.shutil.which", lambda _: None)
    thought = {
        "title": "Minimal",
        "insight": "x",
        "action": "y",
        "path": [{"name": "P", "type": "project"}],
    }
    out = render_card(thought, tmp_path, basename="minimal")
    svg = _read_svg(out)
    assert "Minimal" in svg
    assert "Reasoning" in svg
    assert "Next" in svg
    # Evidence is not present.
    assert "Evidence" not in svg
    # Footer is not present.
    assert "Why now:" not in svg


# --- unit tests for helpers -----------------------------------------------


@pytest.mark.parametrize(
    "text,width,max_lines,expected",
    [
        ("a b c d", 4, 3, ["a b", "c d"]),
        ("", 4, 3, []),
        ("abc", 4, 3, ["abc"]),
    ],
)
def test_wrap_text_basic(text, width, max_lines, expected):
    assert wrap_text(text, width, max_lines) == expected


def test_wrap_text_truncates_with_ellipsis():
    # Long text that exceeds max_lines must end with an ellipsis on the
    # last kept line.
    out = wrap_text("one two three four five six seven", width=6, max_lines=2)
    assert len(out) == 2
    assert out[-1].endswith("…")


@pytest.mark.parametrize(
    "thought,expected",
    [
        ({"title": "Open loop hiding in the graph"}, "open_loop"),
        ({"title": "Deadline path worth checking"}, "deadline"),
        ({"title": "Reasoned graph walk", "surface": {"matched_terms": ["x"]}}, "surface"),
        ({"title": "Reasoned graph walk"}, "reasoned"),
        # An empty surface dict should NOT count as a surface classification.
        ({"title": "Reasoned graph walk", "surface": {}}, "reasoned"),
    ],
)
def test_classify(thought, expected):
    assert _classify(thought) == expected


@pytest.mark.parametrize(
    "relation,expected",
    [
        ("blocks", "blocks"),
        ("is_due", "is due"),
        ("", None),
        (None, None),
    ],
)
def test_edge_label(relation, expected):
    assert _edge_label(relation) == expected


def test_truncate_middle_short_passes_through():
    assert _truncate_middle("hello", 10) == "hello"


def test_truncate_middle_long_string():
    out = _truncate_middle("a" * 200, 20)
    assert len(out) <= 20
    assert "…" in out


def test_safe_basename_sanitises_unsafe_input():
    assert safe_basename("../../escape") == "escape"
    assert safe_basename("a/b/c") == "a_b_c"
    assert safe_basename("")  # fallback to timestamp
