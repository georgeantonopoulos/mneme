from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import random
import re
import sqlite3
from pathlib import Path
from typing import Iterable

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
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"config": str(path), **payload}


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


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


def add_observation(conn, note_id, kind, text, source_path, score):
    oid = hashlib.sha1(f"{note_id}:{kind}:{text}".encode()).hexdigest()[:20]
    conn.execute("INSERT OR IGNORE INTO observations(id,note_id,kind,text,source_path,score,created_at) VALUES(?,?,?,?,?,?,?)", (oid, note_id, kind, text[:1000], source_path, score, now_iso()))


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


def ingest_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, rebuild: bool = True, follow_symlinks: bool = False) -> dict:
    hints = hints or DEFAULT_HINTS; db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path); init_db(conn)
    if rebuild:
        # Privacy-first default: avoid stale private content when a DB is reused
        # with a different or sanitized vault.
        conn.executescript("DELETE FROM thoughts; DELETE FROM observations; DELETE FROM edge_debug_log; DELETE FROM edges; DELETE FROM nodes;")
    else:
        conn.execute("DELETE FROM observations")
    notes=edges=observations=0
    for index, path in enumerate(iter_markdown(vault, {".git", "node_modules"}, follow_symlinks=follow_symlinks)):
        if max_notes is not None and index >= max_notes: break
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip(): continue
        rel = str(path.relative_to(vault)); nid = upsert_node(conn, note_type(path), title_from_text(path, text), rel, metadata={"path":rel,"chars":len(text)}); notes += 1
        research_payload = research_payload_from_note(text)
        if research_payload:
            edges += len(write_research_edges(conn, rel, research_payload, actor="ingest"))
        for target in sorted(set(WIKILINK_RE.findall(text))):
            tid=upsert_node(conn,"wikilink",target.strip(),None,0.8); upsert_edge(conn,nid,tid,"links_to",rel,f"[[{target.strip()}]]",0.9); edges += 1
        for _, heading in HEADING_RE.findall(text):
            if 2 < len(heading) < 100:
                hid=upsert_node(conn,"heading",heading.strip(),rel,0.7); upsert_edge(conn,nid,hid,"has_heading",rel,heading.strip(),0.7); edges += 1
        for email in sorted(set(EMAIL_RE.findall(text))):
            eid=upsert_node(conn,"email",email,rel,0.9); upsert_edge(conn,nid,eid,"mentions_email",rel,email,0.9); edges += 1
        evidence=[]
        for m in TASK_RE.finditer(text):
            done=m.group(1).lower()=="x"; evidence.append(("done" if done else "blocked",m.group(2).strip(),3.0 if not done else 1.5))
        for m in BULLET_RE.finditer(text):
            body=re.sub(r"\s+"," ",m.group(1).strip())
            if re.match(r"^\[[ xX]\]\s+", body):
                continue
            if 8 <= len(body) <= 350:
                k,s=observation_score(body,hints)
                if s >= 3 or k in {"blocked","risk"}: evidence.append((k,body,s))
        for kind, body, score in evidence[:40]:
            add_observation(conn,nid,kind,body,rel,score); observations += 1
            oid=upsert_node(conn,"observation",body[:90],rel,min(1.0,score/6),{"kind":kind}); upsert_edge(conn,nid,oid,f"has_{kind}",rel,body,min(1.0,score/6)); edges += 1
            for date_text in DATE_RE.findall(body):
                did=upsert_node(conn,"date",date_text,rel,0.75); upsert_edge(conn,oid,did,"mentions_date",rel,body,0.75); edges += 1
    conn.commit(); counts=dict(conn.execute("SELECT 'nodes', count(*) FROM nodes UNION ALL SELECT 'edges', count(*) FROM edges UNION ALL SELECT 'observations', count(*) FROM observations").fetchall()); conn.close()
    return {"notes_read":notes,"edges_added":edges,"observations_added":observations,**counts,"db":str(db_path)}


def update_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, follow_symlinks: bool = False) -> dict:
    """Synchronize graph tables from the current vault while preserving generated thoughts.

    This is safer than ``--append`` for day-to-day updates because deleted or renamed
    notes do not leave stale nodes/edges behind, but the thought history remains.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.executescript("DELETE FROM observations; DELETE FROM edge_debug_log; DELETE FROM edges; DELETE FROM nodes;")
    conn.commit()
    conn.close()
    stats = ingest_vault(vault, db_path, hints, max_notes, rebuild=False, follow_symlinks=follow_symlinks)
    stats["mode"] = "update"
    stats["preserved"] = ["thoughts"]
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


def observations_for_seed(db_path: Path, seed_id: str, limit: int = 4):
    conn=sqlite3.connect(db_path); rows=conn.execute("SELECT text FROM observations WHERE note_id=? ORDER BY score DESC LIMIT ?",(seed_id,limit)).fetchall(); conn.close(); return [r[0] for r in rows]


def _node_by_id(conn: sqlite3.Connection, node_id: str) -> dict:
    node = get_node(conn, node_id)
    return node or {"id": node_id, "type": "unknown", "name": node_id, "source_path": None, "metadata": {}}


def _candidate_reasons(kind: str, text: str, score: float, hints: list[str]) -> tuple[float, list[str]]:
    low = text.lower(); reasons=[]; total = float(score)
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
    candidates=[]
    for note_id, kind, text, source_path, base_score, name, ntype, updated_at in rows:
        score, reasons = _candidate_reasons(kind, text, base_score, hints)
        if note_id in recent:
            score -= 3; reasons.append("recently surfaced penalty")
        if ntype in {"project", "finance", "event", "person"}:
            score += 1.5; reasons.append(f"important {ntype} note")
        path = _path_from_observation(conn, note_id, text, hops)
        candidates.append({
            "score": round(score, 2),
            "seed": {"id": note_id, "name": name, "type": ntype, "source_path": source_path},
            "observation": {"kind": kind, "text": text, "source_path": source_path, "score": base_score},
            "evidence": [text],
            "reasons": reasons,
            "path": path,
        })
    conn.close()
    candidates.sort(key=lambda c: (-c["score"], c["seed"]["name"].lower()))
    return candidates[:limit]


def _evidence_seed(obs: list[str]) -> str:
    return (obs[0] if obs else "").strip()


def _path_chain(path: list[dict], limit: int = 5) -> str:
    return " → ".join(n.get("name", "?") for n in path[:limit])


def _reasoned_next(prefix: str, evidence: str, fallback: str) -> str:
    if evidence:
        return f"{prefix} Evidence seed: {evidence[:170]}"
    return fallback


def generate_thought(db_path: Path, path, candidate: dict | None = None):
    seed=path[0]; names=[n.get("name","?") for n in path]; obs=(candidate.get("evidence", []) if candidate else observations_for_seed(db_path, seed["id"], 4)); low=" ".join(names+obs).lower()
    why_now = "; ".join(candidate.get("reasons", [])[:3]) if candidate else "weighted random graph traversal surfaced this path"
    chain = _path_chain(path)
    evidence = _evidence_seed(obs)
    if any(w in low for w in ["blocked","needs","awaiting","unresolved","todo","follow up","waiting"]):
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
    return {"title":title,"insight":insight,"action":action,"path":path,"observations":obs,"evidence":obs,"why_now":why_now,"score": candidate.get("score", 0) if candidate else 0}


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
    conn=sqlite3.connect(db_path); tid=hashlib.sha1((thought["title"]+json.dumps([n["id"] for n in thought["path"]])+now_iso()).encode()).hexdigest()[:16]
    conn.execute("INSERT INTO thoughts(id,seed_id,path_json,title,insight,action,image_path,created_at) VALUES(?,?,?,?,?,?,?,?)",(tid,thought["path"][0].get("id"),json.dumps(thought["path"],ensure_ascii=False),thought["title"],thought["insight"],thought["action"],image_path,now_iso()))
    conn.commit(); conn.close(); return tid
