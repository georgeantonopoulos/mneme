from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .base import SenseEvent


# Patterns that indicate a delivery failure worth surfacing.
# Each tuple: (regex, severity tag).
# - MEDIA_REJECTED: validator rejected a MEDIA: tag (path not in allowlist,
#   recency window missed, denied prefix matched, etc.). Caused the silent
#   "image didn't arrive" failure pattern of 2026-06-01.
# - DELIVERY_ERROR: any other ERROR/CRITICAL line from the gateway.
_GATEWAY_EVENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Skipping unsafe MEDIA directive path:\s*(\S+)"), "mneme:trigger/MEDIA_REJECTED"),
    (re.compile(r"\b(CRITICAL|ERROR)\b.*?(?=\n|$)"), "mneme:trigger/DELIVERY_ERROR"),
)


def _now_iso_safe() -> str:
    """UTC now in ISO 8601, with second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class GatewayLogSense:
    """
    Tails the Hermes gateway log for delivery failures and surfaces them
    as Mneme evidence so the next `surface` call can return them as a
    thought to act on.

    Without this sense, a rejected MEDIA: tag is invisible to Mneme — the
    gateway logs a WARNING, the send_message tool returns success, and the
    agent never knows the image was dropped. This sense catches the
    WARNING/ERROR lines and turns them into a SenseEvent the next time
    `mneme sense run` runs.

    Config:
        sense_id:    "gateway-log" (default)
        log_path:    Path to ~/.hermes/logs/gateway.log (default)
        state_path:  Path to a small JSON file tracking the last byte offset
                     read, so each `collect()` only yields new lines.
                     Default: ~/.local/share/mneme/state/gateway-log.cursor
        patterns:    Optional override of the event-regex list.

    Caveats:
    - The cursor file must be writable. If state_path's parent dir doesn't
      exist, this sense silently yields nothing rather than crashing the
      `sense run` call (a broken telemetry hook must never break ingestion).
    - Log lines are joined into one SenseEvent per run (not one per line)
      to keep the graph tractable. Severity and pattern hits are encoded
      in the event tags + title.
    """

    sense_type = "gateway_log"

    def __init__(
        self,
        *,
        sense_id: str = "gateway-log",
        log_path: str | os.PathLike[str] | None = None,
        state_path: str | os.PathLike[str] | None = None,
        patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        self.sense_id = sense_id
        self.log_path = Path(log_path or "~/.hermes/logs/gateway.log").expanduser()
        default_state = Path("~/.local/share/mneme/state").expanduser()
        self.state_path = Path(state_path or default_state / "gateway-log.cursor").expanduser()
        if patterns is not None:
            self._patterns: tuple[tuple[re.Pattern[str], str], ...] = tuple(
                (re.compile(p), t) for p, t in patterns
            )
        else:
            self._patterns = _GATEWAY_EVENT_PATTERNS

    def _read_cursor(self) -> int:
        try:
            return int(self.state_path.read_text("utf-8").strip() or "0")
        except (OSError, ValueError):
            return 0

    def _write_cursor(self, offset: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(str(offset), "utf-8")
        os.replace(tmp, self.state_path)

    def collect(self, *, since: str | None = None, limit: int | None = None) -> Iterable[SenseEvent]:
        del since, limit
        if not self.log_path.is_file():
            return
        try:
            offset = self._read_cursor()
        except OSError:
            return
        try:
            with self.log_path.open("rb") as fh:
                fh.seek(offset)
                raw = fh.read()
                new_offset = fh.tell()
        except OSError:
            return
        if not raw:
            return
        try:
            self._write_cursor(new_offset)
        except OSError:
            # Don't fail the sense run if we can't persist the cursor;
            # worst case we re-emit on the next run and Mneme dedupes.
            pass
        text = raw.decode("utf-8", errors="replace")
        hits: list[tuple[str, str, str]] = []  # (severity_tag, matched_text, line)
        for line in text.splitlines():
            for pattern, tag in self._patterns:
                m = pattern.search(line)
                if m:
                    hits.append((tag, m.group(0)[:200], line.strip()[:400]))
                    break
        if not hits:
            return
        # Compose one event summarizing all hits in this tail window.
        summary_lines = [f"[{tag}] {line}" for tag, _, line in hits[:25]]
        summary = "\n".join(summary_lines)
        digest = hashlib.sha1(
            f"{self.sense_id}:{self.log_path}:{new_offset}:{summary[:512]}".encode()
        ).hexdigest()[:24]
        # Tags: the matched-pattern tags + a generic "gateway_log" tag so
        # the source is filterable.
        all_tags = sorted({tag for tag, _, _ in hits} | {"mneme:sense/gateway_log"})
        yield SenseEvent(
            id=digest,
            sense_id=self.sense_id,
            sense_type=self.sense_type,
            source_id=f"gateway-log:{self.log_path.name}",
            source_uri=str(self.log_path),
            observed_at=_now_iso_safe(),
            title=f"Gateway log: {len(hits)} delivery-failure event(s) in last tail window",
            text=summary,
            tags=all_tags,
            event_type="log_tail",
            confidence=1.0,
            metadata={
                "log_path": str(self.log_path),
                "log_offset": new_offset,
                "match_count": len(hits),
                "matched_tags": sorted({tag for tag, _, _ in hits}),
            },
        )
