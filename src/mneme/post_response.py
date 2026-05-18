from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .core import write_research_resolution

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_SOURCE_TERMS = re.compile(
    r"\b(solicitor|conveyanc(?:er|ing)|sdlt|stamp duty|gmail|email|completion statement|land registry|contract|invoice|receipt|calendar|official|source)\b",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4}))\b"
)
_EXPLICIT_BLOCK_RE = re.compile(
    r"```mneme-resolution\s*(\{.*?\})\s*```|<!--\s*mneme-resolution\s*(\{.*?\})\s*-->",
    re.I | re.S,
)


def _iso_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    day = int(m.group(4))
    month = _MONTHS.get(m.group(5).lower())
    year = int(m.group(6))
    if not month:
        return None
    return dt.date(year, month, day).isoformat()


def _subject_from_user(user_message: str) -> str | None:
    text = re.sub(r"\s+", " ", user_message or "").strip(" ?.")
    patterns = [
        r"when did (?:i|we) purchase (.+)",
        r"when did (?:i|we) buy (.+)",
        r"what(?:'s| is) the purchase date (?:for|of) (.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            subject = m.group(1).strip(" ?.")
            return subject[:120] if subject else None
    return None


def _extract_explicit_payloads(assistant_response: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in _EXPLICIT_BLOCK_RE.finditer(assistant_response or ""):
        raw = match.group(1) or match.group(2)
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _extract_property_purchase_resolution(user_message: str, assistant_response: str) -> dict[str, Any] | None:
    subject = _subject_from_user(user_message)
    if not subject:
        return None
    response = (assistant_response or "").replace("\\n", "\n")
    if not _SOURCE_TERMS.search(response):
        return None

    purchase_date: str | None = None
    exchange_date: str | None = None
    for line in response.splitlines():
        low = line.lower()
        if any(term in low for term in ("completion / purchase date", "completion date", "purchase date", "completed/purchased", "completed on", "purchased on")):
            purchase_date = _iso_date(line) or purchase_date
        if "exchange" in low:
            exchange_date = _iso_date(line) or exchange_date
    if not purchase_date:
        return None

    evidence_lines = [ln.strip(" -*") for ln in response.splitlines() if _SOURCE_TERMS.search(ln)]
    evidence = " ".join(evidence_lines)[:1200] or "Assistant response cited source-backed evidence."
    claims: list[dict[str, Any]] = [
        {
            "subject": subject,
            "predicate": "completed_purchase_on",
            "object": purchase_date,
            "status": "active",
            "certainty": "confirmed",
            "confidence": 0.93,
            "strength": 0.91,
            "evidence": evidence,
            "source_type": "post_response_source_backed_fact",
        }
    ]
    if exchange_date:
        claims.append(
            {
                "subject": subject,
                "predicate": "exchanged_contracts_on",
                "object": exchange_date,
                "status": "active",
                "certainty": "confirmed",
                "confidence": 0.91,
                "strength": 0.90,
                "evidence": evidence,
                "source_type": "post_response_source_backed_fact",
            }
        )
    return {
        "slug": f"{subject}-purchase-date",
        "title": f"{subject} purchase date confirmed",
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "sources_checked": ["post_response_source_citations"],
        "summary": f"Post-response hook detected a source-backed purchase/completion date for {subject}.",
        "claims": claims,
        "metadata": {"detected_by": "mneme.post_response", "kind": "property_purchase_date"},
    }


def detect_resolution_payloads(user_message: str, assistant_response: str) -> list[dict[str, Any]]:
    """Return conservative research-resolution payloads implied by a final answer.

    This is intentionally narrow. It is a post-response safety net, not an LLM: it
    only writes durable graph edges for explicit source-backed answers or for a
    hidden/fenced JSON payload emitted by an agent/tool.
    """

    payloads = _extract_explicit_payloads(assistant_response)
    inferred = _extract_property_purchase_resolution(user_message, assistant_response)
    if inferred:
        payloads.append(inferred)
    return payloads


def process_post_response(
    user_message: str,
    assistant_response: str,
    *,
    vault: Path,
    db: Path,
    active_threshold: float = 0.9,
    dry_run: bool = False,
) -> dict[str, Any]:
    payloads = detect_resolution_payloads(user_message, assistant_response)
    writes = []
    for payload in payloads:
        if dry_run:
            writes.append({"dry_run": True, "title": payload.get("title"), "claims": len(payload.get("claims", []))})
        else:
            writes.append(write_research_resolution(vault, db, payload, active_threshold=active_threshold))
    return {"detected": len(payloads), "writes": writes, "dry_run": dry_run}
