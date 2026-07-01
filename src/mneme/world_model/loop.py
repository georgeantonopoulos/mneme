from __future__ import annotations

from pathlib import Path

def world_tick(db_path: Path, *, before: str | None = None) -> dict:
    """Run graph tick plus deterministic world-model maintenance."""

    from mneme.core import tick

    graph_report = tick(db_path)
    from .predictions import check_due_predictions
    prediction_report = check_due_predictions(db_path, before=before)
    return {
        "ok": True,
        "graph": graph_report,
        "predictions": prediction_report,
    }
