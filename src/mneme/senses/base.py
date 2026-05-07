from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class SenseEvent:
    id: str
    sense_id: str
    sense_type: str
    source_id: str
    source_uri: str | None
    observed_at: str
    title: str | None
    text: str
    entities: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    event_type: str = "document"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class Sense(Protocol):
    sense_id: str
    sense_type: str

    def collect(
        self,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> Iterable[SenseEvent]:
        ...
