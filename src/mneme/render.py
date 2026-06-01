from __future__ import annotations

import datetime as dt
import html
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path


# Color tokens per path-classification. The header badge picks one based on
# the thought title and why_now. Dark theme is default; the SVG inlines a
# <style> block so the whole card restyles from one place.
THEMES = {
    "dark": {
        "bg": "#070b14",
        "panel": "#101827",
        "panel_border": "#243044",
        "ink": "#f8fafc",
        "ink_muted": "#94a3b8",
        "ink_dim": "#475569",
        "rule": "#1e293b",
        "evidence_bg": "#0f2537",
        "evidence_border": "#1e3a5f",
        "evidence_ink": "#e5e7eb",
        "evidence_accent": "#38bdf8",
        "reasoning_bg": "#1a1530",
        "reasoning_border": "#3b2f6b",
        "reasoning_accent": "#a78bfa",
        "next_bg": "#1f1b10",
        "next_border": "#5b4315",
        "next_ink": "#fef3c7",
        "next_accent": "#fbbf24",
        "edge": "#64748b",
        "node_ink": "#07111f",
        "label_ink": "#e2e8f0",
        "type_ink": "#64748b",
        "chip_bg": "#1e293b",
        "chip_ink": "#cbd5e1",
    },
    "light": {
        "bg": "#f8fafc",
        "panel": "#ffffff",
        "panel_border": "#cbd5e1",
        "ink": "#0f172a",
        "ink_muted": "#475569",
        "ink_dim": "#64748b",
        "rule": "#e2e8f0",
        "evidence_bg": "#e0f2fe",
        "evidence_border": "#7dd3fc",
        "evidence_ink": "#0c4a6e",
        "evidence_accent": "#0369a1",
        "reasoning_bg": "#ede9fe",
        "reasoning_border": "#c4b5fd",
        "reasoning_accent": "#6d28d9",
        "next_bg": "#fef3c7",
        "next_border": "#fbbf24",
        "next_ink": "#78350f",
        "next_accent": "#b45309",
        "edge": "#64748b",
        "node_ink": "#0f172a",
        "label_ink": "#1e293b",
        "type_ink": "#475569",
        "chip_bg": "#e2e8f0",
        "chip_ink": "#334155",
    },
}

# Node type → fill color. Untyped nodes fall back to the muted ink color.
NODE_COLORS = {
    "project": "#60a5fa",
    "person": "#f472b6",
    "finance": "#34d399",
    "event": "#fbbf24",
    "observation": "#fb7185",
    "date": "#a78bfa",
    "wikilink": "#c084fc",
    "note": "#22d3ee",
    "task": "#fb923c",
    "open_loop": "#f87171",
    "deadline": "#ef4444",
}

PATH_CLASS_BADGES = {
    "open_loop": ("Open loop", "#fbbf24"),
    "deadline": ("Deadline", "#ef4444"),
    "reasoned": ("Reasoned walk", "#60a5fa"),
    "surface": ("Surface match", "#a78bfa"),
}

# Render up to MAX_PATH_NODES inline; longer paths get a "+N more" chip.
MAX_PATH_NODES = 12
MAX_EVIDENCE_LINES = 5
MAX_OBSERVATION_LINES = 5


def wrap_text(text: str, width: int, max_lines: int) -> list[str]:
    """Whitespace-normalize then hard-wrap; truncate with an ellipsis on
    the last line if we hit the limit."""
    if not text:
        return []
    words = " ".join(text.split())
    lines = textwrap.wrap(words, width=width) or [""]
    if len(lines) > max_lines:
        kept = lines[: max_lines - 1]
        tail = lines[max_lines - 1]
        kept.append(tail[: max(0, width - 1)].rstrip() + "…")
        return kept
    return lines


def _classify(thought: dict) -> str:
    """Pick a header badge from title and why_now. Unknown → 'reasoned'."""
    title = (thought.get("title") or "").lower()
    if "open loop" in title:
        return "open_loop"
    if "deadline" in title:
        return "deadline"
    surface = thought.get("surface")
    # Only classify as 'surface' when the surface block actually carries
    # at least one of the fields the surface badge represents.
    if isinstance(surface, dict) and any(surface.get(k) for k in ("source_id", "source_path", "matched_terms", "score", "prompt")):
        return "surface"
    return "reasoned"


def _node_color(node: dict, fallback: str) -> str:
    return NODE_COLORS.get(node.get("type", ""), fallback)


def _edge_label(relation: str | None) -> str | None:
    if not relation:
        return None
    cleaned = relation.replace("_", " ").strip()
    return cleaned if cleaned else None


def _truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    keep = max(0, limit - 1)
    head = keep * 2 // 3
    tail = keep - head
    return text[:head].rstrip() + "…" + text[-tail:].lstrip()


def _render_path(thought: dict, palette: dict[str, str], esc) -> list[str]:
    """Render the path zone: numbered nodes connected by labelled edges."""
    path = thought.get("path") or []
    if not path:
        return [
            f'<text x="120" y="280" fill="{palette["ink_muted"]}" '
            f'font-family="Inter,Arial,sans-serif" font-size="22">'
            f'No graph path was returned for this thought.</text>'
        ]

    visible = path[:MAX_PATH_NODES]
    overflow = len(path) - len(visible)
    width, height = 1200, 850
    y0 = 280
    n = len(visible)
    # Evenly distribute the nodes across the inner panel (x ∈ [120, 1080]).
    inner_left, inner_right = 120, 1080
    if n == 1:
        xs = [(inner_left + inner_right) // 2]
    else:
        step = (inner_right - inner_left) // (n - 1)
        xs = [inner_left + i * step for i in range(n)]

    parts: list[str] = []
    default_color = palette["ink_muted"]
    for i, node in enumerate(visible):
        x = xs[i]
        color = _node_color(node, default_color)
        # Edge from the previous node, with the relation label as a chip.
        if i > 0:
            prev_x = xs[i - 1]
            mid_x = (prev_x + x) // 2
            # Curved connector.
            parts.append(
                f'<path d="M {prev_x + 50} {y0} C {mid_x} {y0 - 28}, '
                f'{mid_x} {y0 - 28}, {x - 50} {y0}" '
                f'stroke="{palette["edge"]}" stroke-width="3" fill="none" '
                f'marker-end="url(#arrow)"/>'
            )
            relation = _edge_label(node.get("via"))
            if relation:
                chip_w = max(60, 12 * len(relation) + 16)
                chip_x = mid_x - chip_w // 2
                parts.append(
                    f'<rect x="{chip_x}" y="{y0 - 60}" width="{chip_w}" '
                    f'height="26" rx="13" fill="{palette["chip_bg"]}" '
                    f'stroke="{palette["evidence_border"]}"/>'
                )
                parts.append(
                    f'<text x="{mid_x}" y="{y0 - 42}" text-anchor="middle" '
                    f'fill="{palette["chip_ink"]}" font-family="Inter,Arial" '
                    f'font-size="14" font-weight="600">{esc(relation)}</text>'
                )
        # Node circle.
        parts.append(
            f'<circle cx="{x}" cy="{y0}" r="44" fill="{color}" '
            f'opacity="0.95" stroke="{palette["panel_border"]}" stroke-width="2"/>'
        )
        # Step number badge.
        parts.append(
            f'<text x="{x}" y="{y0 + 8}" text-anchor="middle" '
            f'fill="{palette["node_ink"]}" font-family="Inter,Arial" '
            f'font-size="22" font-weight="800">{i + 1}</text>'
        )
        # Name (up to 3 wrapped lines).
        name = node.get("name") or "?"
        for j, line in enumerate(wrap_text(name, 16, 3)):
            parts.append(
                f'<text x="{x}" y="{y0 + 80 + j * 22}" text-anchor="middle" '
                f'fill="{palette["label_ink"]}" font-family="Inter,Arial" '
                f'font-size="18">{esc(line)}</text>'
            )
        # Type chip.
        node_type = node.get("type") or "node"
        for j, line in enumerate(wrap_text(node_type, 16, 1)):
            parts.append(
                f'<text x="{x}" y="{y0 + 158 + j * 18}" text-anchor="middle" '
                f'fill="{palette["type_ink"]}" font-family="Inter,Arial" '
                f'font-size="14" font-style="italic">{esc(line)}</text>'
            )

    if overflow > 0:
        chip_x = xs[-1] + 60
        parts.append(
            f'<rect x="{chip_x}" y="{y0 - 18}" width="86" height="36" rx="18" '
            f'fill="{palette["chip_bg"]}" stroke="{palette["panel_border"]}"/>'
        )
        parts.append(
            f'<text x="{chip_x + 43}" y="{y0 + 6}" text-anchor="middle" '
            f'fill="{palette["chip_ink"]}" font-family="Inter,Arial" '
            f'font-size="16" font-weight="700">+{overflow} more</text>'
        )
    return parts


def _render_evidence(thought: dict, palette: dict[str, str], esc) -> list[str]:
    """Render the evidence/observations block between the path and the
    reasoning block. Returns an empty list if no evidence is available."""
    raw_items: list[str] = []
    # Evidence first (snippets/source-backed), then observations.
    for key in ("evidence", "observations"):
        for item in thought.get(key) or []:
            if item and isinstance(item, str):
                raw_items.append(item)
    if not raw_items:
        return []

    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in raw_items:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    lines = unique[:MAX_EVIDENCE_LINES]
    body = []
    body.append(
        f'<rect x="90" y="500" width="1020" height="120" rx="22" '
        f'fill="{palette["evidence_bg"]}" stroke="{palette["evidence_border"]}"/>'
    )
    body.append(
        f'<text x="120" y="540" fill="{palette["evidence_accent"]}" '
        f'font-family="Inter,Arial" font-size="22" font-weight="700">Evidence</text>'
    )
    for j, line in enumerate(wrap_text("• " + " • ".join(lines), 100, MAX_EVIDENCE_LINES)):
        body.append(
            f'<text x="120" y="{570 + j * 26}" fill="{palette["evidence_ink"]}" '
            f'font-family="Inter,Arial" font-size="20">{esc(line)}</text>'
        )
    if len(unique) > MAX_EVIDENCE_LINES:
        body.append(
            f'<text x="120" y="605" fill="{palette["ink_dim"]}" '
            f'font-family="Inter,Arial" font-size="16" font-style="italic">'
            f'+{len(unique) - MAX_EVIDENCE_LINES} more in JSON output</text>'
        )
    return body


def _render_reasoning(thought: dict, palette: dict[str, str], esc) -> list[str]:
    parts: list[str] = []
    # Give the Reasoning zone a distinct, gentle tint so it reads as the
    # third colored band alongside Evidence (blue) and Next (amber).
    parts.append(
        f'<rect x="90" y="640" width="1020" height="100" rx="22" '
        f'fill="{palette["reasoning_bg"]}" stroke="{palette["reasoning_border"]}"/>'
    )
    parts.append(
        f'<text x="120" y="678" fill="{palette["reasoning_accent"]}" '
        f'font-family="Inter,Arial" font-size="22" font-weight="700">Reasoning</text>'
    )
    for j, line in enumerate(wrap_text(thought.get("insight", ""), 95, 3)):
        parts.append(
            f'<text x="120" y="{708 + j * 28}" fill="{palette["ink"]}" '
            f'font-family="Inter,Arial" font-size="22">{esc(line)}</text>'
        )
    return parts


def _render_next(thought: dict, palette: dict[str, str], esc) -> list[str]:
    parts: list[str] = []
    parts.append(
        f'<rect x="90" y="760" width="1020" height="80" rx="22" '
        f'fill="{palette["next_bg"]}" stroke="{palette["next_border"]}"/>'
    )
    parts.append(
        f'<text x="120" y="804" fill="{palette["next_accent"]}" '
        f'font-family="Inter,Arial" font-size="22" font-weight="700">Next</text>'
    )
    for j, line in enumerate(wrap_text(thought.get("action", ""), 90, 1)):
        parts.append(
            f'<text x="210" y="804" fill="{palette["next_ink"]}" '
            f'font-family="Inter,Arial" font-size="22">{esc(line)}</text>'
        )
    return parts


def _render_footer(thought: dict, palette: dict[str, str], esc) -> list[str]:
    """Footer: why_now, source surface metadata. Sits in its own row
    below the Next zone (which ends at y=840) so the two never share a
    y coordinate or paint over each other."""
    parts: list[str] = []
    bits: list[str] = []
    why_now = thought.get("why_now")
    if why_now:
        bits.append(f"Why now: {_truncate_middle(why_now, 140)}")
    surface = thought.get("surface") or {}
    if surface.get("source_path"):
        bits.append(f"src: {_truncate_middle(str(surface['source_path']), 80)}")
    matched = surface.get("matched_terms") or []
    if matched:
        bits.append("matched: " + ", ".join(str(m) for m in matched[:5]))
    if bits:
        for j, line in enumerate(wrap_text("  ·  ".join(bits), 130, 2)):
            parts.append(
                f'<text x="90" y="{858 + j * 18}" fill="{palette["ink_dim"]}" '
                f'font-family="Inter,Arial" font-size="15">{esc(line)}</text>'
            )
    return parts


def _render_header(thought: dict, palette: dict[str, str], esc) -> list[str]:
    """Header zone: brand line, classification badge, score, title."""
    parts: list[str] = []
    parts.append(
        f'<text x="90" y="100" fill="{palette["ink_muted"]}" '
        f'font-family="Inter,Arial,sans-serif" font-size="22">'
        f'MNEME</text>'
    )
    classification = _classify(thought)
    label, color = PATH_CLASS_BADGES.get(classification, ("Thought", palette["ink_muted"]))
    # Render the badge as a saturated-fill pill with the label in the
    # panel's high-contrast ink color. Mixing saturated fill + saturated
    # stroke at 22% produced a chip whose label and outline visually merged.
    parts.append(
        f'<rect x="230" y="68" width="170" height="44" rx="22" '
        f'fill="{color}"/>'
    )
    parts.append(
        f'<text x="315" y="97" text-anchor="middle" fill="{palette["panel"]}" '
        f'font-family="Inter,Arial" font-size="19" font-weight="800" '
        f'letter-spacing="0.5">{esc(label)}</text>'
    )
    # Score chip on the right.
    score = thought.get("score")
    if score is not None:
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
        parts.append(
            f'<rect x="1040" y="74" width="80" height="34" rx="17" '
            f'fill="{palette["chip_bg"]}" stroke="{palette["panel_border"]}"/>'
        )
        parts.append(
            f'<text x="1080" y="97" text-anchor="middle" fill="{palette["chip_ink"]}" '
            f'font-family="Inter,Arial" font-size="18" font-weight="700">'
            f'{esc(score_str)}</text>'
        )
    # Title.
    title = thought.get("title") or "Untitled thought"
    for j, line in enumerate(wrap_text(title, 32, 2)):
        parts.append(
            f'<text x="90" y="{158 + j * 44}" fill="{palette["ink"]}" '
            f'font-family="Inter,Arial,sans-serif" font-size="42" '
            f'font-weight="700">{esc(line)}</text>'
        )
    return parts


def render_svg(thought: dict, svg_path: Path, theme: str = "dark") -> None:
    """Render a self-contained SVG card. Backward compatible: old callers
    passing only (thought, svg_path) get the default dark theme."""
    palette = THEMES.get(theme, THEMES["dark"])
    esc = html.escape
    width, height = 1200, 920

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<defs>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">'
        '<feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" '
        'flood-opacity="0.35"/></filter>',
        '<marker id="arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" '
        'orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#64748b"/></marker>',
        '</defs>',
        f'<rect width="100%" height="100%" fill="{palette["bg"]}"/>',
        f'<rect x="40" y="40" width="1120" height="840" rx="36" '
        f'fill="{palette["panel"]}" stroke="{palette["panel_border"]}" '
        f'filter="url(#shadow)"/>',
    ]
    parts.extend(_render_header(thought, palette, esc))
    parts.extend(_render_path(thought, palette, esc))
    parts.extend(_render_evidence(thought, palette, esc))
    parts.extend(_render_reasoning(thought, palette, esc))
    parts.extend(_render_next(thought, palette, esc))
    parts.extend(_render_footer(thought, palette, esc))

    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    parts.append(
        f'<text x="1110" y="900" text-anchor="end" fill="{palette["ink_dim"]}" '
        f'font-family="Inter,Arial" font-size="13">'
        f'Generated {esc(generated)} from a local Markdown-derived SQLite graph.</text>'
    )
    parts.append("</svg>")

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text("\n".join(parts), encoding="utf-8")


def safe_basename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned or dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def render_card(
    thought: dict,
    out_dir: Path,
    basename: str | None = None,
    theme: str | None = None,
) -> Path:
    """Render an SVG card and try to convert it to PNG via ImageMagick if
    available. ``theme`` defaults to the ``MNEME_CARD_THEME`` env var or
    ``dark``. Returns the path to the PNG when conversion succeeds,
    otherwise the SVG path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = safe_basename(basename) if basename else dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    chosen_theme = theme or os.environ.get("MNEME_CARD_THEME", "dark")
    if chosen_theme not in THEMES:
        chosen_theme = "dark"
    svg_path = out_dir / f"thought_{stamp}.svg"
    png_path = out_dir / f"thought_{stamp}.png"
    render_svg(thought, svg_path, theme=chosen_theme)
    convert = shutil.which("convert") or shutil.which("magick")
    if convert:
        try:
            subprocess.run(
                [convert, str(svg_path), str(png_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            return png_path
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return svg_path
    return svg_path
