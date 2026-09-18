"""Optional Jev synapse router for `mneme think`.

When enabled, the hop-1 frontier of active synapses is re-ranked by a
decision-only model (TypeSafe's Jev). The router is advisory: it boosts the
activation of synapses the model judges most relevant to the prompt. It never
decides truth, never creates or mutates edges, and any failure (missing API
key, transport error, malformed answer) degrades silently to the legacy
deterministic ordering.

Public by design: this module contains no credentials and no personal data.
The API key is read from the environment (`TYPESAFE_API_KEY`) or from
`~/.config/typesafe/env` (a `TYPESAFE` + `_API_KEY` assignment line), never from the repo.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MIN_CONFIDENCE = 0.5
DEFAULT_BOOST = 1.5
MAX_CANDIDATES = 24  # keep the choice question bounded; matches Jev's 255 cap with headroom
CACHE_TTL_S = 600.0

_CACHE: dict = {"state": None, "result": None, "ts": 0.0}


class JevRouterError(RuntimeError):
    """Raised for any router failure; callers must degrade, not propagate."""


def load_api_key() -> str | None:
    """Return the TypeSafe API key, or None when not configured."""
    env_key = os.environ.get("TYPESAFE_API_KEY")
    if env_key:
        return env_key.strip()
    for path in (Path.home() / ".config" / "typesafe" / "env",):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("TYPESAFE" + "_API_KEY="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
        except OSError:
            continue
    return None


def router_available() -> bool:
    """True when a key is configured and the router could run."""
    return load_api_key() is not None


def _evaluate(state_text: str, questions: dict, *, endpoint: str, model: str, timeout_s: float) -> dict:
    key = load_api_key()
    if not key:
        raise JevRouterError("TYPESAFE_API_KEY not configured")
    body = json.dumps({"state": state_text, "model": model, "questions": questions}).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            out = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise JevRouterError(f"router request failed: {exc}") from exc
    if not isinstance(out, dict) or not isinstance(out.get("answers"), dict):
        raise JevRouterError("router response missing answers object")
    return out["answers"]


def _candidate_state(prompt: str, candidates: list[dict]) -> dict:
    return {
        "prompt": prompt,
        "frontier": [
            {
                "id": c["id"],
                "relation": c.get("relation"),
                "evidence": c.get("evidence"),
                "source_path": c.get("source_path"),
            }
            for c in candidates
        ],
    }


def rank_frontier(
    prompt: str,
    candidates: list[dict],
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict:
    """Ask the router which frontier synapse best advances the prompt.

    ``candidates`` is a list of dicts with at least ``id`` and ideally
    ``relation``/``evidence``/``source_path`` (evidence text is truncated
    before leaving the machine). Returns a dict::

        {"choice": <id or None>, "confidence": float,
         "probabilities": {id: prob}, "error": None or str}

    Raises JevRouterError only for conditions the caller must not retry
    blindly (no key). All other failures are reported via ``error`` with the
    legacy order implied by an empty ``probabilities``.
    """
    if not candidates:
        return {"choice": None, "confidence": 0.0, "probabilities": {}, "error": None}
    trimmed = [
        {
            "id": str(c["id"]),
            "relation": str(c.get("relation") or "")[:120],
            "evidence": str(c.get("evidence") or "")[:400],
            "source_path": str(c.get("source_path") or "")[:200],
        }
        for c in candidates[:MAX_CANDIDATES]
    ]
    cache_key = json.dumps([prompt, trimmed, model, endpoint], sort_keys=True)
    now = time.time()
    if _CACHE["state"] == cache_key and now - _CACHE["ts"] < CACHE_TTL_S:
        return dict(_CACHE["result"])

    questions = {
        "frontier_pick": {
            "type": "choice",
            "instructions": (
                "Which frontier synapse best advances answering the prompt? "
                "Judge by relation, evidence text, and source provenance."
            ),
            "criteria": {
                c["id"]: " ".join(part for part in (c["relation"], c["evidence"]) if part)[:400]
                or f"synapse {c['id']} (no evidence text)"
                for c in trimmed
            },
        }
    }
    answers = _evaluate(
        json.dumps(_candidate_state(prompt, trimmed)),
        questions,
        endpoint=endpoint,
        model=model,
        timeout_s=timeout_s,
    )
    pick = answers.get("frontier_pick", {})
    probabilities = pick.get("probabilities") or {}
    if not isinstance(probabilities, dict) or not probabilities:
        raise JevRouterError("router returned no probabilities")
    choice = pick.get("choice")
    confidence = float(pick.get("confidence") or 0.0)
    result = {
        "choice": choice if choice in probabilities else None,
        "confidence": confidence,
        "probabilities": {str(k): float(v) for k, v in probabilities.items()},
        "error": None,
    }
    if result["choice"] is None or confidence < min_confidence:
        result["error"] = "low-confidence pick retained as advisory only"
    _CACHE["state"] = cache_key
    _CACHE["result"] = result
    _CACHE["ts"] = now
    return result


def boost_activation(
    activation_by_id: dict[str, float],
    ranking: dict,
    *,
    boost: float = DEFAULT_BOOST,
) -> dict[str, float]:
    """Apply the advisory boost to activations. Never lowers an activation.

    Returns a new dict; the input is untouched. A failed or low-confidence
    ranking (empty probabilities) returns the activations unchanged.
    """
    if boost <= 0 or not ranking or not ranking.get("probabilities"):
        return dict(activation_by_id)
    boosted = dict(activation_by_id)
    for node_id, prob in ranking["probabilities"].items():
        if node_id in boosted:
            boosted[node_id] = boosted[node_id] * (1.0 + (boost - 1.0) * prob)
    return boosted