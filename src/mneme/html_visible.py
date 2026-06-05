from __future__ import annotations

import re
import logging
from typing import Any

try:
    from lxml import html
except ModuleNotFoundError:
    html = None  # type: ignore[assignment]
    _LXML_AVAILABLE = False
else:
    _LXML_AVAILABLE = True


logger = logging.getLogger(__name__)
_LXML_WARNING_LOGGED = False
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def extract_visible_text(html_text: str) -> str:
    """Return only the user-visible text from an HTML string."""
    visible, _hidden = extract_visible_and_hidden(html_text)
    return visible


def extract_visible_and_hidden(html_text: str) -> tuple[str, list[str]]:
    """Return visible text and stripped hidden element text from an HTML string."""
    if not html_text:
        return "", []
    if "<" not in html_text or ">" not in html_text:
        return _normalize_text(html_text), []
    if not _LXML_AVAILABLE:
        _warn_lxml_unavailable_once()
        return _fallback_text(html_text), []

    try:
        assert html is not None
        root = html.fragment_fromstring(html_text, create_parent="div")
    except Exception:
        return _fallback_text(html_text), []

    hidden_texts: list[str] = []

    for node in list(root.xpath(".//comment()")):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)

    for element in list(root.iterdescendants()):
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in {"script", "style"}:
            element.drop_tree()

    for element in list(root.iterdescendants()):
        if _is_hidden(element):
            hidden = _normalize_text(element.text_content())
            if hidden:
                hidden_texts.append(hidden)
            element.drop_tree()

    return _normalize_text(root.text_content()), hidden_texts


def _fallback_text(html_text: str) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", html_text)
    without_comments = _COMMENT_RE.sub(" ", without_scripts)
    return _normalize_text(_TAG_RE.sub(" ", without_comments))


def _warn_lxml_unavailable_once() -> None:
    global _LXML_WARNING_LOGGED
    if _LXML_WARNING_LOGGED:
        return
    logger.warning("lxml is not installed; falling back to regex-only HTML text extraction")
    _LXML_WARNING_LOGGED = True


def _is_hidden(element: Any) -> bool:
    if "hidden" in element.attrib:
        return True

    style = _parse_style(element.attrib.get("style", ""))
    if not style:
        return False

    if style.get("display") == "none":
        return True
    if style.get("visibility") == "hidden":
        return True
    if _is_zero(style.get("opacity")):
        return True
    if _is_zero_length(style.get("font-size")):
        return True
    if _is_transparent_color(style.get("color")):
        return True
    if _is_large_negative_indent(style.get("text-indent")):
        return True
    if style.get("overflow") == "hidden" and (
        _is_zero_length(style.get("height")) or _is_zero_length(style.get("width"))
    ):
        return True
    return False


def _parse_style(style: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        rules[_normalize_css(name)] = _normalize_css(value)
    return rules


def _normalize_css(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip().lower())


def _normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def _is_zero(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) == 0
    except ValueError:
        return False


def _is_zero_length(value: str | None) -> bool:
    if value is None:
        return False
    return bool(re.fullmatch(r"0(?:\.0+)?(?:px|pt|em|rem|%)?", value))


def _is_transparent_color(value: str | None) -> bool:
    if value is None:
        return False
    compact = re.sub(r"\s+", "", value)
    if compact == "transparent":
        return True
    match = re.fullmatch(r"rgba\([^,]+,[^,]+,[^,]+,([^)]+)\)", compact)
    return bool(match and _is_zero(match.group(1)))


def _is_large_negative_indent(value: str | None) -> bool:
    if value is None:
        return False
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)(px|pt|em|rem)?", value)
    return bool(match and float(match.group(1)) <= -100)
