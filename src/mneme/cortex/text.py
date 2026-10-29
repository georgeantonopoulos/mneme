"""Words and time: tokenisation, light normalisation, and date understanding.

Indexing uses SQLite FTS5 with the Porter stemmer. This module adds what the
stemmer can't do (irregular verb forms, identifier codes, dates written many
ways) by emitting extra index terms, and turns time expressions in a query
into a date window.
"""
from __future__ import annotations

import datetime as dt
import re

STOPWORDS = frozenset("""
a about after again all am an and any are as at be been before being but by can could did do does doing for from
had has have having he her here hers him his how i if in into is it its just me more most my no nor not now of off
on once only or other our out over own same she should so some such than that the their them then there these they
this those through to too under until up very was we were what when where which while who whom why will with would
you your yours yet anything something thing things got get let lets
""".split())

# Irregular forms the Porter stemmer leaves apart. Generic English, not fixture-specific.
IRREGULAR = {
    "paid": "pay", "payment": "pay", "payments": "pay", "sent": "send", "went": "go", "gone": "go", "met": "meet",
    "bought": "buy", "told": "tell", "said": "say", "says": "say", "left": "leave", "made": "make", "took": "take",
    "taken": "take", "gave": "give", "given": "give", "came": "come", "saw": "see", "seen": "see", "knew": "know",
    "kept": "keep", "brought": "bring", "thought": "think", "found": "find", "wrote": "write", "written": "write",
    "began": "begin", "broke": "break", "broken": "break", "chose": "choose", "lent": "lend", "owed": "owe",
    "spent": "spend", "won": "win", "lost": "lose", "held": "hold", "flew": "fly", "ran": "run", "sold": "sell",
    "fell": "fall", "felt": "feel", "heard": "hear", "built": "build", "drove": "drive", "ate": "eat",
}

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WORD_RE = re.compile(r"[a-z0-9£]+(?:[-'][a-z0-9]+)*", re.I)
CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]*[-][A-Z0-9-]*\d[A-Z0-9-]*\b|\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,}\b")
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s+(20\d{2}))?\b", re.I)
MDY_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b", re.I)
RANGE_DM_RE = re.compile(r"\b(\d{1,2})\s*-\s*(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+(20\d{2}))?\b", re.I)


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


def query_terms(text: str) -> list[str]:
    seen: list[str] = []
    for word in words(text):
        if word in STOPWORDS or len(word) < 2:
            continue
        for term in (word, IRREGULAR.get(word)):
            if term and term not in seen:
                seen.append(term)
    return seen


def codes(text: str) -> list[str]:
    """Identifiers such as INV-2026-017, DG-58213, AE7QK2, FL-20931."""
    return sorted({c.upper() for c in CODE_RE.findall(text or "") if not ISO_DATE_RE.fullmatch(c)})


def code_term(code: str) -> str:
    return "c" + re.sub(r"[^a-z0-9]", "", code.lower())


def date_term(day: dt.date) -> str:
    return f"d{day:%Y%m%d}"


def _mk(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def mentioned_dates(text: str, *, default_year: int) -> list[dt.date]:
    """Calendar dates written in the text, in any of the common UK/US/ISO forms."""
    found: set[dt.date] = set()
    for y, m, d in ISO_DATE_RE.findall(text or ""):
        if (day := _mk(int(y), int(m), int(d))):
            found.add(day)
    for d1, d2, mon, year in RANGE_DM_RE.findall(text or ""):
        y = int(year) if year else default_year
        for d in (d1, d2):
            if (day := _mk(y, MONTHS[mon[:3].lower()], int(d))):
                found.add(day)
    for d, mon, year in DMY_RE.findall(text or ""):
        if (day := _mk(int(year) if year else default_year, MONTHS[mon[:3].lower()], int(d))):
            found.add(day)
    for mon, d, year in MDY_RE.findall(text or ""):
        if (day := _mk(int(year) if year else default_year, MONTHS[mon[:3].lower()], int(d))):
            found.add(day)
    return sorted(found)


def time_window(query: str, now: dt.datetime) -> tuple[dt.date, dt.date, str] | None:
    """A (start, end, kind) date window the query asks about, if any.

    kind is "day" for an explicit date, "future" or "past" for relative windows.
    """
    low = query.lower()
    today = now.date()
    explicit = mentioned_dates(query, default_year=today.year)
    if explicit:
        return explicit[0], explicit[-1], "day"
    match = re.search(r"\b(next|coming|last|past|previous)\s+(\d+|few|couple of)?\s*(day|week|month)s?\b", low)
    if match:
        count = {"few": 3, "couple of": 2, None: 1}.get(match.group(2), None)
        count = int(match.group(2)) if count is None else count
        span = {"day": 1, "week": 7, "month": 30}[match.group(3)] * count
        if match.group(1) in ("next", "coming"):
            return today, today + dt.timedelta(days=span), "future"
        return today - dt.timedelta(days=span), today, "past"
    if re.search(r"\b(this week|this weekend)\b", low):
        return today, today + dt.timedelta(days=6 - today.weekday()), "future"
    if "tomorrow" in low:
        return today + dt.timedelta(days=1), today + dt.timedelta(days=1), "future"
    if "yesterday" in low:
        return today - dt.timedelta(days=1), today - dt.timedelta(days=1), "past"
    if re.search(r"\b(today|tonight)\b", low):
        return today, today, "future"
    if re.search(r"\b(upcoming|coming up|due soon|soon)\b", low):
        return today, today + dt.timedelta(days=14), "future"
    return None


def wants_current(query: str) -> bool:
    """Questions about the present state of something prefer the newest evidence."""
    low = query.lower()
    if re.search(r"\b(originally|first|used to|was|were|old|previous|before|back then|in (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", low):
        return False
    return bool(re.search(r"\b(is|are|now|current|currently|latest|still|next|yet|do i have|am i)\b", low))


def wants_past(query: str) -> bool:
    return bool(re.search(r"\b(originally|first|used to|initially|previous|old|back then|before)\b", query.lower()))
