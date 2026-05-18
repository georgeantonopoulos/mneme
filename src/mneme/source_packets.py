from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

INVISIBLE_TRANSLATION = {
    ord("\u200b"): None,
    ord("\u200c"): None,
    ord("\u200d"): None,
    ord("\ufeff"): None,
    ord("\u2060"): None,
    ord("\u180e"): None,
    ord("\u034f"): None,
    ord("\u061c"): None,
    ord("\u00ad"): None,
}
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PROMPT_MARKER_RE = re.compile(
    r"(?i)\b(ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|system\s*prompt|developer\s*message|"
    r"assistant\s*message|jailbreak|prompt\s*injection|do\s+not\s+follow)\b"
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_text(text: str, limit: int | None = None) -> str:
    clean = str(text or "").translate(INVISIBLE_TRANSLATION)
    clean = re.sub(r"(?i)&(?:zwnj|zwj|ZeroWidthSpace|#8203|#8204|#8205);", " ", clean)
    clean = CONTROL_RE.sub(" ", clean)
    clean = PROMPT_MARKER_RE.sub("[PROMPT-MARKER-REDACTED]", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit].rstrip() if limit is not None else clean


def validate_packet(packet: dict[str, Any]) -> None:
    required = {"id", "source", "kind", "created_at", "raw_sha256", "raw_path", "summary"}
    missing = sorted(required - set(packet))
    if missing:
        raise ValueError(f"source packet missing required fields: {', '.join(missing)}")
    if not str(packet["id"]).strip() or not str(packet["source"]).strip():
        raise ValueError("source packet id and source must be non-empty")
    if packet.get("summary") and any(ch in str(packet["summary"]) for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\u180e", "\u034f", "\u061c", "\u00ad")):
        raise ValueError("source packet summary contains invisible unicode")


def init_packet_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_packets(
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            observed_at TEXT,
            raw_path TEXT,
            raw_sha256 TEXT NOT NULL,
            text_sha256 TEXT,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_packets_status ON source_packets(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_packets_source ON source_packets(source)")


def store_packet(
    *,
    packet_dir: Path,
    source: str,
    kind: str,
    raw_bytes: bytes | None = None,
    raw_path: Path | None = None,
    text: str = "",
    observed_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    packet_id: str | None = None,
    status: str = "seen",
    excerpt_chars: int = 500,
) -> dict[str, Any]:
    if raw_bytes is None and raw_path is None:
        raw_bytes = text.encode("utf-8")
    packet_dir = Path(packet_dir).expanduser()
    raw_dir = packet_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    packet_id = packet_id or uuid.uuid4().hex
    if raw_bytes is None:
        raw_bytes = Path(raw_path).read_bytes()
    raw_sha = sha256_bytes(raw_bytes)
    suffix = Path(raw_path).suffix if raw_path else ".txt"
    stored_raw = raw_dir / f"{packet_id}{suffix or '.bin'}"
    if raw_path and Path(raw_path).resolve() != stored_raw.resolve():
        shutil.copyfile(raw_path, stored_raw)
    elif not stored_raw.exists():
        stored_raw.write_bytes(raw_bytes)
    sanitized = sanitize_text(text, excerpt_chars)
    text_sha = hashlib.sha256(sanitize_text(text).encode("utf-8")).hexdigest() if text else None
    packet = {
        "id": packet_id,
        "source": sanitize_text(source, 120),
        "kind": sanitize_text(kind, 80),
        "created_at": now_iso(),
        "observed_at": observed_at,
        "raw_path": str(stored_raw),
        "raw_sha256": raw_sha,
        "text_sha256": text_sha,
        "status": status,
        "summary": f"UNTRUSTED DATA excerpt: {sanitized}" if sanitized else "UNTRUSTED DATA: raw file stored; no prompt excerpt",
        "metadata": metadata or {},
    }
    validate_packet(packet)
    manifest = packet_dir / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as f:
        f.write(json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n")
    conn = sqlite3.connect(packet_dir / "source_packets.sqlite")
    try:
        init_packet_db(conn)
        conn.execute(
            """INSERT INTO source_packets
               (id,source,kind,created_at,observed_at,raw_path,raw_sha256,text_sha256,status,summary,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, summary=excluded.summary, metadata_json=excluded.metadata_json""",
            (
                packet["id"],
                packet["source"],
                packet["kind"],
                packet["created_at"],
                packet["observed_at"],
                packet["raw_path"],
                packet["raw_sha256"],
                packet["text_sha256"],
                packet["status"],
                packet["summary"],
                json.dumps(packet["metadata"], ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return packet
