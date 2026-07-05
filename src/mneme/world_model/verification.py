from __future__ import annotations

"""Close the agentic loop: recorded action -> verification prediction.

When mneme records a side-effectful action ("emailed the school finance
office"), it should also record what it *expects reality to do back* ("a reply
or thread update on the school sense within 3 days"). ``record_action`` already
carries a ``prediction_id`` column and predictions already carry
``source_action_id`` — this module fills the gap between them so an action
automatically spawns the prediction that will later verify it.

Determinism
-----------
The prediction window is anchored on the action's ``created_at``, never on
wall-clock ``now()``. Combined with the deterministic ``prediction_content_id``,
replaying the same action is idempotent: re-recording it upserts the same
prediction rather than creating a drifting new one every tick.

Opt-in
------
Spawning only happens when the action payload contains a ``verify`` block with a
``sense_type``. Without it we cannot know *which* sense would confirm the action
and we refuse to guess (a wrong sense_type produces silent false "unverifiable"
outcomes). No ``verify`` block -> no prediction, and ``record_action`` behaves
exactly as before.
"""

import datetime as dt
from typing import Any

from .predictions import _sense_bridge_terms, add_prediction, now_iso


_DURATION_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


def _anchor(created_at: str | None) -> dt.datetime:
    raw = created_at or now_iso()
    try:
        parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        parsed = dt.datetime.now(dt.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _offset(anchor: dt.datetime, duration: str, *, default_days: int) -> str:
    text = str(duration or "").strip().lower()
    amount, unit = None, None
    if text and text[-1] in _DURATION_UNITS and text[:-1].isdigit():
        amount, unit = int(text[:-1]), text[-1]
    if amount is None:
        delta = dt.timedelta(days=default_days)
    else:
        delta = dt.timedelta(**{_DURATION_UNITS[unit]: amount})
    return (anchor + delta).isoformat(timespec="seconds")


def build_verification_payload(action: dict[str, Any]) -> dict[str, Any] | None:
    """Return a prediction payload verifying ``action``, or ``None`` to skip."""

    verify = action.get("verify") or (action.get("metadata_json") or {}).get("verify")
    if not isinstance(verify, dict):
        return None
    sense_type = str(verify.get("sense_type") or "").strip()
    if not sense_type:
        return None

    anchor = _anchor(action.get("created_at"))
    check_after = _offset(anchor, verify.get("check_after", ""), default_days=1)
    expires_at = _offset(anchor, verify.get("expires", ""), default_days=3)
    # Guard the schema invariant expires_at >= check_after even if a caller sets
    # a check window longer than the expiry window.
    if expires_at < check_after:
        expires_at = check_after

    match_json: dict[str, Any] = {"sense_type": sense_type}
    if verify.get("source_id"):
        match_json["source_id"] = str(verify["source_id"]).strip()
    terms = verify.get("terms")
    if isinstance(terms, list) and terms:
        match_json["observation_terms_any"] = [str(t).strip() for t in terms if str(t).strip()]
    elif not match_json.get("source_id"):
        derived = sorted(_sense_bridge_terms(str(action.get("title") or "")))[:6]
        if not derived:
            # No source_id and no usable terms -> the prediction could never
            # match anything specific. Refuse rather than create a noisy catch-all.
            return None
        match_json["observation_terms_any"] = derived

    return {
        "title": f"Verify: {action.get('title') or 'action'}",
        "prediction_type": "confirmation_expected",
        "source_action_id": action.get("id"),
        "match_json": match_json,
        "check_after": check_after,
        "expires_at": expires_at,
        "confidence": float(verify.get("confidence", 0.6)),
        "metadata_json": {
            "spawned_by_action": action.get("id"),
            "action_type": action.get("action_type"),
        },
    }


def spawn_verification_prediction(conn, action: dict[str, Any]) -> dict[str, Any] | None:
    """Create (idempotently) the prediction that verifies ``action``.

    Returns the prediction row, or ``None`` when the action opts out.
    """

    payload = build_verification_payload(action)
    if payload is None:
        return None
    return add_prediction(conn, payload)

