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
        "context": context,
        "world": world,
        "surface": surface,
        "warnings": warnings,
        "failures": failures,
    }
