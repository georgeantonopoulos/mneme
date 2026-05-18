from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from ..core import WIKILINK_RE, now_iso, title_from_text
from .base import SenseEvent


class HermesSessionSense:
    """
    Ingests Hermes Agent session transcripts (JSONL) as Mneme evidence.
    
    Each session file becomes a source document. User messages and assistant
    responses are extracted as text evidence for synapse activation.
    
    Config:
        sense_id: "hermes-sessions" (default)
        sessions_dir: Path to Hermes sessions directory
        limit: Max sessions to ingest per run
    """
    sense_type = "hermes_sessions"

    def __init__(
        self,
        *,
        sense_id: str = "hermes-sessions",
        sessions_dir: Path,
        limit: int | None = None,
    ) -> None:
        self.sense_id = sense_id
        self.sessions_dir = Path(sessions_dir).expanduser()
        self.limit = limit

    def collect(self, *, since: str | None = None, limit: int | None = None) -> Iterable[SenseEvent]:
        del since
        limit = limit or self.limit
        
        # Get session files sorted by modification time (newest first)
        session_files = sorted(
            self.sessions_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        for index, session_path in enumerate(session_files):
            if limit is not None and index >= limit:
                break
            
            try:
                # Read session transcript
                lines = session_path.read_text(encoding="utf-8", errors="replace").strip().split('\n')
                
                # Extract conversation text
                messages = []
                user_messages = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                        role = msg.get('role', '')
                        content = msg.get('content', '')
                        if content:
                            messages.append(f"{role}: {content}")
                            if role == 'user':
                                user_messages.append(content)
                    except json.JSONDecodeError:
                        continue
                
                if not messages:
                    continue
                
                # Build text evidence (focus on user messages for retrieval)
                full_text = '\n'.join(messages)
                user_text = '\n'.join(user_messages) if user_messages else full_text
                
                # Extract wikilinks if present
                links = sorted({target.strip() for target in WIKILINK_RE.findall(full_text) if target.strip()})
                
                # Generate stable ID
                rel = session_path.name
                digest = hashlib.sha1(f"{self.sense_id}:{rel}:{session_path.stat().st_mtime}".encode()).hexdigest()[:24]
                
                # Extract title from first user message or filename
                session_title = user_messages[0][:80] if user_messages else session_path.stem
                
                yield SenseEvent(
                    id=digest,
                    sense_id=self.sense_id,
                    sense_type=self.sense_type,
                    source_id=rel,
                    source_uri=str(session_path),
                    observed_at=now_iso(),
                    title=f"Session: {session_title}",
                    text=user_text,  # Index user messages for better retrieval
                    links=links,
                    event_type="conversation",
                    metadata={
                        "path": rel,
                        "session_id": session_path.stem,
                        "message_count": len(messages),
                        "user_message_count": len(user_messages),
                        "chars": len(user_text),
                    },
                )
                
            except Exception as e:
                # Skip corrupted session files
                continue
