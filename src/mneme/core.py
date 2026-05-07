from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import random
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

THOUGHT_STATUSES = {"open", "acted", "resolved", "learned", "dismissed"}
LIFECYCLE_BY_KIND = {
    "blocked": ("mneme:thought/open_loop", 5.0, "open loop tag"),
    "risk": ("mneme:thought/time_sensitive", 4.0, "time-sensitive tag"),
    "done": ("mneme:thought/consolidate", 1.0, "consolidation tag"),
    "fact": ("mneme:thought/inspect", 0.0, "inspection tag"),
}
MISSION_PREFIX_BY_KIND = {
    "blocked": "Finish this unfinished loop",
    "risk": "Check and reduce this time-sensitive risk",
    "done": "Consolidate this completed item",
    "fact": "Inspect this possible connection",
}
FIRST_MOVE_BY_KIND = {
    "blocked": "Read the newest linked evidence, then choose: draft, schedule, write back, ask, or dismiss.",
    "risk": "Verify freshness against the source, then choose: act, remind, escalate, or dismiss.",
    "done": "Write back the durable lesson or archive the loop so it stops resurfacing.",
    "fact": "Decide whether this connection changes a next action; if not, leave it alone.",
}
THOUGHT_DONE_WHEN = "A human-visible next action, note update, scheduled reminder, or explicit dismissal exists."
ALLOWED_THOUGHT_ACTIONS = ["draft_reply", "write_note", "schedule_reminder", "ask_user", "mark_irrelevant"]

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])]\s+(.+)$", re.M)
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.M)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b", re.I)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
RESEARCH_RESOLUTION_RE = re.compile(r"<!--\s*mneme-research-resolution-b64:\s*([A-Za-z0-9_-]+)\s*-->", re.S)
STATUS_WORDS = {
    "blocked": ["blocked", "stuck", "waiting", "awaiting", "needs", "need to", "todo", "to do", "follow up", "unresolved"],
    "done": ["paid", "resolved", "closed", "completed", "done", "accepted", "confirmed"],
    "risk": ["deadline", "expires", "due", "appeal", "fine", "penalty", "urgent", "overdue", "risk"],
}
DEFAULT_HINTS = ["deadline", "project", "invoice", "lease", "tax", "school", "move", "certification", "payment"]
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mneme" / "config.json"
DEFAULT_RELATIONSHIP_TYPES = [
    {
        "id": "links_to",
        "label": "links to",
        "inverse_id": "linked_from",
        "category": "reference",
        "domain_type": "note",
        "range_type": "any",
        "description": "Explicit Markdown wikilink/reference; useful for navigation but not necessarily a semantic real-world relationship.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "linked_from",
        "label": "linked from",
        "inverse_id": "links_to",
        "category": "reference",
        "domain_type": "any",
        "range_type": "note",
        "description": "Inverse of links_to for traversal.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_heading",
        "label": "has heading",
        "inverse_id": "heading_of",
        "category": "structure",
        "domain_type": "note",
        "range_type": "heading",
        "description": "Markdown heading contained in a source note.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "mentions_email",
        "label": "mentions email",
        "inverse_id": "email_mentioned_by",
        "category": "extraction",
        "domain_type": "note",
        "range_type": "email",
        "description": "Email address extracted from source text.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "mentions_date",
        "label": "mentions date",
        "inverse_id": "date_mentioned_by",
        "category": "extraction",
        "domain_type": "observation",
        "range_type": "date",
        "description": "Date-like phrase extracted from an observation.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_fact",
        "label": "has fact",
        "inverse_id": "fact_of",
        "category": "observation",
        "domain_type": "note",
        "range_type": "observation",
        "description": "Scored factual observation extracted from a task or bullet.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_blocked",
        "label": "has blocked item",
        "inverse_id": "blocked_item_of",
        "category": "observation",
        "domain_type": "note",
        "range_type": "observation",
        "description": "Open loop or blocked task extracted from a task or bullet.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_risk",
        "label": "has risk",
        "inverse_id": "risk_of",
        "category": "observation",
        "domain_type": "note",
        "range_type": "observation",
        "description": "Risk/deadline-like observation extracted from a task or bullet.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_done",
        "label": "has done item",
        "inverse_id": "done_item_of",
        "category": "observation",
        "domain_type": "note",
        "range_type": "observation",
        "description": "Completed/done observation extracted from a task or bullet.",
        "requires_validation": False,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "belongs_to",
        "label": "belongs to",
        "inverse_id": "has_part",
        "category": "semantic",
        "domain_type": "any",
        "range_type": "project",
        "description": "Semantic membership/context relationship, e.g. an item belongs to a project or higher-level context. Requires evidence validation.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "has_part",
        "label": "has part",
        "inverse_id": "belongs_to",
        "category": "semantic",
        "domain_type": "project",
        "range_type": "any",
        "description": "Inverse of belongs_to.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "located_in",
        "label": "located in",
        "inverse_id": "contains_location",
        "category": "semantic",
        "domain_type": "place",
        "range_type": "place",
        "description": "Semantic location relationship. Requires evidence validation.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": True,
    },
    {
        "id": "contains_location",
        "label": "contains location",
        "inverse_id": "located_in",
        "category": "semantic",
        "domain_type": "place",
        "range_type": "place",
        "description": "Inverse of located_in.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": True,
    },
    {
        "id": "father_of",
        "label": "father of",
        "inverse_id": "child_of",
        "category": "semantic",
        "domain_type": "person",
        "range_type": "person",
        "description": "Semantic family relationship. Requires explicit evidence or user confirmation.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "part_of",
        "label": "part of",
        "inverse_id": "has_part",
        "category": "semantic",
        "domain_type": "any",
        "range_type": "any",
        "description": "Semantic part-whole relationship. Requires evidence validation.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": True,
    },
    {
        "id": "attends_activity",
        "label": "attends activity",
        "inverse_id": "activity_attended_by",
        "category": "semantic",
        "domain_type": "person",
        "range_type": "activity",
        "description": "Confirmed participation in an activity. Should only be active when evidence is close to certain.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    },
    {
        "id": "requested_activity",
        "label": "requested activity",
        "inverse_id": "activity_requested_by",
        "category": "semantic_pending",
        "domain_type": "person",
        "range_type": "activity",
        "description": "Requested or pending participation in an activity; not resolved attendance.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    },
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def create_config(config_path: Path | None = None, vault: Path | None = None, db: Path | None = None, out: Path | None = None, hints: list[str] | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vault": str((vault or Path.cwd()).expanduser()),
        "db": str((db or (Path.home() / ".local" / "share" / "mneme" / "mneme.sqlite")).expanduser()),
        "out": str((out or (Path.home() / ".local" / "share" / "mneme" / "out")).expanduser()),
        "hints": hints or DEFAULT_HINTS,
        "follow_symlinks": False,
        "senses": [
            {
                "id": "vault",
                "type": "md",
                "enabled": True,
                "config": {"path": str((vault or Path.cwd()).expanduser()), "follow_symlinks": False},
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"config": str(path), **payload}


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def configured_senses(config: dict) -> list[dict]:
    senses = config.get("senses")
    if isinstance(senses, list) and senses:
        return senses
    if config.get("vault"):
        return [
            {
                "id": "vault",
                "type": "md",
                "enabled": True,
                "config": {
                    "path": config["vault"],
                    "follow_symlinks": bool(config.get("follow_symlinks", False)),
                },
            }
        ]
    return []


def doctor(config_path: Path | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    checks: dict[str, dict] = {}
    if not path.exists():
        return {
            "ok": False,
            "config": str(path),
            "checks": {"config": {"ok": False, "message": "config file does not exist; run `mneme init`"}},
            "next": "Run `mneme init --vault /path/to/vault`.",
        }
    checks["config"] = {"ok": True, "message": "config file found"}
    try:
        cfg = load_config(path)
    except json.JSONDecodeError as exc:
        return {"ok": False, "config": str(path), "checks": {"config": {"ok": False, "message": f"invalid JSON: {exc}"}}, "next": "Fix or recreate the config with `mneme init --force`."}

    vault = Path(cfg.get("vault", "")).expanduser()
    db = Path(cfg.get("db", "")).expanduser()
    out = Path(cfg.get("out", "")).expanduser()
    if not vault.exists():
        checks["vault"] = {"ok": False, "path": str(vault), "message": "vault does not exist"}
        note_count = 0
    elif not vault.is_dir():
        checks["vault"] = {"ok": False, "path": str(vault), "message": "vault is not a directory"}
        note_count = 0
    else:
        note_count = sum(1 for _ in iter_markdown(vault, {".git", "node_modules"}, follow_symlinks=bool(cfg.get("follow_symlinks", False))))
        checks["vault"] = {"ok": True, "path": str(vault), "message": "vault found"}
    checks["markdown_notes"] = {"ok": note_count > 0, "count": note_count, "message": f"{note_count} markdown notes found"}
    checks["db_parent"] = {"ok": db.parent.exists() or db.parent.parent.exists(), "path": str(db.parent), "message": "database parent is creatable" if db.parent.exists() or db.parent.parent.exists() else "database parent is not creatable"}
    checks["out_parent"] = {"ok": out.parent.exists() or out.parent.parent.exists(), "path": str(out.parent), "message": "output parent is creatable" if out.parent.exists() or out.parent.parent.exists() else "output parent is not creatable"}
    ok = all(check.get("ok", False) for check in checks.values())
    return {
        "ok": ok,
        "config": str(path),
        "settings": {"vault": str(vault), "db": str(db), "out": str(out), "hints": cfg.get("hints", DEFAULT_HINTS)},
        "checks": checks,
        "next": "Run `mneme update` then `mneme thought`." if ok else "Fix failed checks, or rerun `mneme init --force` with correct paths.",
    }


def stable_id(kind: str, name: str) -> str:
    return hashlib.sha1(f"{kind}:{name.lower()}".encode()).hexdigest()[:16]


def relationship_type(relation_id: str) -> dict:
    for rel in DEFAULT_RELATIONSHIP_TYPES:
        if rel["id"] == relation_id:
            return dict(rel)
    return {
        "id": relation_id,
        "label": relation_id.replace("_", " "),
        "inverse_id": None,
        "category": "unknown",
        "domain_type": "any",
        "range_type": "any",
        "description": "Unknown relationship type. Treat as requiring validation before semantic use.",
        "requires_validation": True,
        "symmetric": False,
        "transitive": False,
    }


def seed_relationship_types(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO relationship_types(id,label,inverse_id,category,domain_type,range_type,description,requires_validation,symmetric,transitive)
        VALUES(:id,:label,:inverse_id,:category,:domain_type,:range_type,:description,:requires_validation,:symmetric,:transitive)
        ON CONFLICT(id) DO UPDATE SET
          label=excluded.label,
          inverse_id=excluded.inverse_id,
          category=excluded.category,
          domain_type=excluded.domain_type,
          range_type=excluded.range_type,
          description=excluded.description,
          requires_validation=excluded.requires_validation,
          symmetric=excluded.symmetric,
          transitive=excluded.transitive
        """,
        [
            {
                **rel,
                "requires_validation": int(rel["requires_validation"]),
                "symmetric": int(rel["symmetric"]),
                "transitive": int(rel["transitive"]),
            }
            for rel in DEFAULT_RELATIONSHIP_TYPES
        ],
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,source_path TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confidence REAL DEFAULT 1.0,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS relationship_types(id TEXT PRIMARY KEY,label TEXT NOT NULL,inverse_id TEXT,category TEXT NOT NULL,domain_type TEXT DEFAULT 'any',range_type TEXT DEFAULT 'any',description TEXT DEFAULT '',requires_validation INTEGER DEFAULT 1,symmetric INTEGER DEFAULT 0,transitive INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,src_id TEXT NOT NULL,dst_id TEXT NOT NULL,relation TEXT NOT NULL,source_path TEXT,confidence REAL DEFAULT 1.0,evidence_text TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT DEFAULT 'active',strength REAL DEFAULT 1.0,source_type TEXT DEFAULT 'vault',metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS edge_debug_log(id TEXT PRIMARY KEY,edge_id TEXT NOT NULL,event TEXT NOT NULL,actor TEXT NOT NULL,thinking_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,note_id TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,source_path TEXT NOT NULL,score REAL DEFAULT 0,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thoughts(id TEXT PRIMARY KEY,seed_id TEXT,path_json TEXT NOT NULL,title TEXT NOT NULL,insight TEXT NOT NULL,action TEXT,image_path TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thought_tasks(id TEXT PRIMARY KEY,thought_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',lifecycle_tag TEXT,mission TEXT,done_when TEXT,first_move TEXT,writeback_target TEXT,evidence TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS senses(id TEXT PRIMARY KEY,type TEXT NOT NULL,config_json TEXT DEFAULT '{}',enabled INTEGER DEFAULT 1,last_run_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sense_events(id TEXT PRIMARY KEY,sense_id TEXT NOT NULL,sense_type TEXT NOT NULL,source_id TEXT NOT NULL,source_uri TEXT,event_type TEXT,title TEXT,text_hash TEXT,observed_at TEXT,ingested_at TEXT,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS thought_candidates(id TEXT PRIMARY KEY,seed_id TEXT,seed_observation_id TEXT,activation_score REAL DEFAULT 0,why_now_json TEXT DEFAULT '{}',suggested_action TEXT,action_type TEXT,status TEXT DEFAULT 'candidate',surfaced_count INTEGER DEFAULT 0,last_surfaced_at TEXT,cooldown_until TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thought_feedback(id TEXT PRIMARY KEY,thought_id TEXT NOT NULL,feedback_type TEXT NOT NULL,reason TEXT,strength_delta REAL DEFAULT 0,cooldown_until TEXT,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_thought_tasks_status ON thought_tasks(status);
    CREATE INDEX IF NOT EXISTS idx_thought_tasks_thought ON thought_tasks(thought_id);
    CREATE INDEX IF NOT EXISTS idx_sense_events_source ON sense_events(source_id);
    CREATE INDEX IF NOT EXISTS idx_thought_candidates_status ON thought_candidates(status);
    CREATE INDEX IF NOT EXISTS idx_thought_candidates_score ON thought_candidates(activation_score);
    CREATE INDEX IF NOT EXISTS idx_thought_feedback_thought ON thought_feedback(thought_id);
    CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
    CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
    CREATE INDEX IF NOT EXISTS idx_edge_debug_edge ON edge_debug_log(edge_id);
    CREATE INDEX IF NOT EXISTS idx_obs_note ON observations(note_id);
    """)
    for ddl in [
        "ALTER TABLE edges ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE edges ADD COLUMN strength REAL DEFAULT 1.0",
        "ALTER TABLE edges ADD COLUMN source_type TEXT DEFAULT 'vault'",
        "ALTER TABLE edges ADD COLUMN metadata_json TEXT DEFAULT '{}'",
        "ALTER TABLE observations ADD COLUMN sense_event_id TEXT",
        "ALTER TABLE observations ADD COLUMN metadata_json TEXT DEFAULT '{}'",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    seed_relationship_types(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_status ON edges(status)")


def upsert_node(conn, kind, name, source_path=None, confidence=1.0, metadata=None):
    nid = stable_id(kind, name); ts = now_iso()
    conn.execute("""INSERT INTO nodes(id,type,name,source_path,created_at,updated_at,confidence,metadata_json) VALUES(?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, source_path=COALESCE(excluded.source_path,nodes.source_path), confidence=max(nodes.confidence, excluded.confidence), metadata_json=excluded.metadata_json""",
    (nid, kind, name.strip(), source_path, ts, ts, confidence, json.dumps(metadata or {}, ensure_ascii=False)))
    return nid


def edge_creation_thinking(relation: str, source_path: str, evidence: str, confidence: float) -> dict:
    rationale_by_relation = {
        "links_to": "Extracted from an explicit Markdown wikilink. This proves a note-level reference, not necessarily a semantic real-world relationship.",
        "has_heading": "Extracted from a Markdown heading inside the source note.",
        "mentions_email": "Extracted from an email address mention inside the source note.",
        "mentions_date": "Extracted from a date-like phrase inside an observation.",
    }
    if relation.startswith("has_") and relation not in rationale_by_relation:
        rationale = "Extracted from scored note evidence such as a task or salient bullet. The relation type records the observation kind."
    else:
        rationale = rationale_by_relation.get(relation, "Extracted by Mneme ingestion using deterministic source parsing.")
    return {
        "relation": relation,
        "relationship_type": relationship_type(relation),
        "source_path": source_path,
        "evidence_text": evidence[:500] if evidence else "",
        "confidence": confidence,
        "rationale": rationale,
    }


def log_edge_event(conn, edge_id: str, event: str, actor: str, thinking: dict) -> str:
    ts = now_iso()
    payload = json.dumps(thinking, ensure_ascii=False, sort_keys=True)
    event_id = hashlib.sha1(f"{edge_id}:{event}:{actor}:{payload}:{ts}".encode()).hexdigest()[:20]
    conn.execute(
        "INSERT INTO edge_debug_log(id,edge_id,event,actor,thinking_json,created_at) VALUES(?,?,?,?,?,?)",
        (event_id, edge_id, event, actor, payload, ts),
    )
    return event_id


def deterministic_ingest_status(relation: str) -> str:
    """Default status for deterministic vault parsing.

    Keep source-contained observations active because they are provenance edges, but
    leave navigation/extraction links as candidates until an explicit validation or
    promotion pass chooses them. This keeps the active graph selective instead of
    turning every parsed link into a surfaced connection.
    """
    rel = relationship_type(relation)
    if rel.get("category") == "observation":
        return "active"
    return "candidate"


def upsert_edge(conn, src, dst, relation, source_path, evidence="", confidence=1.0, status="active", strength=None, source_type="vault", metadata=None):
    eid = hashlib.sha1(f"{src}:{relation}:{dst}:{source_path}:{evidence[:80]}".encode()).hexdigest()[:20]; ts = now_iso()
    inserted = conn.execute("SELECT 1 FROM edges WHERE id=?", (eid,)).fetchone() is None
    if strength is None:
        strength = confidence
    conn.execute("""INSERT INTO edges(id,src_id,dst_id,relation,source_path,confidence,evidence_text,created_at,updated_at,status,strength,source_type,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, confidence=max(edges.confidence, excluded.confidence), strength=max(edges.strength, excluded.strength), status=excluded.status, source_type=excluded.source_type, metadata_json=excluded.metadata_json""",
    (eid, src, dst, relation, source_path, confidence, evidence[:500], ts, ts, status, strength, source_type, json.dumps(metadata or {}, ensure_ascii=False)))
    if inserted:
        log_edge_event(conn, eid, "created", "ingest", edge_creation_thinking(relation, source_path, evidence, confidence))
    return eid


def add_observation(conn, note_id, kind, text, source_path, score, sense_event_id=None, metadata=None):
    oid = hashlib.sha1(f"{note_id}:{kind}:{text}".encode()).hexdigest()[:20]
    conn.execute(
        """INSERT INTO observations(id,note_id,kind,text,source_path,score,created_at,sense_event_id,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET score=max(observations.score, excluded.score), sense_event_id=COALESCE(excluded.sense_event_id, observations.sense_event_id), metadata_json=excluded.metadata_json""",
        (oid, note_id, kind, text[:1000], source_path, score, now_iso(), sense_event_id, json.dumps(metadata or {}, ensure_ascii=False)),
    )
    return oid


def note_type(path: Path) -> str:
    parent = path.parent.name.lower()
    return {"people":"person","person":"person","projects":"project","project":"project","places":"place","place":"place","finance":"finance","money":"finance","events":"event","event":"event"}.get(parent, "note")


def title_from_text(path: Path, text: str) -> str:
    match = HEADING_RE.search(text)
    return (match.group(2).strip().strip("#") if match else path.stem.replace("-", " ").replace("_", " "))[:120]


def observation_score(text: str, hints: list[str]):
    low = text.lower(); kind = "fact"; score = 1.0
    for candidate, words in STATUS_WORDS.items():
        if any(word in low for word in words):
            kind = candidate; score += {"blocked":3.0,"risk":2.5,"done":1.5}.get(candidate,1.0)
    if any(h.lower() in low for h in hints): score += 2.0
    if DATE_RE.search(text): score += 1.0
    return kind, score


def is_relative_to(child: Path, parent: Path) -> bool:
    """Return True when *child* resolves inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def iter_markdown(vault: Path, exclude_parts: Iterable[str] = (), follow_symlinks: bool = False):
    excludes = set(exclude_parts)
    vault_root = vault.resolve()
    for path in sorted(vault.rglob("*.md")):
        if any(part in excludes for part in path.parts):
            continue
        if path.is_symlink() and not follow_symlinks:
            continue
        resolved = path.resolve()
        if not is_relative_to(resolved, vault_root):
            continue
        yield path


def resolve_vault_write_path(vault: Path, note_path: str | Path) -> tuple[Path, str]:
    vault_root = vault.resolve()
    raw = Path(note_path)
    if raw.is_absolute():
        raise ValueError("note path must be relative and stay inside the vault")
    target = (vault_root / raw).resolve()
    if not is_relative_to(target, vault_root):
        raise ValueError("note path must stay inside the vault")
    if target.suffix.lower() != ".md":
        raise ValueError("note path must end with .md")
    return target, target.relative_to(vault_root).as_posix()


def write_note(vault: Path, note_path: str | Path, content: str, mode: str = "create") -> dict:
    from . import md_edit

    if mode == "append":
        target = md_edit.safe_resolve(vault, note_path)
        if not target.exists():
            raise FileNotFoundError(f"note does not exist: {md_edit.rel_path(vault, target)}")
    try:
        result = md_edit.write_note(vault, note_path, content, mode=mode)
    except ValueError as exc:
        message = str(exc)
        if "already exists" in message:
            raise FileExistsError(message) from exc
        if "absolute" in message or ".." in message or "escapes vault" in message:
            raise ValueError("note path must stay inside the vault") from exc
        raise
    return {"path": result["path"], "mode": mode, "bytes": result["bytes"], "changed": result["changed"], "backup": result.get("backup")}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:80] or "research-resolution"


def research_note_content(payload: dict) -> str:
    title = payload.get("title") or "Research resolution"
    date = payload.get("date") or dt.datetime.now(dt.timezone.utc).date().isoformat()
    lines = [f"# {title}", "", "Source type: user-initiated research resolution  ", f"Date resolved: {date}  "]
    if payload.get("canonical_project"):
        lines.append(f"Canonical project: [[{payload['canonical_project']}]]  ")
    if payload.get("links"):
        lines.append("Links: " + ", ".join(f"[[{link}]]" for link in payload["links"]) + "  ")
    lines.extend(["", "## Sources checked"])
    for source in payload.get("sources_checked") or []:
        lines.append(f"- {source}")
    lines.extend(["", "## Resolved claims"])
    for claim in payload.get("claims") or []:
        confidence = float(claim.get("confidence") or 0.0)
        strength = float(claim.get("strength") if claim.get("strength") is not None else confidence)
        certainty = claim.get("certainty") or ("confirmed" if confidence >= 0.9 else "candidate")
        lines.append(f"- **{claim.get('subject','?')}** --`{claim.get('predicate') or claim.get('relation') or 'related_to'}`--> **{claim.get('object','?')}**")
        lines.append(f"  - Status: {certainty}; confidence {confidence:.2f}; strength {strength:.2f}")
        if claim.get("evidence"):
            lines.append(f"  - Evidence: {claim['evidence']}")
    if payload.get("unresolved"):
        lines.extend(["", "## Unresolved / needs confirmation"])
        for item in payload["unresolved"]:
            lines.append(f"- {item}")
    lines.extend(["", "## Writeback rule", "Near-certain sourced claims can become active graph edges. Pending, unsupported, or lower-confidence claims stay candidate and must not drive resolved thoughts."])
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).decode("ascii").rstrip("=")
    lines.extend(["", f"<!-- mneme-research-resolution-b64: {encoded} -->"])
    return "\n".join(lines).strip() + "\n"


def claim_status(claim: dict, active_threshold: float = 0.9) -> str:
    if claim.get("status") in {"candidate", "killed"}:
        return claim["status"]
    evidence = str(claim.get("evidence") or claim.get("evidence_text") or "").strip()
    if not evidence:
        return "candidate"
    certainty = str(claim.get("certainty") or "").lower()
    confidence = float(claim.get("confidence") or 0.0)
    if certainty in {"confirmed", "certain", "user_confirmed", "absolutely_certain"} and confidence >= active_threshold:
        return "active"
    return "candidate"


def research_payload_from_note(text: str) -> dict | None:
    match = RESEARCH_RESOLUTION_RE.search(text)
    if not match:
        return None
    try:
        encoded = match.group(1)
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_research_edges(conn: sqlite3.Connection, note_path: str, payload: dict, active_threshold: float = 0.9, actor: str = "mneme") -> list[dict]:
    created = []
    for claim in payload.get("claims") or []:
        subject = claim["subject"]
        obj = claim["object"]
        relation = claim.get("predicate") or claim.get("relation") or "related_to"
        confidence = float(claim.get("confidence") or 0.0)
        strength = float(claim.get("strength") if claim.get("strength") is not None else confidence)
        status = claim_status(claim, active_threshold)
        evidence = claim.get("evidence") or claim.get("evidence_text") or ""
        src = upsert_node(conn, claim.get("subject_type", "entity"), subject, note_path, confidence, claim.get("subject_metadata") or {})
        dst = upsert_node(conn, claim.get("object_type", "entity"), obj, note_path, confidence, claim.get("object_metadata") or {})
        edge_id = upsert_edge(
            conn,
            src,
            dst,
            relation,
            note_path,
            evidence,
            confidence,
            status=status,
            strength=strength,
            source_type=claim.get("source_type") or "research",
            metadata={"research_resolution": True, "certainty": claim.get("certainty"), "sources_checked": payload.get("sources_checked") or []},
        )
        existing_debug = conn.execute(
            "SELECT 1 FROM edge_debug_log WHERE edge_id=? AND event='research_writeback' LIMIT 1",
            (edge_id,),
        ).fetchone()
        if existing_debug is None:
            log_edge_event(conn, edge_id, "research_writeback", actor, {
                "status": status,
                "strength": strength,
                "confidence": confidence,
                "source_type": claim.get("source_type") or "research",
                "evidence_text": evidence,
                "source_path": note_path,
                "rationale": "User-initiated research created this weighted graph edge; active only if sourced, confirmed, and above threshold.",
                "active_threshold": active_threshold,
            })
        created.append({"id": edge_id, "src": subject, "predicate": relation, "dst": obj, "status": status, "strength": strength, "confidence": confidence})
    return created


def write_research_resolution(vault: Path, db_path: Path, payload: dict | str, active_threshold: float = 0.9) -> dict:
    if isinstance(payload, str):
        payload = json.loads(payload)
    date = payload.get("date") or dt.datetime.now(dt.timezone.utc).date().isoformat()
    note_path = payload.get("note_path") or f"Sources/{date}_{slugify(payload.get('slug') or payload.get('title'))}-resolution.md"
    content = research_note_content(payload)
    written = write_note(vault, note_path, content, mode="overwrite")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    created = write_research_edges(conn, note_path, payload, active_threshold, actor="mneme")
    conn.commit()
    conn.close()
    return {"note_path": written["path"], "claims_written": len(created), "edges": created, "written": True}


def clear_graph_for_rebuild(conn: sqlite3.Connection, preserve_thoughts: bool = False) -> dict:
    """Clear ingest-derived graph state while preserving durable validation state.

    Mneme's rebuild path must satisfy two constraints at once:
    - privacy: stale vault-ingested content must be removed when notes disappear;
    - safety: user/agent validated edges must not be silently demoted or deleted.

    Therefore we preserve killed tombstones and active non-ingest edges (for example
    research writeback edges with source_type='receipt'), but we clear ordinary
    vault/ingest edges so deleted private note content cannot linger.
    """
    init_db(conn)
    preserved_edge_rows = conn.execute(
        """
        SELECT id,src_id,dst_id FROM edges
        WHERE status='killed'
           OR (status='active' AND COALESCE(source_type,'vault') NOT IN ('vault','ingest'))
        """
    ).fetchall()
    preserved_edges = {row[0] for row in preserved_edge_rows}
    preserved_nodes = {node_id for _, src_id, dst_id in preserved_edge_rows for node_id in (src_id, dst_id) if node_id}
    if not preserve_thoughts:
        conn.execute("DELETE FROM thoughts")
    conn.execute("DELETE FROM observations")
    if preserved_edges:
        edge_placeholders = ','.join('?' for _ in preserved_edges)
        conn.execute(f"DELETE FROM edge_debug_log WHERE edge_id NOT IN ({edge_placeholders})", tuple(preserved_edges))
        conn.execute(f"DELETE FROM edges WHERE id NOT IN ({edge_placeholders})", tuple(preserved_edges))
    else:
        conn.execute("DELETE FROM edge_debug_log")
        conn.execute("DELETE FROM edges")
    if preserved_nodes:
        node_placeholders = ','.join('?' for _ in preserved_nodes)
        conn.execute(f"DELETE FROM nodes WHERE id NOT IN ({node_placeholders})", tuple(preserved_nodes))
    else:
        conn.execute("DELETE FROM nodes")
    return {
        "preserved_active_edges": conn.execute("SELECT count(*) FROM edges WHERE status='active'").fetchone()[0],
        "preserved_killed_edges": conn.execute("SELECT count(*) FROM edges WHERE status='killed'").fetchone()[0],
    }


def _event_node_type(event) -> str:
    metadata = getattr(event, "metadata", {}) or {}
    node_type = metadata.get("node_type")
    if node_type:
        return str(node_type)
    if getattr(event, "event_type", "") == "calendar_event":
        return "event"
    if getattr(event, "event_type", "") == "task":
        return "task"
    if getattr(event, "event_type", "") == "email_message":
        return "message"
    return "source"


def _event_evidence(text: str, hints: list[str]) -> list[tuple[str, str, float]]:
    evidence: list[tuple[str, str, float]] = []
    for m in TASK_RE.finditer(text):
        done = m.group(1).lower() == "x"
        evidence.append(("done" if done else "blocked", m.group(2).strip(), 3.0 if not done else 1.5))
    for m in BULLET_RE.finditer(text):
        body = re.sub(r"\s+", " ", m.group(1).strip())
        if re.match(r"^\[[ xX]\]\s+", body):
            continue
        if 8 <= len(body) <= 350:
            kind, score = observation_score(body, hints)
            if score >= 3 or kind in {"blocked", "risk"}:
                evidence.append((kind, body, score))
    if not evidence:
        compact = re.sub(r"\s+", " ", text).strip()
        if compact:
            kind, score = observation_score(compact[:350], hints)
            if kind in {"blocked", "risk"} or score >= 3:
                evidence.append((kind, compact[:350], score))
    return evidence[:40]


def ingest_sense_events(conn: sqlite3.Connection, events: Iterable[Any], *, hints: list[str] | None = None) -> dict:
    """Normalize sensed source events into graph nodes, observations, and candidate links."""
    init_db(conn)
    hints = hints or DEFAULT_HINTS
    stats: dict[str, Any] = {"events": 0, "nodes": 0, "observations": 0, "edges": 0, "by_sense": {}, "by_event_type": {}}
    for event in events:
        text = str(getattr(event, "text", "") or "")
        if not text.strip():
            continue
        stats["events"] += 1
        stats["by_sense"].setdefault(event.sense_id, {"events": 0})
        stats["by_sense"][event.sense_id]["events"] += 1
        stats["by_event_type"][event.event_type] = stats["by_event_type"].get(event.event_type, 0) + 1
        ts = now_iso()
        text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
        conn.execute(
            """INSERT INTO senses(id,type,config_json,enabled,last_run_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET type=excluded.type,last_run_at=excluded.last_run_at,updated_at=excluded.updated_at""",
            (event.sense_id, event.sense_type, "{}", 1, ts, ts, ts),
        )
        conn.execute(
            """INSERT INTO sense_events(id,sense_id,sense_type,source_id,source_uri,event_type,title,text_hash,observed_at,ingested_at,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,text_hash=excluded.text_hash,observed_at=excluded.observed_at,ingested_at=excluded.ingested_at,metadata_json=excluded.metadata_json""",
            (
                event.id,
                event.sense_id,
                event.sense_type,
                event.source_id,
                event.source_uri,
                event.event_type,
                event.title,
                text_hash,
                event.observed_at,
                ts,
                json.dumps(getattr(event, "metadata", {}) or {}, ensure_ascii=False),
            ),
        )
        event_metadata = getattr(event, "metadata", {}) or {}
        source_path = str(event_metadata.get("path") or event.source_uri or event.source_id)
        edge_source_type = "vault" if event.sense_type in {"md", "markdown"} else event.sense_type
        node_name = (event.title or event.source_id).strip()[:120]
        nid = upsert_node(
            conn,
            _event_node_type(event),
            node_name,
            source_path,
            getattr(event, "confidence", 1.0),
            {"sense_id": event.sense_id, "sense_type": event.sense_type, "source_id": event.source_id, "event_type": event.event_type, **event_metadata},
        )
        stats["nodes"] += 1
        research_payload = research_payload_from_note(text)
        if research_payload:
            written = write_research_edges(conn, source_path, research_payload, actor="ingest")
            stats["edges"] += len(written)
        links = set(getattr(event, "links", []) or []) | {target.strip() for target in WIKILINK_RE.findall(text) if target.strip()}
        for target in sorted(links):
            tid = upsert_node(conn, "reference", target.strip(), None, 0.8)
            link_evidence = f"[[{target.strip()}]]" if event.sense_type in {"md", "markdown"} else target.strip()
            upsert_edge(conn, nid, tid, "links_to", source_path, link_evidence, 0.8, status=deterministic_ingest_status("links_to"), source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id})
            stats["edges"] += 1
        for _, heading in HEADING_RE.findall(text):
            if 2 < len(heading) < 100:
                hid = upsert_node(conn, "heading", heading.strip(), source_path, 0.7)
                upsert_edge(conn, nid, hid, "has_heading", source_path, heading.strip(), 0.7, status=deterministic_ingest_status("has_heading"), source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id})
                stats["edges"] += 1
        for email in sorted(set(EMAIL_RE.findall(text))):
            eid = upsert_node(conn, "email", email, source_path, 0.9)
            upsert_edge(conn, nid, eid, "mentions_email", source_path, email, 0.9, status=deterministic_ingest_status("mentions_email"), source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id})
            stats["edges"] += 1
        for entity in sorted(set(getattr(event, "entities", []) or [])):
            ent_id = upsert_node(conn, "entity", entity, None, 0.6)
            upsert_edge(conn, nid, ent_id, "co_mentioned_candidate", source_path, entity, 0.5, status="candidate", source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id})
            stats["edges"] += 1
        for kind, body, score in _event_evidence(text, hints):
            oid_value = add_observation(conn, nid, kind, body, source_path, score, sense_event_id=event.id, metadata={"sense_id": event.sense_id, "sense_type": event.sense_type, "source_id": event.source_id, "event_type": event.event_type})
            stats["observations"] += 1
            oid = upsert_node(conn, "observation", body[:90], source_path, min(1.0, score / 6), {"kind": kind, "sense_event_id": event.id})
            upsert_edge(conn, nid, oid, f"has_{kind}", source_path, body, min(1.0, score / 6), status=deterministic_ingest_status(f"has_{kind}"), source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id, "observation_id": oid_value})
            stats["edges"] += 1
            for date_text in DATE_RE.findall(body):
                did = upsert_node(conn, "date", date_text, source_path, 0.75)
                upsert_edge(conn, oid, did, "mentions_date", source_path, body, 0.75, status=deterministic_ingest_status("mentions_date"), source_type=edge_source_type, metadata={"sense_id": event.sense_id, "sense_event_id": event.id})
                stats["edges"] += 1
    return stats


def ingest_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, rebuild: bool = True, follow_symlinks: bool = False) -> dict:
    from .senses.markdown import MarkdownSense

    hints = hints or DEFAULT_HINTS; db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path); init_db(conn)
    preserved = {}
    if rebuild:
        preserved = clear_graph_for_rebuild(conn, preserve_thoughts=False)
    else:
        conn.execute("DELETE FROM observations")
    stats = ingest_sense_events(conn, MarkdownSense(sense_id="vault", vault=vault, follow_symlinks=follow_symlinks).collect(limit=max_notes), hints=hints)
    conn.commit(); counts=dict(conn.execute("SELECT 'nodes', count(*) FROM nodes UNION ALL SELECT 'edges', count(*) FROM edges UNION ALL SELECT 'observations', count(*) FROM observations").fetchall()); conn.close()
    return {"notes_read":stats["events"],"edges_added":stats["edges"],"observations_added":stats["observations"],**counts,**preserved,"db":str(db_path)}


def activate_candidate_edges(db_path: Path, mode: str = "validated-only", dry_run: bool = False) -> dict:
    """Explicit opt-in promotion for users who want to process candidates in bulk.

    Default `validated-only` promotes only candidates carrying research-resolution
    metadata with non-ingest source types. `all` is deliberately explicit because
    turning every parsed candidate active collapses Mneme's selectivity.
    """
    conn = sqlite3.connect(db_path)
    init_db(conn)
    if mode == "validated-only":
        where = "status='candidate' AND COALESCE(source_type,'vault') NOT IN ('vault','ingest') AND metadata_json LIKE '%research_resolution%'"
    elif mode == "all":
        where = "status='candidate'"
    else:
        conn.close()
        raise ValueError("mode must be 'validated-only' or 'all'")
    total = conn.execute(f"SELECT count(*) FROM edges WHERE {where}").fetchone()[0]
    if not dry_run:
        conn.execute(f"UPDATE edges SET status='active', updated_at=? WHERE {where}", (now_iso(),))
        conn.commit()
    counts = dict(conn.execute("SELECT status,count(*) FROM edges GROUP BY status").fetchall())
    conn.close()
    return {"mode": mode, "dry_run": dry_run, "would_activate": total, "activated": 0 if dry_run else total, "edges_by_status": counts, "db": str(db_path)}


def update_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, follow_symlinks: bool = False) -> dict:
    """Synchronize graph tables from the current vault while preserving generated thoughts.

    This is safer than ``--append`` for day-to-day updates because deleted or renamed
    notes do not leave stale nodes/edges behind, but the thought history remains.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    preserved = clear_graph_for_rebuild(conn, preserve_thoughts=True)
    conn.commit()
    conn.close()
    stats = ingest_vault(vault, db_path, hints, max_notes, rebuild=False, follow_symlinks=follow_symlinks)
    stats["mode"] = "update"
    stats["preserved"] = ["thoughts", "active_non_ingest_edges", "killed_edge_tombstones"]
    stats.update(preserved)
    return stats


def get_node(conn, node_id):
    row=conn.execute("SELECT id,type,name,source_path,metadata_json FROM nodes WHERE id=?",(node_id,)).fetchone()
    return {} if not row else {"id":row[0],"type":row[1],"name":row[2],"source_path":row[3],"metadata":json.loads(row[4] or "{}")}


def neighbors(conn, node_id):
    rows=conn.execute("""SELECT e.relation,n.id,n.name FROM edges e JOIN nodes n ON n.id=e.dst_id WHERE e.src_id=? AND COALESCE(e.status,'active')='active' UNION ALL SELECT 'reverse_'||e.relation,n.id,n.name FROM edges e JOIN nodes n ON n.id=e.src_id WHERE e.dst_id=? AND COALESCE(e.status,'active')='active'""",(node_id,node_id)).fetchall()
    return [(r,i,n) for r,i,n in rows]


BORING_THOUGHT_NODE_NAMES = {"index", "home", "readme", "daily notes", "memory"}
BORING_THOUGHT_RELATIONS = {"links_to", "linked_from", "reference", "wikilink", "mentions"}


def _is_dateish_name(name: str | None) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}(\s+[-—].*)?$", (name or "").strip()))


def _base_relation(relation: str | None) -> str:
    rel = (relation or "").strip().lower()
    return rel.removeprefix("reverse_")


def _is_low_value_thought_step(relation: str | None, node: dict | None = None, name: str | None = None) -> bool:
    """Return True for graph-plumbing edges that make dull proactive cards.

    Date/index/reference edges remain in the graph for provenance and retrieval,
    but thought cards should prefer semantic or action-bearing bridges whenever
    possible instead of surfacing navigation like `date -> index`.
    """
    node = node or {}
    node_name = (name or node.get("name") or "").strip()
    low_name = node_name.lower()
    node_type = (node.get("type") or "").strip().lower()
    rel = _base_relation(relation)
    return rel in BORING_THOUGHT_RELATIONS and (
        low_name in BORING_THOUGHT_NODE_NAMES or node_type == "date" or _is_dateish_name(node_name)
    )


def _prefer_interesting_thought_steps(options, key):
    options = list(options)
    interesting = [item for item in options if not _is_low_value_thought_step(*key(item))]
    return interesting or options


def choose_seed(conn):
    recent={r[0] for r in conn.execute("SELECT seed_id FROM thoughts ORDER BY created_at DESC LIMIT 20").fetchall() if r[0]}
    rows=conn.execute("""SELECT n.id,COALESCE(sum(o.score),0) score FROM nodes n LEFT JOIN observations o ON o.note_id=n.id WHERE n.type IN ('project','finance','event','person','note') GROUP BY n.id ORDER BY score DESC,n.updated_at DESC LIMIT 80""").fetchall()
    candidates=[r for r in rows if r[0] not in recent] or rows
    if not candidates: raise RuntimeError("No graph nodes available; run ingest first")
    return random.choices([r[0] for r in candidates], weights=[max(1.0,r[1]) for r in candidates], k=1)[0]


def walk_graph(db_path: Path, seed_id: str | None = None, hops: int = 5, hints: list[str] | None = None):
    hints=hints or DEFAULT_HINTS; conn=sqlite3.connect(db_path); current=seed_id or choose_seed(conn); path=[get_node(conn,current)]; seen={current}
    for _ in range(hops):
        opts=[(rel,nid,name) for rel,nid,name in neighbors(conn,current) if nid not in seen]
        if not opts: break
        node_cache={nid:get_node(conn,nid) for _,nid,_ in opts}
        opts=_prefer_interesting_thought_steps(opts, lambda item: (item[0], node_cache[item[1]], item[2]))
        def weight(item):
            rel,nid,name=item; node=node_cache[nid]; ntype=node.get("type",""); low=name.lower(); score=1.0
            if ntype=="observation": score += 4
            if ntype in {"project","person","finance","event","wikilink"}: score += 2
            if ntype=="heading": score *= 0.25
            if any(h.lower() in low for h in hints): score += 3
            if any(w in low for w in ["blocked","needs","due","deadline","awaiting"]): score += 2
            if rel.startswith("has_blocked") or rel.startswith("has_risk"): score += 5
            return max(0.1,score)
        rel,nxt,_=random.choices(opts, weights=[weight(o) for o in opts], k=1)[0]
        node=get_node(conn,nxt); node["via"]=rel; path.append(node); seen.add(nxt); current=nxt
    conn.close(); return path


def explain_edge(db_path: Path, edge_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    edge_row = conn.execute(
        """
        SELECT e.id,e.relation,e.source_path,e.confidence,e.evidence_text,e.created_at,e.updated_at,
               s.id,s.type,s.name,s.source_path,s.metadata_json,
               d.id,d.type,d.name,d.source_path,d.metadata_json
        FROM edges e
        JOIN nodes s ON s.id=e.src_id
        JOIN nodes d ON d.id=e.dst_id
        WHERE e.id=?
        """,
        (edge_id,),
    ).fetchone()
    if edge_row is None:
        conn.close()
        raise KeyError(f"edge not found: {edge_id}")
    debug_rows = conn.execute(
        "SELECT event,actor,thinking_json,created_at FROM edge_debug_log WHERE edge_id=? ORDER BY created_at, CASE event WHEN 'created' THEN 0 ELSE 1 END, id",
        (edge_id,),
    ).fetchall()
    conn.close()

    def node(prefix: int) -> dict:
        return {
            "id": edge_row[prefix],
            "type": edge_row[prefix + 1],
            "name": edge_row[prefix + 2],
            "source_path": edge_row[prefix + 3],
            "metadata": json.loads(edge_row[prefix + 4] or "{}"),
        }

    return {
        "edge": {
            "id": edge_row[0],
            "relation": edge_row[1],
            "relationship_type": relationship_type(edge_row[1]),
            "source_path": edge_row[2],
            "confidence": edge_row[3],
            "evidence_text": edge_row[4],
            "created_at": edge_row[5],
            "updated_at": edge_row[6],
            "src": node(7),
            "dst": node(12),
        },
        "debug_log": [
            {"event": r[0], "actor": r[1], "thinking": json.loads(r[2] or "{}"), "created_at": r[3]}
            for r in debug_rows
        ],
    }


def weaken_edge(db_path: Path, edge_id: str, reason: str = "User dismissed this proposal", factor: float = 0.5, floor: float = 0.0) -> dict:
    """Reduce an edge's strength after explicit negative feedback.

    This is gentler than killing: a dismissal means the surfaced proposal was not
    useful enough now, not necessarily that the underlying relationship is false.
    Very weak active edges are demoted back to candidate so they stop driving
    surfaced thoughts as strongly.
    """
    factor = max(0.0, min(1.0, float(factor)))
    floor = max(0.0, float(floor))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM edges WHERE id=?", (edge_id,)).fetchone()
    if not row:
        conn.close()
        return {"weakened": 0, "id": edge_id, "error": "not_found"}
    if row["status"] == "killed":
        conn.close()
        return {"weakened": 0, "id": edge_id, "error": "already_killed"}
    previous = float(row["strength"] or 0.0)
    new_strength = round(max(floor, previous * factor), 6)
    new_status = row["status"]
    if row["status"] == "active" and new_strength < 0.10:
        new_status = "candidate"
    conn.execute(
        "UPDATE edges SET strength=?, status=?, updated_at=? WHERE id=? AND status!='killed'",
        (new_strength, new_status, now_iso(), edge_id),
    )
    log_edge_event(conn, edge_id, "weakened", "user_feedback", {
        "reason": reason,
        "factor": factor,
        "previous_strength": previous,
        "new_strength": new_strength,
        "previous_status": row["status"],
        "new_status": new_status,
    })
    conn.commit()
    conn.close()
    return {"weakened": 1, "id": edge_id, "previous_strength": previous, "strength": new_strength, "status": new_status}


def observations_for_seed(db_path: Path, seed_id: str, limit: int = 4):
    conn=sqlite3.connect(db_path); rows=conn.execute("SELECT text FROM observations WHERE note_id=? ORDER BY score DESC LIMIT ?",(seed_id,limit)).fetchall(); conn.close(); return [r[0] for r in rows]


def _node_by_id(conn: sqlite3.Connection, node_id: str) -> dict:
    node = get_node(conn, node_id)
    return node or {"id": node_id, "type": "unknown", "name": node_id, "source_path": None, "metadata": {}}


GUARDRAIL_WORDS = {"hallucinated", "hallucination", "stale", "superseded", "incorrect", "wrong", "tombstone"}
GUARDRAIL_DIRECTIVES = {"do not", "don't", "must not", "should not", "no longer", "unless fresh", "without fresh"}
_TOPIC_STOPWORDS = {
    "about", "active", "after", "again", "already", "before", "candidate", "confirmed", "correction",
    "could", "current", "daily", "drive", "evidence", "explicitly", "fresh", "from", "guardrail",
    "hallucinated", "hallucination", "into", "must", "notes", "observation", "only", "open",
    "overdue", "project", "prompt", "reply", "should", "source", "stale", "status", "still", "task",
    "that", "the", "this", "treat", "unless", "without", "would",
}


def is_guardrail_text(text: str) -> bool:
    """Return True when an observation is a correction/tombstone, not an action item."""
    low = text.lower()
    return any(word in low for word in GUARDRAIL_WORDS) and any(phrase in low for phrase in GUARDRAIL_DIRECTIVES)


def _topic_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower())
        if token not in _TOPIC_STOPWORDS and not token.isdigit()
    }


def is_suppressed_by_guardrail(text: str, guardrails: Iterable[str]) -> bool:
    """Return True when a stale/open-loop candidate overlaps a corrective guardrail.

    Mneme may ingest both old TODOs and later corrections. Proactive surfacing must
    not resurrect the old TODO when a newer note says that topic was stale, wrong,
    or hallucinated unless fresh evidence reactivates it. This helper is deliberately
    lexical and conservative: it requires a corrective directive plus topic overlap.
    """
    terms = _topic_terms(text)
    if not terms:
        return False
    for guardrail in guardrails:
        guard_terms = _topic_terms(guardrail)
        overlap = terms & guard_terms
        if len(overlap) >= 2 or (len(overlap) == 1 and len(terms) <= 3):
            return True
    return False


def _candidate_reasons(kind: str, text: str, score: float, hints: list[str]) -> tuple[float, list[str]]:
    low = text.lower(); reasons=[]; total = float(score)
    if is_guardrail_text(text):
        return -100.0, ["corrective guardrail, not an open task"]
    if kind == "blocked":
        total += 5; reasons.append("open loop / unresolved task")
    if kind == "risk":
        total += 4; reasons.append("risk or deadline language")
    if any(word in low for word in ["due", "deadline", "expires", "overdue", "urgent"]):
        total += 4; reasons.append("deadline pressure")
    if any(word in low for word in ["waiting", "awaiting", "follow up", "needs", "todo"]):
        total += 3; reasons.append("follow-up needed")
    matched = [hint for hint in hints if hint.lower() in low]
    if matched:
        total += 2 * len(matched); reasons.append("matches hints: " + ", ".join(matched[:4]))
    return total, reasons or ["high-signal observation"]


def _path_from_observation(conn: sqlite3.Connection, note_id: str, observation_text: str, hops: int) -> list[dict]:
    path=[_node_by_id(conn, note_id)]
    obs_node = conn.execute(
        """SELECT n.id FROM nodes n JOIN edges e ON e.dst_id=n.id
           WHERE e.src_id=? AND COALESCE(e.status,'active')='active' AND n.type='observation' AND n.name=? ORDER BY e.confidence DESC LIMIT 1""",
        (note_id, observation_text[:90]),
    ).fetchone()
    if obs_node:
        node = _node_by_id(conn, obs_node[0]); node["via"] = "has_observation"; path.append(node)
        date_row = conn.execute(
            "SELECT n.id,e.relation FROM edges e JOIN nodes n ON n.id=e.dst_id WHERE e.src_id=? AND COALESCE(e.status,'active')='active' AND n.type='date' ORDER BY n.name LIMIT 1",
            (obs_node[0],),
        ).fetchone()
        if date_row and len(path) < hops + 1:
            node = _node_by_id(conn, date_row[0])
            if not _is_low_value_thought_step(date_row[1], node):
                node["via"] = date_row[1]; path.append(node)
    if len(path) < hops + 1:
        rows = conn.execute(
            """SELECT n.id,e.relation FROM edges e JOIN nodes n ON n.id=e.dst_id
               WHERE e.src_id=? AND COALESCE(e.status,'active')='active' AND n.type IN ('wikilink','project','person','event','finance','note')
               ORDER BY CASE n.type WHEN 'wikilink' THEN 0 ELSE 1 END, n.name LIMIT ?""",
            (note_id, hops + 1 - len(path)),
        ).fetchall()
        rows = _prefer_interesting_thought_steps(rows, lambda item: (item[1], _node_by_id(conn, item[0]), None))
        for nid, rel in rows:
            if nid not in {n.get("id") for n in path}:
                node = _node_by_id(conn, nid); node["via"] = rel; path.append(node)
    return path


def list_thought_candidates(db_path: Path, limit: int = 5, hops: int = 5, hints: list[str] | None = None) -> list[dict]:
    hints = hints or DEFAULT_HINTS
    conn = sqlite3.connect(db_path)
    recent = {r[0] for r in conn.execute("SELECT seed_id FROM thoughts ORDER BY created_at DESC LIMIT 20").fetchall() if r[0]}
    rows = conn.execute(
        """SELECT o.note_id,o.kind,o.text,o.source_path,o.score,n.name,n.type,n.updated_at
           FROM observations o JOIN nodes n ON n.id=o.note_id
           ORDER BY o.score DESC,o.created_at DESC LIMIT 200"""
    ).fetchall()
    guardrails = [row[2] for row in rows if is_guardrail_text(row[2])]
    candidates=[]
    for note_id, kind, text, source_path, base_score, name, ntype, updated_at in rows:
        if is_suppressed_by_guardrail(text, guardrails):
            continue
        score, reasons = _candidate_reasons(kind, text, base_score, hints)
        if score < 0:
            continue
        if note_id in recent:
            score -= 3; reasons.append("recently surfaced penalty")
        if ntype in {"project", "finance", "event", "person"}:
            score += 1.5; reasons.append(f"important {ntype} note")
        path = _path_from_observation(conn, note_id, text, hops)
        candidate = {
            "base_score": round(score, 2),
            "score": round(score, 2),
            "seed": {"id": note_id, "name": name, "type": ntype, "source_path": source_path},
            "observation": {"kind": kind, "text": text, "source_path": source_path, "score": base_score},
            "evidence": [text],
            "reasons": reasons,
            "path": path,
        }
        actionability_score, internal_tags, actionability_reasons = actionability_from_candidate(candidate)
        candidate["score"] = round(actionability_score, 2)
        candidate["actionability_score"] = round(actionability_score, 2)
        candidate["internal_tags"] = internal_tags
        candidate["reasons"] = reasons + [r for r in actionability_reasons if r not in reasons]
        candidates.append(candidate)
    conn.close()
    candidates.sort(key=lambda c: (-c["score"], c["seed"]["name"].lower()))
    return candidates[:limit]


def _iso_add_duration(duration: str | None) -> str | None:
    if not duration:
        return None
    match = re.match(r"^\s*(\d+)\s*([hdw])\s*$", duration.lower())
    if not match:
        raise ValueError("duration must look like 4h, 7d, or 2w")
    amount = int(match.group(1))
    unit = match.group(2)
    delta = {"h": dt.timedelta(hours=amount), "d": dt.timedelta(days=amount), "w": dt.timedelta(weeks=amount)}[unit]
    return (dt.datetime.now(dt.timezone.utc) + delta).isoformat(timespec="seconds")


def _candidate_source_provenance(conn: sqlite3.Connection, observation_id: str | None, source_path: str | None) -> dict:
    event_row = None
    if observation_id:
        event_row = conn.execute(
            """SELECT se.id,se.sense_id,se.sense_type,se.source_id,se.source_uri,se.event_type,se.title,se.observed_at,se.metadata_json
               FROM observations o LEFT JOIN sense_events se ON se.id=o.sense_event_id
               WHERE o.id=?""",
            (observation_id,),
        ).fetchone()
    if event_row and event_row[0]:
        return {
            "sense_event_id": event_row[0],
            "sense_id": event_row[1],
            "sense_type": event_row[2],
            "source_id": event_row[3],
            "source_uri": event_row[4],
            "event_type": event_row[5],
            "title": event_row[6],
            "observed_at": event_row[7],
            "metadata": json.loads(event_row[8] or "{}"),
        }
    return {"source_uri": source_path}


def _feedback_penalty(conn: sqlite3.Connection, candidate_id: str) -> tuple[float, list[str]]:
    rows = conn.execute("SELECT feedback_type FROM thought_feedback WHERE thought_id=?", (candidate_id,)).fetchall()
    penalty = 0.0
    reasons: list[str] = []
    for (feedback_type,) in rows:
        if feedback_type == "deny":
            penalty -= 2.0; reasons.append("previously denied")
        elif feedback_type == "too_obvious":
            penalty -= 2.5; reasons.append("marked too obvious")
        elif feedback_type == "already_done":
            penalty -= 4.0; reasons.append("already done")
        elif feedback_type == "good_but_later":
            penalty -= 0.5; reasons.append("good but later")
        elif feedback_type == "acted":
            penalty -= 6.0; reasons.append("acted on")
    return penalty, reasons


def _corroboration_bonus(conn: sqlite3.Connection, observation_text: str, observation_id: str) -> tuple[float, dict]:
    terms = _topic_terms(observation_text)
    if not terms:
        return 0.0, {"source_diversity": 0, "overlap_terms": []}
    rows = conn.execute(
        """SELECT o.id,o.text,se.sense_id,se.sense_type
           FROM observations o LEFT JOIN sense_events se ON se.id=o.sense_event_id
           WHERE o.id != ? LIMIT 500""",
        (observation_id,),
    ).fetchall()
    senses: set[str] = set()
    overlap_terms: set[str] = set()
    for oid, text, sense_id, sense_type in rows:
        del oid
        overlap = terms & _topic_terms(text or "")
        if len(overlap) >= 2:
            senses.add(str(sense_id or sense_type or "unknown"))
            overlap_terms.update(overlap)
    if not senses:
        return 0.0, {"source_diversity": 0, "overlap_terms": []}
    bonus = min(3.0, 1.0 + 0.75 * max(0, len(senses) - 1))
    return bonus, {"source_diversity": len(senses), "overlap_terms": sorted(overlap_terms)[:8]}


def tick(db_path: Path, *, hints: list[str] | None = None, limit: int = 100) -> dict:
    hints = hints or DEFAULT_HINTS
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.row_factory = sqlite3.Row
    now = now_iso()
    rows = conn.execute(
        """SELECT o.id observation_id,o.note_id,o.kind,o.text,o.source_path,o.score,o.created_at,n.name,n.type
           FROM observations o JOIN nodes n ON n.id=o.note_id
           ORDER BY o.score DESC,o.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    guardrails = [row["text"] for row in rows if is_guardrail_text(row["text"])]
    upserted = 0
    skipped = 0
    for row in rows:
        if is_suppressed_by_guardrail(row["text"], guardrails):
            skipped += 1
            continue
        candidate_id = hashlib.sha1(f"thought-candidate:{row['observation_id']}".encode()).hexdigest()[:20]
        existing = conn.execute("SELECT status,cooldown_until,surfaced_count,last_surfaced_at FROM thought_candidates WHERE id=?", (candidate_id,)).fetchone()
        if existing and existing["status"] == "killed":
            skipped += 1
            continue
        if existing and existing["cooldown_until"] and existing["cooldown_until"] > now:
            skipped += 1
            continue
        score, reasons = _candidate_reasons(row["kind"], row["text"], row["score"], hints)
        if score < 0:
            skipped += 1
            continue
        factors: dict[str, float] = {"observation_score": float(row["score"] or 0)}
        if row["kind"] == "blocked":
            factors["blocked_observation"] = 3.0
        elif row["kind"] == "risk":
            factors["risk_observation"] = 2.5
        elif row["kind"] == "done":
            factors["done_observation"] = 0.5
        matched = [hint for hint in hints if hint.lower() in row["text"].lower()]
        if matched:
            factors["hint_match"] = float(2 * len(matched))
        if row["created_at"]:
            factors["freshness"] = 1.0
        corroboration, corroboration_info = _corroboration_bonus(conn, row["text"], row["observation_id"])
        if corroboration:
            factors["cross_sense_corroboration"] = corroboration
            reasons.append("corroborated by related sensed evidence")
        if existing and existing["surfaced_count"]:
            factors["recently_surfaced_penalty"] = -0.5 * int(existing["surfaced_count"])
        feedback_delta, feedback_reasons = _feedback_penalty(conn, candidate_id)
        if feedback_delta:
            factors["feedback_penalty"] = feedback_delta
            reasons.extend(feedback_reasons)
        activation = round(sum(factors.values()), 3)
        provenance = _candidate_source_provenance(conn, row["observation_id"], row["source_path"])
        why_now = {
            "score": activation,
            "factors": factors,
            "reasons": list(dict.fromkeys(reasons))[:8],
            "corroboration": corroboration_info,
            "evidence": row["text"],
            "seed": {"id": row["note_id"], "name": row["name"], "type": row["type"]},
            "observation": {"id": row["observation_id"], "kind": row["kind"], "text": row["text"], "score": row["score"]},
            "provenance": provenance,
        }
        action_type = "ask_user" if row["kind"] in {"blocked", "risk"} else "inspect"
        suggested = FIRST_MOVE_BY_KIND.get(row["kind"], FIRST_MOVE_BY_KIND["fact"])
        status = existing["status"] if existing and existing["status"] not in {"surfaced"} else "candidate"
        conn.execute(
            """INSERT INTO thought_candidates(id,seed_id,seed_observation_id,activation_score,why_now_json,suggested_action,action_type,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET activation_score=excluded.activation_score,why_now_json=excluded.why_now_json,suggested_action=excluded.suggested_action,action_type=excluded.action_type,updated_at=excluded.updated_at,status=CASE WHEN thought_candidates.status IN ('killed','accepted','acted','already_done') THEN thought_candidates.status ELSE excluded.status END""",
            (candidate_id, row["note_id"], row["observation_id"], activation, json.dumps(why_now, ensure_ascii=False), suggested, action_type, status, now, now),
        )
        upserted += 1
    conn.commit()
    total = conn.execute("SELECT count(*) FROM thought_candidates").fetchone()[0]
    conn.close()
    return {"candidates_updated": upserted, "skipped": skipped, "total_candidates": total, "db": str(db_path)}


def surface_thoughts(db_path: Path, *, limit: int = 1, mark_surfaced: bool = True) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    now = now_iso()
    rows = conn.execute(
        """SELECT * FROM thought_candidates
           WHERE status NOT IN ('killed','acted','already_done')
             AND (cooldown_until IS NULL OR cooldown_until <= ?)
           ORDER BY activation_score DESC, updated_at DESC
           LIMIT ?""",
        (now, limit),
    ).fetchall()
    results: list[dict] = []
    for row in rows:
        why = json.loads(row["why_now_json"] or "{}")
        observation = why.get("observation") or {}
        seed = why.get("seed") or {}
        result = {
            "id": row["id"],
            "title": _surface_title(observation),
            "seed": seed,
            "seed_observation_id": row["seed_observation_id"],
            "activation_score": row["activation_score"],
            "why_now": why,
            "suggested_action": row["suggested_action"],
            "action_type": row["action_type"],
            "evidence": [observation.get("text")] if observation.get("text") else [],
            "source": why.get("provenance") or {},
            "sense_provenance": why.get("provenance") or {},
            "feedback_options": ["accept", "deny", "snooze", "kill", "acted", "already_done", "too_obvious", "good_but_later"],
        }
        results.append(result)
        if mark_surfaced:
            conn.execute(
                "UPDATE thought_candidates SET surfaced_count=surfaced_count+1,last_surfaced_at=?,status=CASE WHEN status='candidate' THEN 'surfaced' ELSE status END,updated_at=? WHERE id=?",
                (now, now, row["id"]),
            )
    conn.commit()
    conn.close()
    return results


def _surface_title(observation: dict) -> str:
    kind = observation.get("kind") or "fact"
    text = str(observation.get("text") or "Thought candidate")
    prefix = {"blocked": "Unfinished loop", "risk": "Risk to check", "done": "Completed item to consolidate", "fact": "Possible connection"}.get(kind, "Thought candidate")
    return f"{prefix}: {text[:90]}"


def record_feedback(db_path: Path, thought_id: str, feedback_type: str, *, reason: str | None = None, snooze: str | None = None) -> dict:
    allowed = {"accept", "deny", "snooze", "kill", "acted", "already_done", "too_obvious", "good_but_later"}
    if feedback_type not in allowed:
        raise ValueError(f"feedback_type must be one of {sorted(allowed)}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    row = conn.execute("SELECT * FROM thought_candidates WHERE id=?", (thought_id,)).fetchone()
    if row is None:
        conn.close()
        raise KeyError(f"thought candidate not found: {thought_id}")
    cooldown_until = _iso_add_duration(snooze) if snooze else None
    status = row["status"]
    strength_delta = 0.0
    if feedback_type == "accept":
        status = "accepted"; strength_delta = 1.0
    elif feedback_type == "deny":
        status = "dismissed"; strength_delta = -1.0
    elif feedback_type == "kill":
        status = "killed"; strength_delta = -10.0
    elif feedback_type == "snooze":
        status = "snoozed"; cooldown_until = cooldown_until or _iso_add_duration("1d")
    elif feedback_type == "acted":
        status = "acted"; strength_delta = 2.0
    elif feedback_type == "already_done":
        status = "already_done"; strength_delta = -2.0
    elif feedback_type == "too_obvious":
        status = "candidate"; strength_delta = -1.5
    elif feedback_type == "good_but_later":
        status = "candidate"; cooldown_until = cooldown_until or _iso_add_duration("7d"); strength_delta = 0.25
    feedback_id = hashlib.sha1(f"{thought_id}:{feedback_type}:{reason}:{now_iso()}".encode()).hexdigest()[:20]
    now = now_iso()
    conn.execute(
        "INSERT INTO thought_feedback(id,thought_id,feedback_type,reason,strength_delta,cooldown_until,created_at) VALUES(?,?,?,?,?,?,?)",
        (feedback_id, thought_id, feedback_type, reason, strength_delta, cooldown_until, now),
    )
    conn.execute(
        "UPDATE thought_candidates SET status=?, cooldown_until=COALESCE(?, cooldown_until), activation_score=max(0, activation_score + ?), updated_at=? WHERE id=?",
        (status, cooldown_until, strength_delta, now, thought_id),
    )
    conn.commit()
    updated = conn.execute("SELECT id,status,activation_score,cooldown_until FROM thought_candidates WHERE id=?", (thought_id,)).fetchone()
    conn.close()
    return dict(updated) | {"feedback_id": feedback_id, "feedback_type": feedback_type}


def explain_thought(db_path: Path, thought_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    row = conn.execute("SELECT * FROM thought_candidates WHERE id=?", (thought_id,)).fetchone()
    if row is None:
        conn.close()
        raise KeyError(f"thought candidate not found: {thought_id}")
    why = json.loads(row["why_now_json"] or "{}")
    edge_rows = conn.execute(
        """SELECT e.id,e.relation,e.status,e.strength,e.confidence,e.evidence_text,s.name src,d.name dst
           FROM edges e JOIN nodes s ON s.id=e.src_id JOIN nodes d ON d.id=e.dst_id
           WHERE e.src_id=? OR e.dst_id=? OR e.metadata_json LIKE ?
           ORDER BY e.status,e.strength DESC LIMIT 20""",
        (row["seed_id"], row["seed_id"], f"%{row['seed_observation_id']}%"),
    ).fetchall()
    feedback_rows = conn.execute(
        "SELECT feedback_type,reason,strength_delta,cooldown_until,created_at FROM thought_feedback WHERE thought_id=? ORDER BY created_at",
        (thought_id,),
    ).fetchall()
    conn.close()
    return {
        "id": row["id"],
        "status": row["status"],
        "activation_score": row["activation_score"],
        "why_this_surfaced": why.get("reasons") or [],
        "activation_breakdown": why.get("factors") or {},
        "seed": why.get("seed") or {"id": row["seed_id"]},
        "seed_observation": why.get("observation") or {"id": row["seed_observation_id"]},
        "evidence": [why.get("evidence")] if why.get("evidence") else [],
        "sense_provenance": why.get("provenance") or {},
        "relationship_path": [dict(edge) for edge in edge_rows],
        "relationship_statuses": [{"id": edge["id"], "relation": edge["relation"], "status": edge["status"], "strength": edge["strength"]} for edge in edge_rows],
        "feedback_history": [dict(item) for item in feedback_rows],
        "feedback_effects": {
            "accept": "reinforces this candidate and keeps it inspectable",
            "deny": "weakens/dismisses without marking evidence false",
            "kill": "tombstones this candidate so it is not surfaced",
            "snooze": "sets a cooldown before resurfacing",
        },
        "suggested_action": row["suggested_action"],
        "action_type": row["action_type"],
        "cooldown_until": row["cooldown_until"],
    }


def _evidence_seed(obs: list[str]) -> str:
    return (obs[0] if obs else "").strip()


def _path_chain(path: list[dict], limit: int = 5) -> str:
    return " → ".join(n.get("name", "?") for n in path[:limit])


def _reasoned_next(prefix: str, evidence: str, fallback: str) -> str:
    if evidence:
        return f"{prefix} Evidence seed: {evidence[:170]}"
    return fallback


def _safe_thought_slug(text: str) -> str:
    return slugify(text)[:64] or "thought"


def actionability_from_candidate(candidate: dict) -> tuple[float, list[str], list[str]]:
    """Return a cheap actionability score using internal tags, not closure words.

    This is intentionally not a generic "pressure" metric and it does not try to
    decide whether something is resolved by scanning for words like done/closed.
    Closure should come from explicit writeback/dismissal tags in a later lifecycle
    layer. Here we only ask: can this surfaced object be turned into a useful next
    move?
    """
    score = float(candidate.get("base_score", candidate.get("score", 0)) or 0)
    kind = (candidate.get("observation") or {}).get("kind") or "fact"
    path = candidate.get("path") or []
    tags: list[str] = []
    reasons: list[str] = []

    lifecycle_tag, bonus, reason = LIFECYCLE_BY_KIND.get(kind, LIFECYCLE_BY_KIND["fact"])
    score += bonus
    tags.append(lifecycle_tag)
    reasons.append(reason)

    node_types = {str(node.get("type") or "").lower() for node in path}
    if node_types & {"person", "email"}:
        score += 2
        tags.append("mneme:near_human")
        reasons.append("human context nearby")
    if node_types & {"project", "event", "finance"}:
        score += 1.5
        tags.append("mneme:domain_anchor")
        reasons.append("anchored to an actionable domain")
    if any(str(node.get("type") or "").lower() == "date" for node in path):
        score += 1
        tags.append("mneme:has_date_anchor")
        reasons.append("date anchor nearby")

    return score, list(dict.fromkeys(tags)), reasons


def contract_from_candidate(candidate: dict) -> dict:
    observation = candidate.get("observation") or {}
    kind = observation.get("kind") or "fact"
    text = str(observation.get("text") or "").strip()
    path = candidate.get("path") or []
    score = float(candidate.get("actionability_score", candidate.get("score", 0)) or 0)
    tags = list(candidate.get("internal_tags") or [])
    actionability_reasons = []
    if not tags:
        score, tags, actionability_reasons = actionability_from_candidate(candidate)
    lifecycle_tag = tags[0] if tags else "mneme:thought/inspect"
    mission_prefix = MISSION_PREFIX_BY_KIND.get(kind, "Inspect this surfaced item")
    first_move = FIRST_MOVE_BY_KIND.get(kind, "Inspect the evidence and decide whether a next action exists.")
    source = observation.get("source_path") or (candidate.get("seed") or {}).get("source_path") or "unknown"
    target_seed = text or (candidate.get("seed") or {}).get("name") or "thought"
    return {
        "mission": f"{mission_prefix}: {target_seed[:180]}",
        "why_now": "; ".join((candidate.get("reasons") or actionability_reasons)[:4]),
        "done_when": THOUGHT_DONE_WHEN,
        "first_move": first_move,
        "needed_context": [node.get("name") for node in path if node.get("name")][:6],
        "evidence": candidate.get("evidence") or ([text] if text else []),
        "allowed_actions": ALLOWED_THOUGHT_ACTIONS,
        "writeback_target": f"Thoughts/{dt.datetime.now(dt.timezone.utc).date().isoformat()}_{_safe_thought_slug(target_seed)}.md",
        "writeback_required": kind in {"blocked", "risk"},
        "lifecycle_tag": lifecycle_tag,
        "internal_tags": tags,
        "actionability_score": round(score, 2),
        "source_path": source,
    }


def generate_thought(db_path: Path, path, candidate: dict | None = None):
    seed=path[0]; names=[n.get("name","?") for n in path]; obs=(candidate.get("evidence", []) if candidate else observations_for_seed(db_path, seed["id"], 4)); low=" ".join(names+obs).lower()
    contract = contract_from_candidate(candidate) if candidate else None
    why_now = (contract or {}).get("why_now") or ("; ".join(candidate.get("reasons", [])[:3]) if candidate else "weighted random graph traversal surfaced this path")
    chain = _path_chain(path)
    evidence = _evidence_seed(obs)
    if contract and contract.get("lifecycle_tag") == "mneme:thought/open_loop":
        title="Unfinished loop with a first move"
        insight=f"Why this matters: {names[0]} has an actionable open-loop tag along {chain}. Treat this as a small mission, not just context."
        action=_reasoned_next(f"Finish the contract first move: {contract['first_move']}", evidence, contract["first_move"])
    elif contract and contract.get("lifecycle_tag") == "mneme:thought/time_sensitive":
        title="Time-sensitive item to verify"
        insight=f"Why this matters: {chain} has a time-sensitive internal tag. Verify freshness before acting."
        action=_reasoned_next(f"Finish the contract first move: {contract['first_move']}", evidence, contract["first_move"])
    elif any(w in low for w in ["blocked","needs","awaiting","unresolved","todo","follow up","waiting"]):
        title="Open loop hiding in the graph"
        insight=f"Why this matters: {names[0]} is connected to unresolved language along {chain}. Mneme is surfacing it as a possible open loop, not as a resolved fact."
        action=_reasoned_next("Ask whether this is still pending, then choose the smallest next action.", evidence, "Pick the smallest next action and attach it to the source note.")
    elif any(w in low for w in ["due","deadline","expires","urgent","overdue"]):
        title="Deadline path worth checking"
        insight=f"Why this matters: {chain} touches time-sensitive language. Verify freshness before treating it as current urgency."
        action=_reasoned_next("Check whether the date/status is still current.", evidence, "Check whether the deadline/status is still current.")
    else:
        title="Reasoned graph walk"
        insight=f"Why this matters: Mneme explored {chain}. This may be useful, or it may be true-but-boring; the point is to test whether the bridge deserves promotion."
        action=_reasoned_next("Ask whether this connection changes what to do next.", evidence, "If this still matters, promote it to an explicit next action; otherwise let future walks drift elsewhere.")
    result={"title":title,"insight":insight,"action":action,"path":path,"observations":obs,"evidence":obs,"why_now":why_now,"score": candidate.get("score", 0) if candidate else 0}
    if contract:
        result["contract"] = contract
    return result


def _weighted_candidate_choice(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    weights=[max(0.1, float(c.get("score", 0))) for c in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def generate_proactive_thought(db_path: Path, hints: list[str] | None = None, hops: int = 5) -> dict:
    candidates = list_thought_candidates(db_path, limit=12, hops=hops, hints=hints)
    chosen = _weighted_candidate_choice(candidates)
    if chosen:
        return generate_thought(db_path, chosen["path"], chosen)
    return generate_thought(db_path, walk_graph(db_path, hops=hops, hints=hints))


def save_thought(db_path: Path, thought: dict, image_path: str | None = None):
    conn=sqlite3.connect(db_path); init_db(conn); tid=uuid.uuid4().hex[:16]
    created=now_iso()
    conn.execute("INSERT INTO thoughts(id,seed_id,path_json,title,insight,action,image_path,created_at) VALUES(?,?,?,?,?,?,?,?)",(tid,thought["path"][0].get("id"),json.dumps(thought["path"],ensure_ascii=False),thought["title"],thought["insight"],thought["action"],image_path,created))
    contract=thought.get("contract") or {}
    if contract:
        task_id=hashlib.sha1((tid+contract.get("mission","")).encode()).hexdigest()[:16]
        conn.execute("""INSERT INTO thought_tasks(id,thought_id,status,lifecycle_tag,mission,done_when,first_move,writeback_target,evidence,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(
            task_id,tid,"open",contract.get("lifecycle_tag"),contract.get("mission"),contract.get("done_when"),contract.get("first_move"),contract.get("writeback_target"),json.dumps(contract.get("evidence") or [],ensure_ascii=False),created,created))
    conn.commit(); conn.close(); return tid


def list_thought_tasks(db_path: Path, status: str | None = None) -> list[dict]:
    conn=sqlite3.connect(db_path); conn.row_factory=sqlite3.Row; init_db(conn)
    if status:
        rows=conn.execute("SELECT * FROM thought_tasks WHERE status=? ORDER BY created_at DESC",(status,)).fetchall()
    else:
        rows=conn.execute("SELECT * FROM thought_tasks ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(r) for r in rows]


def update_thought_task(db_path: Path, task_id: str, status: str, evidence: str = "") -> dict:
    allowed=THOUGHT_STATUSES
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    conn=sqlite3.connect(db_path); conn.row_factory=sqlite3.Row; init_db(conn)
    row=conn.execute("SELECT * FROM thought_tasks WHERE id=?",(task_id,)).fetchone()
    if row is None:
        conn.close(); raise KeyError(task_id)
    existing=[]
    try:
        existing=json.loads(row["evidence"] or "[]")
    except Exception:
        existing=[row["evidence"]] if row["evidence"] else []
    if evidence:
        existing.append(evidence)
    conn.execute("UPDATE thought_tasks SET status=?, evidence=?, updated_at=? WHERE id=?",(status,json.dumps(existing,ensure_ascii=False),now_iso(),task_id))
    conn.commit(); updated=conn.execute("SELECT * FROM thought_tasks WHERE id=?",(task_id,)).fetchone(); conn.close(); return dict(updated)


def record_thought_writeback(db_path: Path, task_id: str, target: str, evidence: str = "") -> dict:
    """Mark that a thought produced a human-visible note/writeback artifact."""
    marker = f"writeback:{target}"
    return update_thought_task(db_path, task_id, "acted", "; ".join(p for p in [marker, evidence] if p))


def record_thought_reminder(db_path: Path, task_id: str, reminder_id: str, evidence: str = "") -> dict:
    """Close a thought loop because a concrete reminder/task/calendar item exists."""
    marker = f"reminder:{reminder_id}"
    return update_thought_task(db_path, task_id, "resolved", "; ".join(p for p in [marker, evidence] if p))


def dismiss_thought_task(db_path: Path, task_id: str, reason: str) -> dict:
    """Explicitly dismiss a thought so it is not closed by lexical guessing."""
    return update_thought_task(db_path, task_id, "dismissed", f"dismissed:{reason}")
