from __future__ import annotations

from pathlib import Path

from .predictions import check_due_predictions


def world_tick(db_path: Path, *, before: str | None = None) -> dict:
    """Run deterministic world-model maintenance."""

    prediction_report = check_due_predictions(db_path, before=before)
    return {
        "ok": True,
        "predictions": prediction_report,
    }
