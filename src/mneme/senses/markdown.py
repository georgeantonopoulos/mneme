from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from ..core import WIKILINK_RE, iter_markdown, note_type, now_iso, title_from_text
from .base import SenseEvent


class MarkdownSense:
    sense_type = "md"

    def __init__(
        self,
        *,
        sense_id: str = "vault",
        vault: Path,
        follow_symlinks: bool = False,
        exclude_parts: Iterable[str] = (".git", "node_modules"),
    ) -> None:
        self.sense_id = sense_id
        self.vault = Path(vault).expanduser()
        self.follow_symlinks = follow_symlinks
        self.exclude_parts = tuple(exclude_parts)

    def collect(self, *, since: str | None = None, limit: int | None = None) -> Iterable[SenseEvent]:
        del since
        for index, path in enumerate(iter_markdown(self.vault, self.exclude_parts, follow_symlinks=self.follow_symlinks)):
            if limit is not None and index >= limit:
                break
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue
            rel = path.relative_to(self.vault).as_posix()
            digest = hashlib.sha1(f"{self.sense_id}:{rel}:{hashlib.sha1(text.encode('utf-8')).hexdigest()}".encode()).hexdigest()[:24]
            yield SenseEvent(
                id=digest,
                sense_id=self.sense_id,
                sense_type=self.sense_type,
                source_id=rel,
                source_uri=str(path),
                observed_at=now_iso(),
                title=title_from_text(path, text),
                text=text,
                links=sorted({target.strip() for target in WIKILINK_RE.findall(text) if target.strip()}),
                event_type="document",
                metadata={"path": rel, "chars": len(text), "node_type": note_type(path)},
            )
