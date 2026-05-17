from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field


DATE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b",
    re.I,
)
SOURCE_DATE_RE = re.compile(r"\b(20\d{2})[-_/](\d{2})[-_/](\d{2})\b")

HUB_NOTE_NAMES = {
    "architecture",
    "current memory",
    "debugging notes",
    "decisions",
    "moc",
    "open questions",
    "release notes",
    "roadmap",
    "run log",
}


@dataclass
class ScoreBreakdown:
    total: float
    factors: list[dict] = field(default_factory=list)
    penalties: list[dict] = field(default_factory=list)
    freshness: dict = field(default_factory=dict)
    source_quality: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    skip_reasons: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total"] = round(float(self.total), 2)
        return data


def _add_factor(total: float, factors: list[dict], label: str, value: float) -> float:
    if value:
        factors.append({"label": label, "value": round(value, 2)})
        total += value
    return total


def _add_penalty(total: float, penalties: list[dict], label: str, value: float) -> float:
    if value:
        penalties.append({"label": label, "value": round(value, 2)})
        total -= value
    return total


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _source_path_date(source_path: str | None) -> dt.date | None:
    if not source_path:
        return None
    match = SOURCE_DATE_RE.search(source_path)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def freshness_breakdown(text: str, source_path: str | None, observation_created_at: str | None, node_updated_at: str | None, *, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    explicit = DATE_RE.search(text or "")
    if explicit:
        return {
            "basis": "explicit_date",
            "value": explicit.group(1),
            "score": 0.8,
            "reason": "evidence contains a date-like phrase",
        }
    path_date = _source_path_date(source_path)
    if path_date is not None:
        age_days = max(0, (now.date() - path_date).days)
        score = 0.6 if age_days <= 30 else 0.2 if age_days <= 120 else -0.2
        return {
            "basis": "source_path_date",
            "value": path_date.isoformat(),
            "age_days": age_days,
            "score": score,
            "reason": "source path carries a date",
        }
    created = _parse_iso(observation_created_at) or _parse_iso(node_updated_at)
    if created is not None:
        age_days = max(0, (now - created).days)
        score = 0.3 if age_days <= 30 else 0.0 if age_days <= 120 else -0.15
        return {
            "basis": "observation_created_at",
            "value": created.isoformat(),
            "age_days": age_days,
            "score": score,
            "reason": "using observation or node timestamp",
        }
    return {
        "basis": "unknown",
        "value": None,
        "score": -0.15,
        "reason": "freshness is unknown; applying a small uncertainty penalty only",
    }


def source_quality_breakdown(source_path: str | None, note_name: str | None = None) -> dict:
    path = (source_path or "").lower()
    name = (note_name or "").strip().lower()
    score = 0.0
    reasons: list[str] = []
    if "/archive/runs/" in path:
        score -= 2.5
        reasons.append("archived run note")
    elif "/runs/" in path:
        score -= 1.0
        reasons.append("raw run note")
    if name in HUB_NOTE_NAMES:
        score -= 1.5
        reasons.append("project hub note")
    if "current memory.md" in path or "/topics/" in path or "/compactions/" in path:
        score += 0.6
        reasons.append("distilled memory surface")
    if not reasons:
        reasons.append("ordinary source")
    return {"score": score, "reasons": reasons}


def score_observation_candidate(
    *,
    kind: str,
    text: str,
    base_score: float,
    hints: list[str],
    note_type: str | None = None,
    note_name: str | None = None,
    source_path: str | None = None,
    recently_surfaced: bool = False,
    observation_created_at: str | None = None,
    node_updated_at: str | None = None,
    now: dt.datetime | None = None,
) -> ScoreBreakdown:
    low = (text or "").lower()
    factors: list[dict] = []
    penalties: list[dict] = []
    reasons: list[str] = []
    skip_reasons: list[str] = []
    total = float(base_score or 0)
    factors.append({"label": "base observation score", "value": round(total, 2)})

    if kind == "blocked":
        total = _add_factor(total, factors, "open loop / unresolved task", 5.0)
        reasons.append("open loop / unresolved task")
    if kind == "risk":
        total = _add_factor(total, factors, "risk or deadline language", 4.0)
        reasons.append("risk or deadline language")
    if any(word in low for word in ["due", "deadline", "expires", "overdue", "urgent"]):
        total = _add_factor(total, factors, "deadline pressure", 4.0)
        reasons.append("deadline pressure")
    if any(word in low for word in ["waiting", "awaiting", "follow up", "needs", "todo"]):
        total = _add_factor(total, factors, "follow-up needed", 3.0)
        reasons.append("follow-up needed")
    matched = [hint for hint in hints if hint.lower() in low]
    if matched:
        total = _add_factor(total, factors, "hint match", 2.0 * len(matched))
        reasons.append("matches hints: " + ", ".join(matched[:4]))
    if note_type in {"project", "finance", "event", "person"}:
        total = _add_factor(total, factors, f"important {note_type} note", 1.5)
        reasons.append(f"important {note_type} note")

    freshness = freshness_breakdown(text, source_path, observation_created_at, node_updated_at, now=now)
    if freshness["score"] >= 0:
        total = _add_factor(total, factors, "freshness", float(freshness["score"]))
    else:
        total = _add_penalty(total, penalties, "freshness uncertainty", abs(float(freshness["score"])))

    source_quality = source_quality_breakdown(source_path, note_name)
    if source_quality["score"] >= 0:
        total = _add_factor(total, factors, "source quality", float(source_quality["score"]))
    else:
        total = _add_penalty(total, penalties, "source quality", abs(float(source_quality["score"])))

    if recently_surfaced:
        total = _add_penalty(total, penalties, "recently surfaced", 3.0)
        reasons.append("recently surfaced penalty")

    if not reasons:
        reasons.append("high-signal observation")
    if total <= 0:
        skip_reasons.append("score below surfacing threshold")

    return ScoreBreakdown(
        total=total,
        factors=factors,
        penalties=penalties,
        freshness=freshness,
        source_quality=source_quality,
        reasons=reasons,
        skip_reasons=skip_reasons,
        provenance={"source_path": source_path, "note_type": note_type, "note_name": note_name},
    )
