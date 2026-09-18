from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contract import AGENT_RULES, CONTRACT_NAME, CONTRACT_VERSION, check_db_contract, validate_retrieval_pack
from ..core import DEFAULT_HINTS, retrieve_context, surface_thoughts
from ..world_model.predictions import due_predictions
from ..world_model.state import list_assertions, partition_assertions_by_validity
from ..world_model.conflicts import detect_state_conflicts
from ..path_classifier import classify_path


def agent_preflight(
    db_path: Path,
    prompt: str,
    *,
    budget: int = 2500,
    max_items: int = 8,
    surface_limit: int = 5,
    hints: list[str] | None = None,
    include_candidates: bool = True,
    as_of: str | None = None,
    router: str | None = None,
) -> dict[str, Any]:
    hints = hints or DEFAULT_HINTS
    route = classify_path(prompt, enabled=False)
    context = retrieve_context(
        db_path,
        prompt,
        budget=budget,
        max_items=max_items,
        hints=hints,
        include_candidates=include_candidates,
        as_of=as_of,
    )
    surface = surface_thoughts(
        db_path,
        prompt,
        limit=surface_limit,
        hints=hints,
        include_candidates=include_candidates,
        as_of=as_of,
    )
    stored_current = list_assertions(db_path, status="current", order_by="updated_at_desc", limit=200)
    effective_current, lapsed = partition_assertions_by_validity(stored_current, as_of=as_of)
    world = {
        "as_of": as_of,
        "current_assertions": effective_current[:20],
        "lapsed_assertions": lapsed[:20],
        "due_predictions": due_predictions(db_path)[:20],
        "contradictions": detect_state_conflicts(db_path)[:20],
    }
    router_report: dict | None = None
    if router == "jev":
        # Advisory prompt-relevance ranking of current world assertions.
        # Any failure degrades silently; assertion order is otherwise unchanged.
        router_report = {"mode": "jev", "applied": False, "error": None}
        try:
            from ..jev_router import rank_frontier

            def _assertion_candidates(assertions: list[dict]) -> list[dict]:
                candidates = []
                for index, assertion in enumerate(assertions):
                    candidates.append(
                        {
                            "id": str(assertion.get("id") or f"assertion-{index}"),
                            "relation": str(assertion.get("predicate") or ""),
                            "evidence": " ".join(
                                part
                                for part in (
                                    assertion.get("subject_name"),
                                    assertion.get("object_name"),
                                    assertion.get("object_value"),
                                )
                                if part
                            ),
                            "source_path": str(assertion.get("source_path") or ""),
                        }
                    )
                return candidates[:24]

            candidates = _assertion_candidates(world["current_assertions"])
            if candidates:
                ranking = rank_frontier(prompt, candidates)
                router_report.update(
                    {
                        "applied": bool(ranking.get("probabilities")),
                        "choice": ranking.get("choice"),
                        "confidence": ranking.get("confidence"),
                        "error": ranking.get("error"),
                    }
                )
                if ranking.get("probabilities"):
                    # Reorder current assertions by router probability, stable for ties.
                    probs = ranking["probabilities"]
                    ranked_ids = sorted(probs, key=lambda item: (-probs[item], item))
                    reordered_set = set(ranked_ids)
                    assertion_ids = [
                        str(a.get("id") or f"assertion-{i}")
                        for i, a in enumerate(world["current_assertions"])
                    ]
                    by_id = dict(zip(assertion_ids, world["current_assertions"]))
                    reordered = [by_id[node_id] for node_id in ranked_ids if node_id in by_id]
                    reordered_key_set = {node_id for node_id in ranked_ids if node_id in by_id}
                    remaining = [
                        assertion
                        for key, assertion in zip(assertion_ids, world["current_assertions"])
                        if key not in reordered_key_set
                    ]
                    world["current_assertions"] = reordered + remaining
        except Exception as exc:  # noqa: BLE001 - advisory layer must never break preflight
            router_report["error"] = f"router unavailable or failed: {exc}"
    db_report = check_db_contract(db_path)
    retrieval_report = validate_retrieval_pack(context)
    warnings = list(db_report.warnings) + list(retrieval_report.warnings)
    if world["contradictions"]:
        warnings.append(f"{len(world['contradictions'])} world-state contradiction(s) require review")
    failures = list(db_report.failures) + list(retrieval_report.failures)
    status = "pass" if not failures else "fail"
    return {
        "contract": {
            "name": CONTRACT_NAME,
            "version": CONTRACT_VERSION,
            "status": status,
            "db": db_report.to_dict(),
            "retrieval": retrieval_report.to_dict(),
        },
        "agent_rules": AGENT_RULES,
        "route": route,
        "router": router_report,
        "context": context,
        "world": world,
        "surface": surface,
        "warnings": warnings,
        "failures": failures,
    }
