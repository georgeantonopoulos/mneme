from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import hashlib
from pathlib import Path
from typing import Any

from .schema import ensure_world_model_schema


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _sense_bridge_terms(*parts: str) -> set[str]:
    text = " ".join(p or "" for p in parts).lower()
    words = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text)
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "still", "needs", "need", "follow", "update", "task", "event", "email", "calendar", "notion", "open"}
    return {word for word in words if word not in stop}


def _bridge_match_score(candidate_terms: set[str], event_terms: set[str]) -> float:
    if not candidate_terms or not event_terms:
        return 0.0
    overlap = candidate_terms & event_terms
    return len(overlap) / max(3, min(len(candidate_terms), 12))


def _init_db(conn: sqlite3.Connection) -> None:
    from mneme.core import init_db

    init_db(conn)

PREDICTION_TYPES = {"confirmation_expected", "no_news_expected"}
TERMS_FIELDS = (
    "title_terms_any",
    "title_terms_all",
    "observation_terms_any",
    "observation_terms_all",
    "source_path_terms_any",
    "source_path_terms_all",
)


def _parse_iso(value: str, *, field: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _duration_from_now(value: str) -> str:
    match = re.match(r"^\s*(\d+)\s*([hdw])\s*$", value.lower())
    if not match:
        return value
    amount = int(match.group(1))
    unit = match.group(2)
    delta = {"h": dt.timedelta(hours=amount), "d": dt.timedelta(days=amount), "w": dt.timedelta(weeks=amount)}[unit]
    return (dt.datetime.now(dt.timezone.utc) + delta).isoformat(timespec="seconds")


def parse_before(value: str | None) -> str:
    if not value:
        return now_iso()
    parsed = _duration_from_now(value)
    _parse_iso(parsed, field="before")
    return parsed


def _terms(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"match_json.{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def validate_match_json(match_json: Any) -> dict:
    if not isinstance(match_json, dict):
        raise ValueError("match_json must be an object")
    criteria = dict(match_json)
    sense_type = criteria.get("sense_type")
    if not isinstance(sense_type, str) or not sense_type.strip():
        raise ValueError("match_json.sense_type is required")
    criteria["sense_type"] = sense_type.strip()
    source_id = criteria.get("source_id")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise ValueError("match_json.source_id must be a non-empty string or null")
    if isinstance(source_id, str):
        criteria["source_id"] = source_id.strip()
    term_count = 0
    for field in TERMS_FIELDS:
        terms = _terms(criteria.get(field), field=field)
        criteria[field] = terms
        term_count += len(terms)
    for legacy, current in (("title_terms", "title_terms_any"), ("text_terms", "observation_terms_any")):
        if legacy in criteria:
            terms = _terms(criteria.get(legacy), field=legacy)
            criteria[current] = criteria[current] + terms
            del criteria[legacy]
            term_count += len(terms)
    if not criteria.get("source_id") and term_count == 0:
        raise ValueError("match_json requires source_id or at least one terms field")
    for field in ("observed_after", "observed_before"):
        value = criteria.get(field)
        if value is not None:
            _parse_iso(value, field=f"match_json.{field}")
    min_score = criteria.get("min_score", 0.34)
    if not isinstance(min_score, (int, float)) or not 0 <= float(min_score) <= 1:
        raise ValueError("match_json.min_score must be a number between 0 and 1")
    criteria["min_score"] = float(min_score)
    return criteria



def prediction_content_id(payload: dict[str, Any], match_json: dict[str, Any]) -> str:
    """Deterministic id for idempotent prediction replay from durable payloads."""
    key = {
        "title": str(payload.get("title") or "").strip(),
        "prediction_type": payload.get("prediction_type", "confirmation_expected"),
        "subject_assertion_id": payload.get("subject_assertion_id"),
        "source_action_id": payload.get("source_action_id"),
        "match_json": match_json,
        "check_after": str(payload.get("check_after") or ""),
        "expires_at": str(payload.get("expires_at") or ""),
    }
    raw = json.dumps(key, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(("wp:" + raw).encode("utf-8")).hexdigest()[:24]

def _row_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["match_json"] = json.loads(result.get("match_json") or "{}")
    result["metadata_json"] = json.loads(result.get("metadata_json") or "{}")
    return result


def _open_conn(db_path: Path | str, *, skip_schema: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if not skip_schema:
        _init_db(conn)
        ensure_world_model_schema(conn)
    return conn


def _prediction_table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_predictions'"
        ).fetchone()
        is not None
    )


def add_prediction(conn_or_path: sqlite3.Connection | Path | str, payload: dict[str, Any]) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = _open_conn(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    ensure_world_model_schema(conn)
    try:
        if not isinstance(payload, dict):
            raise ValueError("prediction payload must be an object")
        prediction_type = payload.get("prediction_type", "confirmation_expected")
        if prediction_type not in PREDICTION_TYPES:
            raise ValueError("prediction_type must be confirmation_expected or no_news_expected")
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        check_after = payload.get("check_after")
        expires_at = payload.get("expires_at")
        if not check_after or not expires_at:
            raise ValueError("check_after and expires_at are required")
        check_dt = _parse_iso(check_after, field="check_after")
        expires_dt = _parse_iso(expires_at, field="expires_at")
        if expires_dt < check_dt:
            raise ValueError("expires_at must be greater than or equal to check_after")
        match_json = validate_match_json(payload.get("match_json"))
        confidence = float(payload.get("confidence", 0.5))
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        metadata = payload.get("metadata_json", payload.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must be an object")
        prediction_id = str(payload.get("id") or prediction_content_id(payload, match_json))
        ts = now_iso()
        conn.execute(
            """INSERT INTO world_predictions(
                 id,title,prediction_type,subject_assertion_id,source_action_id,match_json,
                 check_after,expires_at,confidence,status,metadata_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title,
                 prediction_type=excluded.prediction_type,
                 subject_assertion_id=excluded.subject_assertion_id,
                 source_action_id=excluded.source_action_id,
                 match_json=excluded.match_json,
                 check_after=excluded.check_after,
                 expires_at=excluded.expires_at,
                 confidence=excluded.confidence,
                 metadata_json=excluded.metadata_json,
                 updated_at=excluded.updated_at
            """,
            (
                prediction_id,
                title.strip(),
                prediction_type,
                payload.get("subject_assertion_id"),
                payload.get("source_action_id"),
                json.dumps(match_json, sort_keys=True, ensure_ascii=False),
                str(check_after),
                str(expires_at),
                confidence,
                "open",
                json.dumps(metadata, sort_keys=True, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        if close:
            conn.commit()
        row = conn.execute("SELECT * FROM world_predictions WHERE id=?", (prediction_id,)).fetchone()
        return _row_dict(row) or {}
    finally:
        if close:
            conn.close()


def due_predictions(conn_or_path: sqlite3.Connection | Path | str, *, before: str | None = None) -> list[dict]:
    if not isinstance(conn_or_path, sqlite3.Connection) and not Path(conn_or_path).exists():
        return []
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        if not _prediction_table_exists(conn):
            return []
        before_iso = parse_before(before)
        rows = conn.execute(
            """SELECT * FROM world_predictions
               WHERE status='open' AND check_after <= ?
               ORDER BY check_after,id""",
            (before_iso,),
        ).fetchall()
        return [_row_dict(row) or {} for row in rows]
    finally:
        if close:
            conn.close()


def _criterion_terms(criteria: dict) -> set[str]:
    pieces: list[str] = []
    for field in TERMS_FIELDS:
        pieces.extend(criteria.get(field) or [])
    return _sense_bridge_terms(" ".join(pieces))


def _field_satisfies(criteria: dict, field: str, event_terms: set[str], *, require_all: bool) -> bool:
    terms = _sense_bridge_terms(" ".join(criteria.get(field) or []))
    if not terms:
        return True
    return terms <= event_terms if require_all else bool(terms & event_terms)


def _candidate_events(conn: sqlite3.Connection, criteria: dict, prediction: sqlite3.Row) -> list[dict]:
    rows = conn.execute(
        """SELECT se.id,se.sense_id,se.sense_type,se.source_id,se.source_uri,se.event_type,se.title,
                  se.observed_at,COUNT(o.id) observation_count,
                  GROUP_CONCAT(o.text, ' ') observation_text,
                  GROUP_CONCAT(o.source_path, ' ') observation_source_paths
           FROM sense_events se
           LEFT JOIN observations o ON o.sense_event_id=se.id
           WHERE se.sense_type=?
           GROUP BY se.id
           ORDER BY se.observed_at,se.id""",
        (criteria["sense_type"],),
    ).fetchall()
    observed_after = criteria.get("observed_after") or prediction["check_after"]
    observed_before = criteria.get("observed_before") or prediction["expires_at"]
    after_dt = _parse_iso(observed_after, field="observed_after")
    before_dt = _parse_iso(observed_before, field="observed_before")
    candidates = []
    for row in rows:
        if criteria.get("source_id") and row["source_id"] != criteria["source_id"]:
            continue
        observed_at = row["observed_at"]
        if observed_at:
            observed_dt = _parse_iso(observed_at, field="sense_events.observed_at")
            if observed_dt < after_dt or observed_dt > before_dt:
                continue
        title_terms = _sense_bridge_terms(row["title"] or "")
        observation_terms = _sense_bridge_terms(row["observation_text"] or "")
        source_path_terms = _sense_bridge_terms(row["observation_source_paths"] or "", row["source_uri"] or "", row["source_id"] or "")
        event_terms = title_terms | observation_terms | source_path_terms
        if not _field_satisfies(criteria, "title_terms_any", title_terms, require_all=False):
            continue
        if not _field_satisfies(criteria, "title_terms_all", title_terms, require_all=True):
            continue
        if not _field_satisfies(criteria, "observation_terms_any", observation_terms, require_all=False):
            continue
        if not _field_satisfies(criteria, "observation_terms_all", observation_terms, require_all=True):
            continue
        if not _field_satisfies(criteria, "source_path_terms_any", source_path_terms, require_all=False):
            continue
        if not _field_satisfies(criteria, "source_path_terms_all", source_path_terms, require_all=True):
            continue
        criterion_terms = _criterion_terms(criteria)
        score = 1.0 if criteria.get("source_id") and not criterion_terms else _bridge_match_score(criterion_terms, event_terms)
        if score >= criteria.get("min_score", 0.34):
            candidates.append({
                "id": row["id"],
                "title": row["title"],
                "sense_type": row["sense_type"],
                "source_id": row["source_id"],
                "observed_at": row["observed_at"],
                "score": round(score, 3),
                "overlap": sorted(criterion_terms & event_terms)[:12],
                "observation_count": int(row["observation_count"] or 0),
            })
    return candidates


def _terminal_status(prediction_type: str, matched: bool, expired: bool, sense_seen: bool) -> str:
    if prediction_type == "no_news_expected":
        if matched:
            return "missed"
        if expired:
            return "confirmed" if sense_seen else "unverifiable"
        return "open"
    if matched:
        return "confirmed"
    if expired:
        return "missed" if sense_seen else "unverifiable"
    return "open"


def check_prediction(conn_or_path: sqlite3.Connection | Path | str, prediction_id: str, *, now: str | None = None, dry_run: bool = False) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = _open_conn(conn_or_path, skip_schema=dry_run) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    if not dry_run:
        _init_db(conn)
        ensure_world_model_schema(conn)
    try:
        row = conn.execute("SELECT * FROM world_predictions WHERE id=?", (prediction_id,)).fetchone()
        if row is None:
            raise ValueError(f"prediction not found: {prediction_id}")
        if dry_run:
            conn.execute("SAVEPOINT mneme_prediction_dry_run")
        checked_at = now or now_iso()
        try:
            criteria = validate_match_json(json.loads(row["match_json"] or "{}"))
        except Exception as exc:
            status = "unverifiable"
            outcome = f"unverifiable criteria: {exc}"
            conn.execute(
                "UPDATE world_predictions SET status=?, outcome_summary=?, checked_at=?, updated_at=? WHERE id=?",
                (status, outcome, checked_at, checked_at, prediction_id),
            )
            if dry_run:
                conn.execute("ROLLBACK TO mneme_prediction_dry_run")
                conn.execute("RELEASE mneme_prediction_dry_run")
            if close:
                conn.commit()
            return {"id": prediction_id, "status": status, "outcome_summary": outcome, "matches": [], "dry_run": dry_run}
        matches = _candidate_events(conn, criteria, row)
        best = matches[0] if matches else None
        sense_seen = conn.execute("SELECT 1 FROM sense_events WHERE sense_type=? LIMIT 1", (criteria["sense_type"],)).fetchone() is not None
        expired = _parse_iso(checked_at, field="now") >= _parse_iso(row["expires_at"], field="expires_at")
        status = _terminal_status(row["prediction_type"], bool(best), expired, sense_seen)
        if best:
            outcome_summary = f"{status} by {best['sense_type']}:{best['source_id']} score={best['score']}"
            outcome_id = best["id"]
        elif status == "open":
            outcome_summary = "no matching sense event yet"
            outcome_id = None
        elif status == "unverifiable":
            outcome_summary = f"no stored events for sense_type={criteria['sense_type']}"
            outcome_id = None
        else:
            outcome_summary = "expired without matching sense event"
            outcome_id = None
        confidence_coupled = False
        if row["status"] == "open" and status == "missed" and row["subject_assertion_id"]:
            assertion = conn.execute(
                "SELECT confidence,metadata_json FROM world_state_assertions WHERE id=?",
                (row["subject_assertion_id"],),
            ).fetchone()
            if assertion is not None:
                metadata = {}
                try:
                    metadata = json.loads(assertion["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                old_confidence = float(assertion["confidence"] or 0.0)
                new_confidence = max(0.1, round(old_confidence * 0.8, 6))
                new_status = "current" if new_confidence >= 0.9 else "contradicted"
                metadata.setdefault("prediction_misses", []).append({
                    "prediction_id": prediction_id,
                    "checked_at": checked_at,
                    "old_confidence": old_confidence,
                    "new_confidence": new_confidence,
                    "new_status": new_status,
                })
                conn.execute(
                    "UPDATE world_state_assertions SET confidence=?, status=?, metadata_json=?, updated_at=? WHERE id=?",
                    (new_confidence, new_status, json.dumps(metadata, sort_keys=True, ensure_ascii=False), checked_at, row["subject_assertion_id"]),
                )
                confidence_coupled = True
        conn.execute(
            """UPDATE world_predictions
               SET status=?, outcome_sense_event_id=COALESCE(?, outcome_sense_event_id),
                   outcome_summary=?, checked_at=?, updated_at=?
               WHERE id=?""",
            (status, outcome_id, outcome_summary, checked_at, checked_at, prediction_id),
        )
        if dry_run:
            conn.execute("ROLLBACK TO mneme_prediction_dry_run")
            conn.execute("RELEASE mneme_prediction_dry_run")
        if close:
            conn.commit()
        return {
            "id": prediction_id,
            "status": status,
            "checked_at": checked_at,
            "outcome_sense_event_id": outcome_id,
            "outcome_summary": outcome_summary,
            "matches": matches,
            "confidence_coupled": confidence_coupled,
            "dry_run": dry_run,
        }
    finally:
        if close:
            conn.close()


def check_due_predictions(conn_or_path: sqlite3.Connection | Path | str, *, before: str | None = None, now: str | None = None, dry_run: bool = False) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = _open_conn(conn_or_path, skip_schema=dry_run) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    if not dry_run:
        _init_db(conn)
        ensure_world_model_schema(conn)
    try:
        effective_now = now or (parse_before(before) if before else None)
        due = due_predictions(conn, before=before or now)
        checked = [check_prediction(conn, item["id"], now=effective_now, dry_run=dry_run) for item in due]
        if close:
            conn.rollback() if dry_run else conn.commit()
        return {"ok": True, "dry_run": dry_run, "due": len(due), "checked": len(checked), "results": checked}
    finally:
        if close:
            conn.close()
