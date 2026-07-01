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

from .brain import brain_label_matches
from .consolidate import retrieval_cluster_matches
from .contract import (
    deterministic_ingest_status as contract_deterministic_ingest_status,
    enforce_edge_write,
    truth_policy_for_edge,
)
from .hierarchy import ensure_hierarchy_schema, get_subtree_node_ids, normalize_path
from .retrieval import score_observation_candidate
from .world_model.schema import delete_world_model_source, ensure_world_model_schema
from .world_model.state import upsert_assertion

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
    "correction": ["correction", "corrected", "fix:", "incorrect", "wrong:", "misleading", "updated:", "superseded"],
}
DEFAULT_HINTS = ["deadline", "project", "invoice", "lease", "tax", "school", "move", "certification", "payment"]
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mneme" / "config.json"
THOUGHT_STATUSES = {"open", "acted", "resolved", "learned", "dismissed"}
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
        "next": "Run `mneme update`, then `mneme retrieve` or `mneme surface` for agent context; use `mneme thought` when you need a rendered card." if ok else "Fix failed checks, or rerun `mneme init --force` with correct paths.",
    }


def stable_id(kind: str, name: str) -> str:
    return hashlib.sha1(f"{kind}:{name.lower()}".encode()).hexdigest()[:16]


def node_identity_name(kind: str, name: str, source_path: str | None = None) -> str:
    if source_path:
        return f"{source_path}:{name}"
    return name


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
    CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,source_path TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confidence REAL DEFAULT 1.0,path TEXT DEFAULT NULL,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS relationship_types(id TEXT PRIMARY KEY,label TEXT NOT NULL,inverse_id TEXT,category TEXT NOT NULL,domain_type TEXT DEFAULT 'any',range_type TEXT DEFAULT 'any',description TEXT DEFAULT '',requires_validation INTEGER DEFAULT 1,symmetric INTEGER DEFAULT 0,transitive INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,src_id TEXT NOT NULL,dst_id TEXT NOT NULL,relation TEXT NOT NULL,source_path TEXT,confidence REAL DEFAULT 1.0,evidence_text TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT DEFAULT 'active',strength REAL DEFAULT 1.0,source_type TEXT DEFAULT 'vault',metadata_json TEXT DEFAULT '{}',cross_boundary INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS path_index(path TEXT NOT NULL,node_id TEXT NOT NULL,depth INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(path,node_id));
    CREATE TABLE IF NOT EXISTS edge_debug_log(id TEXT PRIMARY KEY,edge_id TEXT NOT NULL,event TEXT NOT NULL,actor TEXT NOT NULL,thinking_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sense_events(id TEXT PRIMARY KEY,sense_id TEXT NOT NULL,sense_type TEXT NOT NULL,source_id TEXT NOT NULL,source_uri TEXT,event_type TEXT,title TEXT,text_hash TEXT,observed_at TEXT,ingested_at TEXT,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,note_id TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,source_path TEXT NOT NULL,score REAL DEFAULT 0,created_at TEXT NOT NULL,sense_event_id TEXT);
    CREATE TABLE IF NOT EXISTS thoughts(id TEXT PRIMARY KEY,seed_id TEXT,path_json TEXT NOT NULL,title TEXT NOT NULL,insight TEXT NOT NULL,action TEXT,image_path TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thought_candidates(id TEXT PRIMARY KEY,seed_id TEXT,seed_observation_id TEXT,activation_score REAL DEFAULT 0,why_now_json TEXT DEFAULT '{}',suggested_action TEXT,action_type TEXT,status TEXT DEFAULT 'candidate',surfaced_count INTEGER DEFAULT 0,last_surfaced_at TEXT,cooldown_until TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thought_feedback(id TEXT PRIMARY KEY,thought_id TEXT NOT NULL,feedback_type TEXT NOT NULL,reason TEXT,strength_delta REAL DEFAULT 0,cooldown_until TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS meditations(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,completed_at TEXT,model TEXT,seed_strategy TEXT,status TEXT,final_summary TEXT,final_score REAL,surfaced_thought_id TEXT,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS meditation_iterations(id TEXT PRIMARY KEY,meditation_id TEXT NOT NULL,iteration_index INTEGER NOT NULL,prompt TEXT,output_json TEXT,hypothesis TEXT,supporting_evidence_json TEXT,contradicting_evidence_json TEXT,next_question TEXT,score REAL,decision TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS hypotheses(id TEXT PRIMARY KEY,meditation_id TEXT,claim TEXT NOT NULL,entities_json TEXT,relation TEXT,confidence REAL,novelty REAL,usefulness REAL,evidence_count INTEGER,contradiction_count INTEGER,status TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS thought_fingerprints(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE,topic_entities_json TEXT,last_seen_at TEXT,surfaced_count INTEGER DEFAULT 0,dismissed_count INTEGER DEFAULT 0,accepted_count INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
    CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
    CREATE INDEX IF NOT EXISTS idx_edge_debug_edge ON edge_debug_log(edge_id);
    CREATE INDEX IF NOT EXISTS idx_obs_note ON observations(note_id);
    CREATE INDEX IF NOT EXISTS idx_obs_sense_event ON observations(sense_event_id);
    CREATE INDEX IF NOT EXISTS idx_path_index_prefix ON path_index(path);
    CREATE INDEX IF NOT EXISTS idx_path_index_node ON path_index(node_id);
    """)
    for ddl in [
        "ALTER TABLE nodes ADD COLUMN path TEXT DEFAULT NULL",
        "ALTER TABLE edges ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE edges ADD COLUMN strength REAL DEFAULT 1.0",
        "ALTER TABLE edges ADD COLUMN source_type TEXT DEFAULT 'vault'",
        "ALTER TABLE edges ADD COLUMN metadata_json TEXT DEFAULT '{}'",
        "ALTER TABLE edges ADD COLUMN cross_boundary INTEGER DEFAULT 0",
        "ALTER TABLE observations ADD COLUMN sense_event_id TEXT",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    seed_relationship_types(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_status ON edges(status)")


def upsert_node(conn, kind, name, source_path=None, confidence=1.0, metadata=None):
    nid = stable_id(kind, node_identity_name(kind, name, source_path))
    ts = now_iso()
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
    # Include a uuid4 suffix to guarantee uniqueness even when ts collides
    event_id = hashlib.sha1(f"{edge_id}:{event}:{actor}:{payload}:{ts}:{uuid.uuid4().hex}".encode()).hexdigest()[:20]
    conn.execute(
        "INSERT OR IGNORE INTO edge_debug_log(id,edge_id,event,actor,thinking_json,created_at) VALUES(?,?,?,?,?,?)",
        (event_id, edge_id, event, actor, payload, ts),
    )
    return event_id


def deterministic_ingest_status(relation: str) -> str:
    """Default status for deterministic vault parsing."""
    return contract_deterministic_ingest_status(relation)


def extract_observations(text: str, hints: list[str] | None = None) -> list[tuple[str, str, float]]:
    hints = hints or DEFAULT_HINTS
    observations: list[tuple[str, str, float]] = []
    for match in TASK_RE.finditer(text or ""):
        done, body = match.groups()
        low = body.lower()
        kind = "done" if done.lower() == "x" else "blocked"
        if any(word in low for word in STATUS_WORDS["risk"]):
            kind = "risk"
        if any(word in low for word in STATUS_WORDS["correction"]):
            kind = "correction"
        score = 9.0 if kind == "correction" else 6.0 if kind == "blocked" else 5.0 if kind == "risk" else 2.0
        if any(hint.lower() in low for hint in hints):
            score += 2.0
        observations.append((kind, body.strip(), score))
    for match in BULLET_RE.finditer(text or ""):
        body = match.group(1).strip()
        low = body.lower()
        if body.startswith("["):
            continue
        kind = None
        if any(word in low for word in STATUS_WORDS["correction"]):
            kind = "correction"
        elif any(word in low for word in STATUS_WORDS["risk"]):
            kind = "risk"
        elif any(word in low for word in STATUS_WORDS["blocked"]):
            kind = "blocked"
        if kind:
            score = 9.0 if kind == "correction" else 5.0 + (2.0 if any(hint.lower() in low for hint in hints) else 0.0)
            observations.append((kind, body, score))
    if not observations and text.strip():
        low = text.lower()
        if any(word in low for word in STATUS_WORDS["blocked"] + STATUS_WORDS["risk"] + ["need "]):
            observations.append(("blocked", text.strip()[:500], 4.0))
    return observations


def upsert_edge(conn, src, dst, relation, source_path, evidence="", confidence=1.0, status="active", strength=None, source_type="vault", metadata=None):
    eid = hashlib.sha1(f"{src}:{relation}:{dst}:{source_path}:{evidence[:80]}".encode()).hexdigest()[:20]; ts = now_iso()
    metadata = dict(metadata or {})
    decision = enforce_edge_write(
        relation=relation,
        requested_status=status,
        evidence_text=evidence,
        confidence=float(confidence or 0.0),
        source_type=source_type,
        metadata=metadata,
        requested_strength=strength,
    )
    if decision.status != "killed":
        tombstone = conn.execute(
            "SELECT id FROM edges WHERE src_id=? AND dst_id=? AND relation=? AND status='killed' LIMIT 1",
            (src, dst, relation),
        ).fetchone()
        if tombstone:
            log_edge_event(
                conn,
                tombstone[0],
                "blocked_recreation",
                "contract",
                {
                    "attempted_edge_id": eid,
                    "source_path": source_path,
                    "evidence_text": evidence[:500] if evidence else "",
                    "requested_status": status,
                    "contract": decision.contract_payload,
                },
            )
            return tombstone[0]
    status = decision.status
    strength = decision.strength
    metadata["contract"] = decision.contract_payload
    inserted = conn.execute("SELECT 1 FROM edges WHERE id=?", (eid,)).fetchone() is None
    conn.execute("""INSERT INTO edges(id,src_id,dst_id,relation,source_path,confidence,evidence_text,created_at,updated_at,status,strength,source_type,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, confidence=max(edges.confidence, excluded.confidence), strength=max(edges.strength, excluded.strength), status=excluded.status, source_type=excluded.source_type, metadata_json=excluded.metadata_json""",
    (eid, src, dst, relation, source_path, confidence, evidence[:500], ts, ts, status, strength, source_type, json.dumps(metadata or {}, ensure_ascii=False)))
    if inserted:
        log_edge_event(conn, eid, "created", "ingest", edge_creation_thinking(relation, source_path, evidence, confidence))
    if decision.reasons and decision.status != "killed":
        log_edge_event(conn, eid, "contract_enforced", "contract", decision.contract_payload)
    return eid


def add_observation(conn, note_id, kind, text, source_path, score, sense_event_id: str | None = None):
    oid = hashlib.sha1(f"{note_id}:{kind}:{text}".encode()).hexdigest()[:20]
    conn.execute(
        "INSERT OR IGNORE INTO observations(id,note_id,kind,text,source_path,score,created_at,sense_event_id) VALUES(?,?,?,?,?,?,?,?)",
        (oid, note_id, kind, text[:1000], source_path, score, now_iso(), sense_event_id),
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
            kind = candidate; score += {"blocked":3.0,"risk":2.5,"done":1.5,"correction":8.0}.get(candidate,1.0)
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
    ensure_world_model_schema(conn)
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
        assertion_result = None
        if status == "active":
            assertion_result = upsert_assertion(
                conn,
                {**claim, "predicate": relation, "object": obj, "metadata": {**(claim.get("metadata") or {}), "research_resolution": True}},
                source_path=note_path,
                source_edge_id=edge_id,
                subject_node_id=src,
                valid_from=payload.get("date"),
                active=True,
            )
        created.append({
            "id": edge_id,
            "src": subject,
            "predicate": relation,
            "dst": obj,
            "status": status,
            "strength": strength,
            "confidence": confidence,
            "assertion_id": assertion_result.get("id") if assertion_result else None,
        })
    return created


def write_research_resolution(vault: Path, db_path: Path, payload: dict | str, active_threshold: float = 0.9) -> dict:
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert isinstance(payload, dict)
    date = payload.get("date") or dt.datetime.now(dt.timezone.utc).date().isoformat()
    note_path = payload.get("note_path") or f"Sources/{date}_{slugify(payload.get('slug') or payload.get('title') or '')}-resolution.md"
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
        conn.execute(f"DELETE FROM path_index WHERE node_id NOT IN ({node_placeholders})", tuple(preserved_nodes))
    else:
        conn.execute("DELETE FROM nodes")
        conn.execute("DELETE FROM path_index")
    return {
        "preserved_active_edges": conn.execute("SELECT count(*) FROM edges WHERE status='active'").fetchone()[0],
        "preserved_killed_edges": conn.execute("SELECT count(*) FROM edges WHERE status='killed'").fetchone()[0],
    }


def ingest_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, rebuild: bool = True, follow_symlinks: bool = False) -> dict:
    hints = hints or DEFAULT_HINTS; db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path); init_db(conn)
    preserved = {}
    if rebuild:
        preserved = clear_graph_for_rebuild(conn, preserve_thoughts=False)
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
            tid=upsert_node(conn,"wikilink",target.strip(),None,0.8); upsert_edge(conn,nid,tid,"links_to",rel,f"[[{target.strip()}]]",0.9,status=deterministic_ingest_status("links_to")); edges += 1
        for _, heading in HEADING_RE.findall(text):
            if 2 < len(heading) < 100:
                hid=upsert_node(conn,"heading",heading.strip(),rel,0.7); upsert_edge(conn,nid,hid,"has_heading",rel,heading.strip(),0.7,status=deterministic_ingest_status("has_heading")); edges += 1
        for email in sorted(set(EMAIL_RE.findall(text))):
            eid=upsert_node(conn,"email",email,rel,0.9); upsert_edge(conn,nid,eid,"mentions_email",rel,email,0.9,status=deterministic_ingest_status("mentions_email")); edges += 1
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
            oid=upsert_node(conn,"observation",body[:90],rel,min(1.0,score/6),{"kind":kind}); upsert_edge(conn,nid,oid,f"has_{kind}",rel,body,min(1.0,score/6),status=deterministic_ingest_status(f"has_{kind}")); edges += 1
            for date_text in DATE_RE.findall(body):
                did=upsert_node(conn,"date",date_text,rel,0.75); upsert_edge(conn,oid,did,"mentions_date",rel,body,0.75,status=deterministic_ingest_status("mentions_date")); edges += 1
    conn.commit(); counts=dict(conn.execute("SELECT 'nodes', count(*) FROM nodes UNION ALL SELECT 'edges', count(*) FROM edges UNION ALL SELECT 'observations', count(*) FROM observations").fetchall()); conn.close()
    return {"notes_read":notes,"edges_added":edges,"observations_added":observations,**counts,**preserved,"db":str(db_path)}


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
    rows = conn.execute(
        f"SELECT id,relation,evidence_text,confidence,strength,source_type,metadata_json FROM edges WHERE {where}"
    ).fetchall()
    total = len(rows)
    if not dry_run:
        activated = 0
        for edge_id, relation, evidence, confidence, current_strength, source_type, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            decision = enforce_edge_write(
                relation=relation,
                requested_status="active",
                evidence_text=evidence,
                confidence=float(confidence or 0.0),
                source_type=source_type or "vault",
                metadata=metadata,
                requested_strength=current_strength,
            )
            metadata["contract"] = decision.contract_payload
            conn.execute(
                "UPDATE edges SET status=?, strength=?, updated_at=?, metadata_json=? WHERE id=? AND status!='killed'",
                (decision.status, decision.strength, now_iso(), json.dumps(metadata, ensure_ascii=False), edge_id),
            )
            if decision.status == "active":
                activated += 1
            if decision.reasons:
                log_edge_event(conn, edge_id, "contract_enforced", "contract", decision.contract_payload)
        conn.commit()
    else:
        activated = 0
    counts = dict(conn.execute("SELECT status,count(*) FROM edges GROUP BY status").fetchall())
    conn.close()
    return {"mode": mode, "dry_run": dry_run, "would_activate": total, "activated": activated, "edges_by_status": counts, "db": str(db_path)}


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


def observations_for_seed(db_path: Path, seed_id: str, limit: int = 4):
    conn=sqlite3.connect(db_path); rows=conn.execute("SELECT text FROM observations WHERE note_id=? ORDER BY score DESC LIMIT ?",(seed_id,limit)).fetchall(); conn.close(); return [r[0] for r in rows]


def _node_by_id(conn: sqlite3.Connection, node_id: str) -> dict:
    node = get_node(conn, node_id)
    return node or {"id": node_id, "type": "unknown", "name": node_id, "source_path": None, "metadata": {}}


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


def _candidate_reasons(kind: str, text: str, score: float, hints: list[str]) -> tuple[float, list[str]]:
    low = text.lower()
    reasons: list[str] = []
    total = float(score or 0)
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


def list_thought_candidates(db_path: Path, limit: int = 5, hops: int = 5, hints: list[str] | None = None) -> list[dict]:
    return _scored_thought_candidates(db_path, limit=limit, hops=hops, hints=hints, include_skipped=False)


def _scored_thought_candidates(db_path: Path, limit: int = 5, hops: int = 5, hints: list[str] | None = None, include_skipped: bool = False) -> list[dict]:
    hints = hints or DEFAULT_HINTS
    conn = sqlite3.connect(db_path)
    recent = {r[0] for r in conn.execute("SELECT seed_id FROM thoughts ORDER BY created_at DESC LIMIT 20").fetchall() if r[0]}
    rows = conn.execute(
        """SELECT o.note_id,o.kind,o.text,o.source_path,o.score,o.created_at,n.name,n.type,n.updated_at
           FROM observations o JOIN nodes n ON n.id=o.note_id
           ORDER BY o.score DESC,o.created_at DESC LIMIT 200"""
    ).fetchall()
    candidates=[]
    for note_id, kind, text, source_path, base_score, observation_created_at, name, ntype, updated_at in rows:
        breakdown = score_observation_candidate(
            kind=kind,
            text=text,
            base_score=base_score,
            hints=hints,
            note_type=ntype,
            note_name=name,
            source_path=source_path,
            recently_surfaced=note_id in recent,
            observation_created_at=observation_created_at,
            node_updated_at=updated_at,
        )
        if breakdown.skip_reasons and not include_skipped:
            continue
        path = _path_from_observation(conn, note_id, text, hops)
        candidates.append({
            "score": round(breakdown.total, 2),
            "seed": {"id": note_id, "name": name, "type": ntype, "source_path": source_path},
            "observation": {"kind": kind, "text": text, "source_path": source_path, "score": base_score},
            "evidence": [text],
            "reasons": breakdown.reasons,
            "score_breakdown": breakdown.to_dict(),
            "skip_reasons": breakdown.skip_reasons,
            "path": path,
        })
    conn.close()
    candidates.sort(key=lambda c: (-c["score"], c["seed"]["name"].lower()))
    return candidates[:limit]


def debug_candidates(db_path: Path, limit: int = 20, hops: int = 5, hints: list[str] | None = None, include_skipped: bool = False) -> dict:
    candidates = _scored_thought_candidates(db_path, limit=limit, hops=hops, hints=hints, include_skipped=include_skipped)
    return {
        "db": str(db_path),
        "include_skipped": include_skipped,
        "count": len(candidates),
        "candidates": candidates,
        "empty_reason": None if candidates else "No observations scored above the surfacing threshold. Re-run with --include-skipped to inspect suppressed candidates.",
    }


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.I)


def _query_tokens(prompt: str) -> set[str]:
    stop = {"about", "after", "again", "agent", "could", "from", "have", "into", "make", "memory", "need", "next", "should", "surface", "that", "this", "what", "when", "where", "with", "work"}
    return {token.lower() for token in TOKEN_RE.findall(prompt or "") if token.lower() not in stop}


def _lexical_overlap(tokens: set[str], *values: str | None) -> tuple[int, list[str]]:
    haystack = " ".join(value or "" for value in values).lower()
    matched = sorted(token for token in tokens if token in haystack)
    return len(matched), matched


def _merge_rows_by_id(*row_sets: Iterable[tuple]) -> list[tuple]:
    merged: dict[str, tuple] = {}
    for rows in row_sets:
        for row in rows:
            if row and row[0] not in merged:
                merged[row[0]] = row
    return list(merged.values())


def _like_clause(tokens: set[str], columns: list[str]) -> tuple[str, list[str]]:
    if not tokens:
        return "0", []
    clauses: list[str] = []
    params: list[str] = []
    for token in sorted(tokens):
        pattern = f"%{token.lower()}%"
        for column in columns:
            clauses.append(f"lower(COALESCE({column},'')) LIKE ?")
            params.append(pattern)
    return " OR ".join(clauses), params


def _rrf_score(ranks: Iterable[int | None], k: int = 60) -> float:
    return sum(1.0 / (k + rank) for rank in ranks if rank is not None)


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {item_id: index + 1 for index, (item_id, _score) in enumerate(ordered) if _score > 0}


def _memory_frequency_by_source(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source_path, count in conn.execute("SELECT source_path,COUNT(*) FROM observations GROUP BY source_path"):
        if source_path:
            counts[str(source_path)] = counts.get(str(source_path), 0) + int(count or 0)
    for source_path, count in conn.execute("SELECT source_path,COUNT(*) FROM edges WHERE COALESCE(status,'candidate') != 'killed' GROUP BY source_path"):
        if source_path:
            counts[str(source_path)] = counts.get(str(source_path), 0) + int(count or 0)
    return counts


def _query_seed_nodes(conn: sqlite3.Connection, tokens: set[str], limit: int = 24) -> set[str]:
    if not tokens:
        return set()
    where, params = _like_clause(tokens, ["name", "source_path"])
    rows = conn.execute(
        f"SELECT id,name,source_path FROM nodes WHERE {where} ORDER BY updated_at DESC,name LIMIT ?",
        params + [limit],
    ).fetchall()
    return {row[0] for row in rows}


def _resolve_query_paths(conn: sqlite3.Connection, tokens: set[str]) -> dict[str, float]:
    if not tokens:
        return {}
    ensure_hierarchy_schema(conn)
    normalized_tokens = {normalize_path(token) or token for token in tokens}
    scores: dict[str, float] = {}
    placeholders = ",".join("?" for _ in normalized_tokens)
    if placeholders:
        for path, count in conn.execute(
            f"""SELECT path,COUNT(*) FROM path_index
                WHERE path IN ({placeholders})
                GROUP BY path
                ORDER BY COUNT(*) DESC
                LIMIT 10""",
            tuple(sorted(normalized_tokens)),
        ).fetchall():
            segments = set(str(path).split("/"))
            scores[str(path)] = scores.get(str(path), 0.0) + float(count or 0) + len(segments & normalized_tokens) * 2.0
    where, params = _like_clause(tokens, ["name", "source_path", "path"])
    if where != "0":
        for path, name, source_path in conn.execute(
            f"""SELECT path,name,source_path FROM nodes
                WHERE path IS NOT NULL AND path != '' AND ({where})
                ORDER BY updated_at DESC,name
                LIMIT 24""",
            params,
        ).fetchall():
            if not path:
                continue
            overlap, _matched = _lexical_overlap(tokens, path, name, source_path)
            if overlap:
                scores[str(path)] = scores.get(str(path), 0.0) + float(overlap * 3)
                parent = str(path).rsplit("/", 1)[0] if "/" in str(path) else str(path)
                parent_overlap, _parent_matched = _lexical_overlap(tokens, parent)
                if parent_overlap:
                    scores[parent] = scores.get(parent, 0.0) + float(parent_overlap)
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:10])


def _ids_clause(column: str, node_ids: set[str]) -> tuple[str, list[str]]:
    if not node_ids:
        return "0", []
    placeholders = ",".join("?" for _ in node_ids)
    return f"{column} IN ({placeholders})", sorted(node_ids)


def _path_proximity_scores(conn: sqlite3.Connection, matched_paths: dict[str, float]) -> dict[str, float]:
    scores: dict[str, float] = {}
    if not matched_paths:
        return scores
    ensure_hierarchy_schema(conn)
    for path, relevance in matched_paths.items():
        normalized = normalize_path(path)
        if not normalized:
            continue
        base_depth = len(normalized.split("/"))
        for node_id, node_path in conn.execute(
            "SELECT id,path FROM nodes WHERE path IS NOT NULL AND (path=? OR path LIKE ?)",
            (normalized, normalized + "/%"),
        ).fetchall():
            depth_delta = max(0, len(str(node_path).split("/")) - base_depth)
            bonus = float(relevance) / (1.0 + depth_delta)
            scores[str(node_id)] = max(scores.get(str(node_id), 0.0), bonus)
    return scores


def _graph_distance_scores(conn: sqlite3.Connection, seed_nodes: set[str], max_hops: int = 2) -> dict[str, float]:
    if not seed_nodes:
        return {}
    scores: dict[str, float] = {node_id: 1.0 for node_id in seed_nodes}
    frontier = set(seed_nodes)
    seen = set(seed_nodes)
    for depth in range(1, max_hops + 1):
        placeholders = ",".join("?" for _ in frontier)
        if not placeholders:
            break
        rows = conn.execute(
            f"""SELECT id,src_id,dst_id,status,strength,confidence
                FROM edges
                WHERE COALESCE(status,'candidate') != 'killed'
                  AND (src_id IN ({placeholders}) OR dst_id IN ({placeholders}))""",
            tuple(frontier) + tuple(frontier),
        ).fetchall()
        next_frontier: set[str] = set()
        for edge_id, src_id, dst_id, status, strength, confidence in rows:
            status_factor = 1.0 if status == "active" else 0.55
            edge_score = (float(strength or 0) + float(confidence or 0)) * status_factor / depth
            scores[edge_id] = max(scores.get(edge_id, 0.0), edge_score)
            for node_id in (src_id, dst_id):
                scores[node_id] = max(scores.get(node_id, 0.0), edge_score * 0.85)
                if node_id not in seen:
                    seen.add(node_id)
                    next_frontier.add(node_id)
        frontier = next_frontier
    return scores


def _retrieval_signals(
    item_id: str,
    *,
    lexical_score: float,
    graph_score: float,
    memory_score: float,
    lexical_ranks: dict[str, int],
    graph_ranks: dict[str, int],
    memory_ranks: dict[str, int],
) -> dict:
    ranks = {
        "lexical": lexical_ranks.get(item_id),
        "graph": graph_ranks.get(item_id),
        "memory": memory_ranks.get(item_id),
    }
    return {
        "method": "hybrid_memory_graph_rrf",
        "rrf": round(_rrf_score(ranks.values()), 5),
        "ranks": ranks,
        "scores": {
            "lexical": round(lexical_score, 3),
            "graph": round(graph_score, 3),
            "memory": round(memory_score, 3),
        },
    }


def _memory_boost(memory_score: float, *, overlap: int, graph_score: float, has_context_signal: bool) -> float:
    if overlap <= 0 and graph_score <= 0 and not has_context_signal:
        return 0.0
    return min(1.2, memory_score * 0.08)


def _hybrid_rrf_boost(hybrid: dict, *, overlap: int, graph_score: float, has_context_signal: bool) -> float:
    ranks = (hybrid.get("ranks") or {}).copy()
    if overlap <= 0 and graph_score <= 0 and not has_context_signal:
        ranks["memory"] = None
    return _rrf_score(ranks.values()) * 25.0


def _retrieval_source_authority(source_path: str | None, source_type: str | None = None) -> float:
    source_type_norm = (source_type or "").strip().lower()
    path = (source_path or "").strip().lower()
    if source_type_norm == "user_confirmed":
        return 1.3
    if path.startswith(("gws://", "email://")):
        return 1.4
    normalized = path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if any(part in {"cron", "logs", "out", "debug", "heartbeat"} for part in parts):
        return 0.08
    if "memory" in parts:
        return 0.25
    if any(part in {"daily", "archive"} for part in parts):
        return 0.15
    if any(part in {"projects", "people", "events", "vendors"} for part in parts):
        return 1.2
    return 1.0


def _retrieval_staleness(text: str | None, source_path: str | None) -> float:
    return _meditation_staleness_penalty(text or "", source_path)


def _retrieval_edge_source_authority(source_type: str | None) -> float:
    source_type_norm = (source_type or "").strip().lower()
    if source_type_norm == "user_confirmed":
        return 1.4
    if source_type_norm in {"gws", "email", "calendar"}:
        return 1.3
    if source_type_norm in {"sense", "extraction"}:
        return 1.0
    if source_type_norm in {"", "candidate"}:
        return 0.7
    return 1.0


def _select_retrieval_items(items: list[dict], *, budget: int, max_items: int, skipped: list[dict], per_source_limit: int = 2) -> tuple[list[dict], int]:
    selected: list[dict] = []
    selected_ids: set[str] = set()
    source_counts: dict[str, int] = {}
    used = 0

    def try_add(item: dict, *, enforce_source_limit: bool) -> bool:
        nonlocal used
        item_id = str(item.get("id") or "")
        if item_id in selected_ids:
            return False
        source_path = item.get("source_path") or ""
        if enforce_source_limit and source_counts.get(source_path, 0) >= per_source_limit:
            return False
        cost = len(item.get("snippet") or "") + len(item.get("title") or "")
        if selected and (used + cost) > budget:
            skipped.append({"kind": item["kind"], "id": item["id"], "source_path": item.get("source_path"), "skip_reasons": ["budget limit"], "score": item.get("score")})
            return False
        selected.append(item)
        selected_ids.add(item_id)
        source_counts[source_path] = source_counts.get(source_path, 0) + 1
        used += cost
        return True

    for item in items:
        try_add(item, enforce_source_limit=True)
        if len(selected) >= max_items:
            return selected, used

    for item in items:
        try_add(item, enforce_source_limit=False)
        if len(selected) >= max_items:
            break
    return selected, used


def _edge_truth_policy(status: str | None, relation: str) -> str:
    return truth_policy_for_edge(status=status, relation=relation)


def retrieve_context(db_path: Path, prompt: str, budget: int = 2500, max_items: int = 8, hints: list[str] | None = None, include_candidates: bool = True) -> dict:
    hints = hints or DEFAULT_HINTS
    tokens = _query_tokens(prompt)
    if not tokens:
        tokens = _query_tokens(" ".join(hints))
    min_overlap = 2 if len(tokens) >= 3 else 1
    conn = sqlite3.connect(db_path)
    ensure_hierarchy_schema(conn)
    matched_paths = _resolve_query_paths(conn, tokens)
    path_node_ids: set[str] = set()
    for path in matched_paths:
        path_node_ids.update(get_subtree_node_ids(conn, path))
    path_filter_active = bool(path_node_ids)
    path_proximity_scores = _path_proximity_scores(conn, matched_paths)
    obs_path_clause, obs_path_params = _ids_clause("n.id", path_node_ids)
    edge_src_clause, edge_src_params = _ids_clause("e.src_id", path_node_ids)
    edge_dst_clause, edge_dst_params = _ids_clause("e.dst_id", path_node_ids)
    edge_path_clause = f"(({edge_src_clause}) OR ({edge_dst_clause}) OR COALESCE(e.cross_boundary,0)=1)"
    edge_path_params = edge_src_params + edge_dst_params
    base_observation_rows = conn.execute(
        f"""SELECT o.id,o.note_id,o.kind,o.text,o.source_path,o.score,o.created_at,n.name,n.type,n.updated_at,n.path
           FROM observations o JOIN nodes n ON n.id=o.note_id
           {"WHERE " + obs_path_clause if path_filter_active else ""}
           ORDER BY o.score DESC,o.created_at DESC LIMIT 500""",
        obs_path_params if path_filter_active else [],
    ).fetchall()
    obs_where, obs_params = _like_clause(tokens, ["o.text", "o.source_path", "n.name"])
    lexical_observation_rows = conn.execute(
        f"""SELECT o.id,o.note_id,o.kind,o.text,o.source_path,o.score,o.created_at,n.name,n.type,n.updated_at,n.path
            FROM observations o JOIN nodes n ON n.id=o.note_id
            WHERE ({obs_where})
              {"AND (" + obs_path_clause + ")" if path_filter_active else ""}
            ORDER BY o.score DESC,o.created_at DESC LIMIT 700""",
        obs_params + (obs_path_params if path_filter_active else []),
    ).fetchall()
    observation_rows = _merge_rows_by_id(lexical_observation_rows, base_observation_rows)
    base_edge_rows = conn.execute(
        f"""SELECT e.id,e.relation,e.status,e.confidence,e.strength,e.source_type,e.source_path,e.evidence_text,COALESCE(e.cross_boundary,0),
                  s.id,s.type,s.name,s.source_path,s.path,
                  d.id,d.type,d.name,d.source_path,d.path
           FROM edges e
           JOIN nodes s ON s.id=e.src_id
           JOIN nodes d ON d.id=e.dst_id
           WHERE COALESCE(e.status,'candidate') != 'killed'
             {"AND " + edge_path_clause if path_filter_active else ""}
           ORDER BY e.strength DESC,e.confidence DESC,e.updated_at DESC LIMIT 800"""
        ,
        edge_path_params if path_filter_active else [],
    ).fetchall()
    edge_where, edge_params = _like_clause(tokens, ["e.relation", "e.evidence_text", "e.source_path", "s.name", "d.name"])
    lexical_edge_rows = conn.execute(
        f"""SELECT e.id,e.relation,e.status,e.confidence,e.strength,e.source_type,e.source_path,e.evidence_text,COALESCE(e.cross_boundary,0),
                  s.id,s.type,s.name,s.source_path,s.path,
                  d.id,d.type,d.name,d.source_path,d.path
            FROM edges e
            JOIN nodes s ON s.id=e.src_id
            JOIN nodes d ON d.id=e.dst_id
            WHERE COALESCE(e.status,'candidate') != 'killed'
              AND ({edge_where})
              {"AND " + edge_path_clause if path_filter_active else ""}
            ORDER BY e.strength DESC,e.confidence DESC,e.updated_at DESC LIMIT 900""",
        edge_params + (edge_path_params if path_filter_active else []),
    ).fetchall()
    edge_rows = _merge_rows_by_id(lexical_edge_rows, base_edge_rows)
    memory_counts = _memory_frequency_by_source(conn)
    query_seed_nodes = _query_seed_nodes(conn, tokens)
    graph_scores = _graph_distance_scores(conn, query_seed_nodes)
    lexical_scores: dict[str, float] = {}
    memory_scores: dict[str, float] = {}
    for obs_id, _note_id, _kind, text, source_path, _base_score, _created_at, note_name, _note_type, _updated_at, _node_path in observation_rows:
        overlap, _matched = _lexical_overlap(tokens, text, source_path, note_name)
        lexical_scores[obs_id] = float(overlap)
        memory_scores[obs_id] = float(memory_counts.get(source_path or "", 0))
    for edge_id, relation, _status, _confidence, _strength, _source_type, source_path, evidence_text, _cross_boundary, _src_id, _src_type, src_name, _src_path, _src_hpath, _dst_id, _dst_type, dst_name, _dst_path, _dst_hpath in edge_rows:
        overlap, _matched = _lexical_overlap(tokens, relation, evidence_text, source_path, src_name, dst_name)
        lexical_scores[edge_id] = float(overlap)
        memory_scores[edge_id] = float(memory_counts.get(source_path or "", 0))
    lexical_ranks = _rank_map(lexical_scores)
    graph_ranks = _rank_map(graph_scores)
    memory_ranks = _rank_map(memory_scores)
    has_direct_lexical_matches = any(score > 0 for score in lexical_scores.values())
    cluster_context = retrieval_cluster_matches(conn, prompt, limit=5)
    node_boosts = cluster_context.get("node_boosts", {})
    brain_context = brain_label_matches(conn, prompt, limit=16)
    brain_matches = brain_context.get("by_target", {})

    def brain_match(*keys: tuple[str, str]) -> dict | None:
        found = [brain_matches[key] for key in keys if key in brain_matches]
        if not found:
            return None
        return sorted(found, key=lambda item: -float(item.get("score", 0)))[0]

    def cluster_for_text(*values: str | None) -> dict | None:
        value_tokens = _query_tokens(" ".join(value or "" for value in values))
        best: dict | None = None
        best_score = 0
        for cluster in cluster_context.get("clusters", []):
            matched = set(cluster.get("matched_terms") or [])
            score = len(tokens & value_tokens & matched)
            if score > best_score:
                best = {
                    "run_id": cluster_context.get("run_id"),
                    "cluster_id": cluster.get("cluster_id"),
                    "cluster_score": cluster.get("score"),
                    "role": "text_match",
                    "matched_terms": sorted(tokens & value_tokens & matched),
                }
                best_score = score
        return best

    items: list[dict] = []
    skipped: list[dict] = []
    for obs_id, note_id, kind, text, source_path, base_score, created_at, note_name, note_type, updated_at, node_path in observation_rows:
        overlap, matched = _lexical_overlap(tokens, text, source_path, note_name)
        memory_score = memory_scores.get(obs_id, 0.0)
        path_bonus = path_proximity_scores.get(note_id, 0.0)
        graph_score = max(graph_scores.get(note_id, 0.0), path_bonus * 0.35)
        breakdown = score_observation_candidate(
            kind=kind,
            text=text,
            base_score=base_score,
            hints=hints,
            note_type=note_type,
            note_name=note_name,
            source_path=source_path,
            observation_created_at=created_at,
            node_updated_at=updated_at,
        )
        hybrid = _retrieval_signals(
            obs_id,
            lexical_score=float(overlap),
            graph_score=graph_score,
            memory_score=memory_score,
            lexical_ranks=lexical_ranks,
            graph_ranks=graph_ranks,
            memory_ranks=memory_ranks,
        )
        cluster = node_boosts.get(note_id) or cluster_for_text(note_name, source_path, text)
        obs_brain = brain_match(("node", note_id))
        has_context_signal = bool(cluster or obs_brain)
        score = breakdown.total + (overlap * 3.0) + min(4.0, graph_score * 1.5) + min(3.0, path_bonus) + _hybrid_rrf_boost(hybrid, overlap=overlap, graph_score=graph_score, has_context_signal=has_context_signal)
        if cluster:
            score += min(5.0, float(cluster.get("cluster_score", 0)) * 0.2)
        if obs_brain:
            score += min(4.0, float(obs_brain.get("score", 0)) * 0.35)
        score += _memory_boost(memory_score, overlap=overlap, graph_score=graph_score, has_context_signal=has_context_signal)
        raw_score = score
        source_authority = _retrieval_source_authority(source_path)
        staleness = _retrieval_staleness(text, source_path)
        score *= source_authority * staleness
        source_quality_score = float((breakdown.source_quality or {}).get("score") or 0.0)
        include_by_score = score >= 8 and (
            overlap > 0
            or has_context_signal
            or (not has_direct_lexical_matches and source_quality_score == 0 and breakdown.total >= 12)
        )
        if overlap < min_overlap and not include_by_score and not obs_brain:
            skipped.append({"kind": "observation", "id": obs_id, "source_path": source_path, "skip_reasons": [f"matched {overlap} prompt term(s); required {min_overlap}"], "score": round(score, 2)})
            continue
        item = {
            "kind": "observation",
            "id": obs_id,
            "title": note_name,
            "source_path": source_path,
            "snippet": text[:500],
            "score": round(score, 2),
            "matched_terms": matched,
            "status": "active_evidence",
            "truth_policy": "source_contained_observation",
            "score_breakdown": breakdown.to_dict(),
            "retrieval_signals": hybrid,
            "freshness": {
                "raw_score": round(raw_score, 3),
                "source_authority": source_authority,
                "staleness": staleness,
            },
            "memory": {
                "source_path": source_path,
                "mentions": int(memory_score),
                "kind": "source_memory",
            },
            "path": _path_from_observation(conn, note_id, text, hops=3),
        }
        if node_path:
            item["hierarchy_path"] = node_path
        if path_bonus:
            item["path_match"] = {"bonus": round(path_bonus, 3), "matched_paths": matched_paths}
        if cluster:
            item["cluster"] = cluster
        if obs_brain:
            item["brain_label"] = {key: obs_brain[key] for key in ("run_id", "target_type", "target_id", "labels", "matched_terms", "score")}
        if overlap >= min_overlap or include_by_score or obs_brain:
            items.append(item)
        else:
            skipped.append({"kind": "observation", "id": obs_id, "source_path": source_path, "skip_reasons": [f"matched {overlap} prompt term(s); required {min_overlap}"], "score": round(score, 2)})

    for edge_id, relation, status, confidence, strength, source_type, source_path, evidence_text, cross_boundary, src_id, src_type, src_name, src_path, src_hpath, dst_id, dst_type, dst_name, dst_path, dst_hpath in edge_rows:
        if status != "active" and not include_candidates:
            skipped.append({"kind": "edge", "id": edge_id, "source_path": source_path, "skip_reasons": ["candidate edge excluded"], "status": status})
            continue
        overlap, matched = _lexical_overlap(tokens, relation, evidence_text, source_path, src_name, dst_name)
        edge_brain = brain_match(("synapse", edge_id), ("node", src_id), ("node", dst_id), ("relationship", relation))
        path_bonus = max(path_proximity_scores.get(src_id, 0.0), path_proximity_scores.get(dst_id, 0.0))
        graph_score = max(graph_scores.get(edge_id, 0.0), path_bonus * 0.3)
        memory_score = memory_scores.get(edge_id, 0.0)
        hybrid = _retrieval_signals(
            edge_id,
            lexical_score=float(overlap),
            graph_score=graph_score,
            memory_score=memory_score,
            lexical_ranks=lexical_ranks,
            graph_ranks=graph_ranks,
            memory_ranks=memory_ranks,
        )
        include_by_graph = graph_score >= 0.5 or hybrid["rrf"] >= 0.02
        if overlap < min_overlap and not edge_brain and not include_by_graph:
            skipped.append({
                "kind": "edge",
                "id": edge_id,
                "source_path": source_path,
                "skip_reasons": [f"matched {overlap} prompt term(s); required {min_overlap}"],
                "status": status,
                "overlap": overlap,
                "min_overlap": min_overlap,
                "brain_match": False,
            })
            continue
        rel = relationship_type(relation)
        policy = _edge_truth_policy(status, relation)
        base = (float(confidence or 0) + float(strength or 0)) * 2.0
        edge_cluster = node_boosts.get(src_id) or node_boosts.get(dst_id)
        has_context_signal = bool(edge_cluster or edge_brain)
        score = base + overlap * 3.0 + min(4.0, graph_score * 1.5) + min(3.0, path_bonus) + _hybrid_rrf_boost(hybrid, overlap=overlap, graph_score=graph_score, has_context_signal=has_context_signal)
        if edge_cluster:
            score += min(4.0, float(edge_cluster.get("cluster_score", 0)) * 0.15)
        if edge_brain:
            score += min(4.0, float(edge_brain.get("score", 0)) * 0.3)
        score += _memory_boost(memory_score, overlap=overlap, graph_score=graph_score, has_context_signal=has_context_signal)
        if rel.get("category") in {"reference", "structure", "extraction"}:
            score -= 0.8
        if cross_boundary:
            score *= 1.5
        raw_score = score
        source_authority = _retrieval_source_authority(source_path, source_type)
        edge_source_authority = _retrieval_edge_source_authority(source_type)
        staleness = _retrieval_staleness(evidence_text, source_path)
        status_multiplier = 0.3 if status == "candidate" else 1.0
        score *= source_authority * edge_source_authority * staleness * status_multiplier
        items.append({
            "kind": "edge",
            "id": edge_id,
            "title": f"{src_name} {relation} {dst_name}",
            "source_path": source_path,
            "snippet": (evidence_text or "")[:500],
            "score": round(score, 2),
            "matched_terms": matched,
            "relation": relation,
            "relationship_type": rel,
            "status": status,
            "truth_policy": policy,
            "source_type": source_type,
            "retrieval_signals": hybrid,
            "score_breakdown": {
                "base": round(base, 3),
                "lexical": round(overlap * 3.0, 3),
                "graph": round(min(4.0, graph_score * 1.5), 3),
                "raw_score": round(raw_score, 3),
                "path": round(min(3.0, path_bonus), 3),
                "cross_boundary_multiplier": 1.5 if cross_boundary else 1.0,
                "source_authority": source_authority,
                "edge_source_authority": edge_source_authority,
                "staleness": staleness,
                "status_multiplier": status_multiplier,
            },
            "freshness": {
                "raw_score": round(raw_score, 3),
                "cross_boundary_multiplier": 1.5 if cross_boundary else 1.0,
                "source_authority": source_authority,
                "edge_source_authority": edge_source_authority,
                "staleness": staleness,
                "status_multiplier": status_multiplier,
            },
            "memory": {
                "source_path": source_path,
                "mentions": int(memory_score),
                "kind": "source_memory",
            },
            "cross_boundary": bool(cross_boundary),
            "src": {"id": src_id, "type": src_type, "name": src_name, "source_path": src_path, "hierarchy_path": src_hpath},
            "dst": {"id": dst_id, "type": dst_type, "name": dst_name, "source_path": dst_path, "hierarchy_path": dst_hpath},
        })
        if path_bonus:
            items[-1]["path_match"] = {"bonus": round(path_bonus, 3), "matched_paths": matched_paths}
        if status == "candidate":
            items[-1]["truth_policy_tags"] = ["candidate"]
        if edge_cluster:
            items[-1]["cluster"] = edge_cluster
        if edge_brain:
            items[-1]["brain_label"] = {key: edge_brain[key] for key in ("run_id", "target_type", "target_id", "labels", "matched_terms", "score")}

    conn.close()
    items.sort(key=lambda item: (-float(item.get("score", 0)), item.get("source_path") or "", item.get("title") or ""))
    selected, used = _select_retrieval_items(items, budget=budget, max_items=max_items, skipped=skipped)
    return {
        "prompt": prompt,
        "budget": budget,
        "used_budget": used,
        "max_items": max_items,
        "tokens": sorted(tokens),
        "clusters": cluster_context.get("clusters", []),
        "brain_labels": brain_context.get("matches", []),
        "retrieval": {
            "method": "hybrid_memory_graph_rrf",
            "signals": ["lexical", "graph", "memory"],
            "memory_term": "memory",
            "query_seed_nodes": sorted(query_seed_nodes),
            "matched_paths": matched_paths,
            "path_filter_active": path_filter_active,
            "path_node_count": len(path_node_ids),
        },
        "items": selected,
        "skipped": skipped[:50],
        "stats": {
            "candidate_items_considered": len(items),
            "items_returned": len(selected),
            "skipped_reported": min(len(skipped), 50),
        },
        "empty_reason": None if selected else "No prompt-relevant context survived scoring and budget limits.",
    }


def _surface_item_to_thought(db_path: Path, item: dict, prompt: str) -> dict:
    path = item.get("path") or []
    if not path and item.get("src") and item.get("dst"):
        path = [item["src"], item["dst"]]
    if not path:
        path = [{"id": item.get("id"), "type": item.get("kind", "unknown"), "name": item.get("title") or item.get("id"), "source_path": item.get("source_path")}]
    evidence = [item.get("snippet", "")] if item.get("snippet") else []
    reasons = []
    for key in ("matched_terms",):
        if item.get(key):
            reasons.append("matched: " + ", ".join(item[key][:5]))
    if item.get("cluster"):
        reasons.append(f"cluster {item['cluster'].get('cluster_id')} activated")
    if item.get("brain_label"):
        reasons.append("brain label activated: " + ", ".join(item["brain_label"].get("labels", [])[:3]))
    if item.get("truth_policy"):
        reasons.append(f"truth policy: {item['truth_policy']}")
    item_score = float(item.get("score") or 0)
    raw_score = float((item.get("freshness") or {}).get("raw_score") or item_score)
    candidate = {
        "score": max(item_score, raw_score),
        "evidence": evidence,
        "reasons": reasons,
    }
    thought = generate_thought(db_path, path, candidate)
    thought["surface"] = {
        "prompt": prompt,
        "kind": item.get("kind"),
        "source_id": item.get("id"),
        "source_path": item.get("source_path"),
        "score": item.get("score"),
        "matched_terms": item.get("matched_terms", []),
        "truth_policy": item.get("truth_policy"),
        "cluster": item.get("cluster"),
        "brain_label": item.get("brain_label"),
    }
    thought["suggested_actions"] = _suggest_surface_actions(item)
    return thought


def _suggest_surface_actions(item: dict) -> list[dict]:
    actions: list[dict] = []
    source_path = item.get("source_path")
    if source_path and str(source_path).startswith("mneme://"):
        actions.append({
            "type": "graph_memory_review",
            "source_path": source_path,
            "action": "keep_or_forget",
        })
    elif source_path and item.get("kind") == "observation":
        actions.append({
            "type": "vault_append_bullet",
            "path": source_path,
            "heading": "Next Actions",
            "bullet": f"Review surfaced memory: {item.get('title') or item.get('id')}",
        })
    if item.get("kind") == "edge" and item.get("status") == "candidate":
        actions.append({
            "type": "synapse_review",
            "edge_id": item.get("id"),
            "action": "validate_or_kill",
        })
    if not actions:
        actions.append({"type": "inspect", "source_path": source_path, "id": item.get("id")})
    return actions


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


def actionability_from_candidate(candidate: dict) -> tuple[float, list[str], list[str]]:
    observation = candidate.get("observation") or {}
    text = str(observation.get("text") or " ".join(candidate.get("evidence", [])))
    kind = str(observation.get("kind") or "fact")
    score = float(candidate.get("score") or candidate.get("base_score") or 0)
    factors: dict[str, float] = {"base": score}
    tags: list[str] = []
    reasons = list(candidate.get("reasons") or [])
    if kind == "blocked" or any(word in text.lower() for word in ["follow up", "needs", "waiting", "todo"]):
        score += 3.0; factors["open_loop"] = 3.0; tags.append("mneme:thought/open_loop")
    if kind == "risk" or any(word in text.lower() for word in ["deadline", "urgent", "due", "overdue"]):
        score += 2.5; factors["time_sensitive"] = 2.5; tags.append("mneme:thought/time_sensitive")
    if not tags:
        tags.append("mneme:thought/inspect")
    candidate["why_now"] = {"factors": factors, "reasons": reasons}
    return score, tags, reasons


def _topic_terms(text: str) -> set[str]:
    stop = {"about", "after", "again", "from", "need", "needs", "reply", "soon", "that", "this", "with"}
    return {token.lower() for token in re.findall(r"[a-z][a-z0-9-]{3,}", text or "", re.I) if token.lower() not in stop}


def _candidate_source_provenance(conn: sqlite3.Connection, observation_id: str | None, source_path: str | None) -> dict:
    if observation_id:
        row = conn.execute(
            """SELECT se.id,se.sense_id,se.sense_type,se.source_id,se.source_uri,se.event_type,se.title,se.observed_at,se.metadata_json
               FROM observations o LEFT JOIN sense_events se ON se.id=o.sense_event_id
               WHERE o.id=?""",
            (observation_id,),
        ).fetchone()
        if row and row[0]:
            return {
                "sense_event_id": row[0],
                "sense_id": row[1],
                "sense_type": row[2],
                "source_id": row[3],
                "source_uri": row[4],
                "event_type": row[5],
                "title": row[6],
                "observed_at": row[7],
                "metadata": json.loads(row[8] or "{}"),
            }
    return {"source_uri": source_path}


def tick(db_path: Path, *, hints: list[str] | None = None, limit: int = 100) -> dict:
    hints = hints or DEFAULT_HINTS
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    now = now_iso()
    rows = conn.execute(
        """SELECT o.id observation_id,o.note_id,o.kind,o.text,o.source_path,o.score,o.created_at,n.name,n.type,n.updated_at
           FROM observations o JOIN nodes n ON n.id=o.note_id
           ORDER BY o.score DESC,o.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    upserted = 0
    for row in rows:
        breakdown = score_observation_candidate(
            kind=row["kind"],
            text=row["text"],
            base_score=row["score"],
            hints=hints,
            note_type=row["type"],
            note_name=row["name"],
            source_path=row["source_path"],
            observation_created_at=row["created_at"],
            node_updated_at=row["updated_at"],
        )
        score = breakdown.total
        reasons = list(breakdown.reasons) or ["high-signal observation"]
        if score < 0:
            continue
        candidate = {
            "score": score,
            "observation": {"kind": row["kind"], "text": row["text"], "source_path": row["source_path"], "score": row["score"]},
            "evidence": [row["text"]],
            "reasons": reasons,
        }
        actionability_score, tags, actionability_reasons = actionability_from_candidate(candidate)
        provenance = _candidate_source_provenance(conn, row["observation_id"], row["source_path"])
        factors = dict(candidate.get("why_now", {}).get("factors", {}))
        if provenance.get("sense_id"):
            factors["source_provenance"] = 1.0
        topic_terms = _topic_terms(row["text"])
        sibling_senses = set()
        for sibling_text, sibling_event in conn.execute("SELECT text,sense_event_id FROM observations WHERE id != ? AND sense_event_id IS NOT NULL", (row["observation_id"],)).fetchall():
            if len(topic_terms & _topic_terms(sibling_text or "")) >= 2:
                sibling_senses.add(sibling_event)
        if sibling_senses:
            factors["cross_sense_corroboration"] = 1.0
            actionability_score += 1.0
        candidate_id = hashlib.sha1(f"thought-candidate:{row['observation_id']}".encode()).hexdigest()[:20]
        existing = conn.execute("SELECT status,cooldown_until FROM thought_candidates WHERE id=?", (candidate_id,)).fetchone()
        if existing and existing["status"] == "killed":
            continue
        if existing and existing["cooldown_until"] and existing["cooldown_until"] > now:
            continue
        conn.execute(
            """INSERT INTO thought_candidates(id,seed_id,seed_observation_id,activation_score,why_now_json,suggested_action,action_type,status,surfaced_count,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,COALESCE((SELECT surfaced_count FROM thought_candidates WHERE id=?),0),?,?)
               ON CONFLICT(id) DO UPDATE SET activation_score=excluded.activation_score,why_now_json=excluded.why_now_json,suggested_action=excluded.suggested_action,action_type=excluded.action_type,updated_at=excluded.updated_at""",
            (
                candidate_id,
                row["note_id"],
                row["observation_id"],
                round(actionability_score, 2),
                json.dumps({"factors": factors, "reasons": reasons + actionability_reasons, "tags": tags, "source": provenance}, ensure_ascii=False),
                row["text"][:180],
                tags[0] if tags else "mneme:thought/inspect",
                "candidate",
                candidate_id,
                now,
                now,
            ),
        )
        upserted += 1
    conn.commit()
    conn.close()
    return {"candidates_updated": upserted, "observations_considered": len(rows)}


def _surface_thought_candidates(db_path: Path, *, limit: int = 5) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    now = now_iso()
    rows = conn.execute(
        """SELECT tc.*,o.text observation_text,o.kind observation_kind,o.source_path,n.name seed_name,n.type seed_type
           FROM thought_candidates tc
           LEFT JOIN observations o ON o.id=tc.seed_observation_id
           LEFT JOIN nodes n ON n.id=tc.seed_id
           WHERE tc.status='candidate' AND (tc.cooldown_until IS NULL OR tc.cooldown_until <= ?)
           ORDER BY tc.activation_score DESC,tc.updated_at DESC LIMIT ?""",
        (now, limit),
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        why_now = json.loads(row["why_now_json"] or "{}")
        conn.execute("UPDATE thought_candidates SET surfaced_count=surfaced_count+1,last_surfaced_at=? WHERE id=?", (now, row["id"]))
        items.append({
            "id": row["id"],
            "seed_id": row["seed_id"],
            "seed_observation_id": row["seed_observation_id"],
            "title": row["seed_name"] or row["suggested_action"],
            "suggested_action": row["suggested_action"],
            "activation_score": row["activation_score"],
            "why_now": why_now,
            "source_path": row["source_path"],
            "observation": {"kind": row["observation_kind"], "text": row["observation_text"], "source_path": row["source_path"]},
        })
    conn.commit()
    conn.close()
    return items


def surface_thoughts(
    db_path: Path,
    prompt: str | None = None,
    *,
    limit: int = 5,
    hops: int = 5,
    hints: list[str] | None = None,
    include_candidates: bool = True,
) -> dict | list[dict]:
    if prompt is None:
        return _surface_thought_candidates(db_path, limit=limit)
    hints = hints or DEFAULT_HINTS
    query = prompt
    context = retrieve_context(
        db_path,
        query,
        budget=5000,
        max_items=max(limit * 2, limit),
        hints=hints,
        include_candidates=include_candidates,
    )
    thoughts = [_surface_item_to_thought(db_path, item, query) for item in context.get("items", [])[:limit]]
    if not thoughts and not prompt:
        candidates = list_thought_candidates(db_path, limit=limit, hops=hops, hints=hints)
        thoughts = [generate_thought(db_path, candidate["path"], candidate) for candidate in candidates]
    return {
        "prompt": query,
        "count": len(thoughts),
        "thoughts": thoughts,
        "retrieval": {
            "clusters": context.get("clusters", []),
            "brain_labels": context.get("brain_labels", []),
            "stats": context.get("stats", {}),
            "empty_reason": context.get("empty_reason"),
        },
        "empty_reason": None if thoughts else "No retrievable items or thought candidates surfaced.",
    }


def record_feedback(db_path: Path, thought_id: str, feedback_type: str, *, reason: str | None = None, snooze: str | None = None) -> dict:
    status_map = {
        "accept": "candidate",
        "deny": "dismissed",
        "kill": "killed",
        "acted": "acted",
        "already_done": "resolved",
        "too_obvious": "dismissed",
        "good_but_later": "candidate",
        "snooze": "candidate",
    }
    if feedback_type not in status_map:
        raise ValueError(f"unknown feedback type: {feedback_type}")
    cooldown_until = _iso_add_duration(snooze) if snooze else None
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT tc.id,tc.seed_observation_id,o.note_id,o.text
           FROM thought_candidates tc
           LEFT JOIN observations o ON o.id=tc.seed_observation_id
           WHERE tc.id=?""",
        (thought_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "id": thought_id, "error": "not_found"}
    feedback_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO thought_feedback(id,thought_id,feedback_type,reason,cooldown_until,created_at) VALUES(?,?,?,?,?,?)",
        (feedback_id, thought_id, feedback_type, reason, cooldown_until, now_iso()),
    )
    status = status_map[feedback_type]
    conn.execute("UPDATE thought_candidates SET status=?, cooldown_until=?, updated_at=? WHERE id=?", (status, cooldown_until, now_iso(), thought_id))
    edge_changes: list[dict] = []
    related_edges = []
    if row["seed_observation_id"] and row["note_id"] and row["text"]:
        related_edges = conn.execute(
            """
            SELECT id,status,strength
            FROM edges
            WHERE src_id=?
              AND relation LIKE 'has_%'
              AND evidence_text=?
              AND status!='killed'
            """,
            (row["note_id"], row["text"][:500]),
        ).fetchall()
    if feedback_type in {"deny", "too_obvious", "good_but_later", "snooze"}:
        for edge in related_edges:
            previous = float(edge["strength"] or 0)
            new_strength = round(max(0.0, previous * 0.5), 6)
            new_status = "candidate" if edge["status"] == "active" and new_strength < 0.10 else edge["status"]
            conn.execute("UPDATE edges SET strength=?, status=?, updated_at=? WHERE id=? AND status!='killed'", (new_strength, new_status, now_iso(), edge["id"]))
            log_edge_event(conn, edge["id"], "weakened", "user_feedback", {"reason": reason or feedback_type, "factor": 0.5, "previous_strength": previous, "new_strength": new_strength, "previous_status": edge["status"], "new_status": new_status})
            edge_changes.append({"id": edge["id"], "action": "weaken", "previous_strength": previous, "strength": new_strength, "status": new_status})
    elif feedback_type == "kill":
        for edge in related_edges:
            conn.execute("UPDATE edges SET strength=0.0, status='killed', updated_at=? WHERE id=?", (now_iso(), edge["id"]))
            log_edge_event(conn, edge["id"], "killed", "user_feedback", {"reason": reason or "false relationship", "previous_status": edge["status"], "previous_strength": edge["strength"]})
            edge_changes.append({"id": edge["id"], "action": "kill", "status": "killed"})
    conn.commit()
    conn.close()
    return {"ok": True, "id": thought_id, "feedback_type": feedback_type, "status": status, "cooldown_until": cooldown_until, "edge_changes": edge_changes}


def explain_thought(db_path: Path, thought_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    row = conn.execute(
        """SELECT tc.*,o.id observation_id,o.text observation_text,o.kind observation_kind,o.source_path,n.name seed_name,n.type seed_type
           FROM thought_candidates tc
           LEFT JOIN observations o ON o.id=tc.seed_observation_id
           LEFT JOIN nodes n ON n.id=tc.seed_id
           WHERE tc.id=?""",
        (thought_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"id": thought_id, "error": "not_found"}
    feedback = [dict(item) for item in conn.execute("SELECT feedback_type,reason,cooldown_until,created_at FROM thought_feedback WHERE thought_id=? ORDER BY created_at", (thought_id,)).fetchall()]
    provenance = _candidate_source_provenance(conn, row["observation_id"], row["source_path"])
    conn.close()
    return {
        "id": thought_id,
        "activation_score": row["activation_score"],
        "status": row["status"],
        "why_now": json.loads(row["why_now_json"] or "{}"),
        "seed": {"id": row["seed_id"], "name": row["seed_name"], "type": row["seed_type"]},
        "seed_observation": {"id": row["observation_id"], "kind": row["observation_kind"], "text": row["observation_text"], "source_path": row["source_path"]},
        "sense_provenance": provenance,
        "feedback_history": feedback,
    }


def remember_graph(db_path: Path, payload: dict | str, *, dry_run: bool = False) -> dict:
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert isinstance(payload, dict)
    source_path = str(payload.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("remember payload requires source_path")
    if not source_path.startswith("mneme://"):
        raise ValueError("remember source_path must use the mneme:// namespace")
    nodes_in = payload.get("nodes") or []
    edges_in = payload.get("edges") or []
    observations_in = payload.get("observations") or []
    assertions_in = payload.get("assertions") or []
    created_nodes: dict[str, str] = {}
    out_nodes = []
    out_edges = []
    out_observations = []
    out_assertions = []
    conn = sqlite3.connect(db_path)
    init_db(conn)
    try:
        for index, node in enumerate(nodes_in):
            ref = str(node.get("ref") or node.get("id") or f"node{index + 1}")
            node_type = str(node.get("type") or "entity")
            name = str(node.get("name") or node.get("label") or "").strip()
            if not name:
                raise ValueError(f"remember node {ref} requires name (or label alias)")
            node_id = upsert_node(conn, node_type, name, source_path, float(node.get("confidence", 1.0)), node.get("metadata") or {})
            created_nodes[ref] = node_id
            out_nodes.append({"ref": ref, "id": node_id, "type": node_type, "name": name, "source_path": source_path})
        for edge in edges_in:
            src_ref = str(edge.get("src") or "")
            dst_ref = str(edge.get("dst") or "")
            if src_ref not in created_nodes or dst_ref not in created_nodes:
                raise ValueError("remember edges must reference nodes from the same payload")
            relation = str(edge.get("relation") or "relates_to")
            status = str(edge.get("status") or "candidate")
            confidence = float(edge.get("confidence", 0.7))
            strength = float(edge.get("strength", confidence))
            edge_id = upsert_edge(
                conn,
                created_nodes[src_ref],
                created_nodes[dst_ref],
                relation,
                source_path,
                str(edge.get("evidence") or ""),
                confidence,
                status=status,
                strength=strength,
                source_type=str(edge.get("source_type") or "remember"),
                metadata=edge.get("metadata") or {},
            )
            out_edges.append({"id": edge_id, "src": created_nodes[src_ref], "dst": created_nodes[dst_ref], "relation": relation, "status": status})
        for obs in observations_in:
            node_ref = str(obs.get("node") or obs.get("node_ref") or obs.get("node_id") or "")
            if node_ref not in created_nodes:
                existing = None
                if obs.get("node_id") and not (obs.get("node") or obs.get("node_ref")):
                    # node_id conventionally means a persisted Mneme node id, not a
                    # payload-local ref. Resolve it first to avoid silently creating
                    # a new entity named after an id-like string.
                    existing = conn.execute("SELECT id FROM nodes WHERE id=? LIMIT 1", (node_ref,)).fetchone()
                if not existing:
                    # Auto-resolve or auto-create: look up by name, else create entity.
                    # This preserves existing behavior for node/node_ref and for
                    # node_id values that are intentionally payload-local refs.
                    existing = conn.execute(
                        "SELECT id FROM nodes WHERE name=? COLLATE NOCASE LIMIT 1",
                        (node_ref,),
                    ).fetchone()
                if existing:
                    created_nodes[node_ref] = existing[0]
                else:
                    # Auto-create as entity node with the ref as its name
                    auto_name = str(obs.get("node_name") or node_ref)
                    auto_id = upsert_node(conn, "entity", auto_name, source_path)
                    created_nodes[node_ref] = auto_id
                    out_nodes.append({"ref": node_ref, "id": auto_id, "type": "entity", "name": auto_name, "source_path": source_path, "auto_created": True})
            text = str(obs.get("text") or "").strip()
            if not text:
                raise ValueError("remember observation requires text")
            kind = str(obs.get("kind") or "fact")
            # Correction observations default to high score
            default_score = 9.0 if kind == "correction" else 3.0
            out_observations.append({"node": created_nodes[node_ref], "kind": kind, "text": text[:1000]})
            if not dry_run:
                add_observation(conn, created_nodes[node_ref], kind, text, source_path, float(obs.get("score", default_score)))
        for assertion in assertions_in:
            subject_ref = str(assertion.get("subject_ref") or assertion.get("subject_node") or "")
            subject_node_id = created_nodes.get(subject_ref) if subject_ref else None
            result = upsert_assertion(
                conn,
                assertion,
                source_path=source_path,
                subject_node_id=subject_node_id,
                valid_from=assertion.get("valid_from") or payload.get("date"),
                active=claim_status(assertion) == "active",
            )
            out_assertions.append(result)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "dry_run": dry_run,
        "source_path": source_path,
        "nodes": out_nodes,
        "edges": out_edges,
        "observations": out_observations,
        "assertions": out_assertions,
    }


def _edge_row_payload(row: sqlite3.Row) -> dict:
    metadata = {}
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except Exception:
        metadata = {}
    return {
        "id": row["id"],
        "src": row["src_name"],
        "dst": row["dst_name"],
        "relation": row["relation"],
        "status": row["status"],
        "strength": float(row["strength"] or 0.0),
        "confidence": float(row["confidence"] or 0.0),
        "evidence": row["evidence_text"] or "",
        "source_path": row["source_path"],
        "metadata": metadata,
    }


MEDITATION_PLUMBING_RELATIONS = {"links_to", "has_heading", "mentions_date", "mentions_email"}
MEDITATION_LOW_SIGNAL_TERMS = {
    "oauth", "invalid_grant", "token", "traceback", "cron", "status board", "debug", "log", "heartbeat",
    "index", "heading", "calendar event", "daily note", "yesterday", "tomorrow", "old blocker",
}
MEDITATION_HIGH_VALUE_TERMS = {
    "school", "deadline", "lease", "rent", "tax", "move", "property", "family", "payment", "invoice",
    "meeting", "doctor", "passport", "visa", "citizenship", "contract", "notice", "evidence", "confirmed",
}
MEDITATION_OPEN_LOOP_TERMS = {
    "needs", "need to", "todo", "to do", "follow up", "waiting", "awaiting", "unresolved", "blocked",
    "stalled", "open", "draft", "unsent", "relist", "transfer", "chase", "call", "email", "reply",
}
MEDITATION_RESOLVED_TERMS = {
    "done", "resolved", "paid", "sent", "completed", "closed", "cancelled", "moot", "not urgent",
}


def _meditation_has_term(text: str, terms: set[str]) -> bool:
    for term in terms:
        if " " in term:
            if term in text:
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
            return True
    return False


def _meditation_path_penalty(source_path: str | None, *, source_type: str | None = None, metadata_json: str | None = None) -> float:
    path = (source_path or "").lower()
    if not path:
        return 1.0
    # User-confirmed corrections in MEMORY.md should NOT be penalized
    if source_type == "user_confirmed":
        return 1.0
    if metadata_json:
        try:
            meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
            if meta.get("certainty") == "user_confirmed" or meta.get("source_type") == "user_confirmed":
                return 1.0
        except (json.JSONDecodeError, TypeError):
            pass
    if "/memory/" in f"/{path}" or path.startswith("memory/"):
        return 0.18
    if "/archive/" in f"/{path}" or "daily" in path:
        return 0.12
    if any(part in path for part in ["logs/", "cron/", "out/", "debug", "heartbeat"]):
        return 0.08
    if path.startswith("projects/") or path.startswith("people/") or path.startswith("vendors/") or path.startswith("events/"):
        return 1.35
    return 1.0


def _meditation_parse_date(value: str) -> dt.date | None:
    value = value.strip()
    formats = ["%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"]
    for fmt in formats:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _meditation_extract_dates(text: str) -> list[dt.date]:
    dates: list[dt.date] = []
    current_year = dt.datetime.now(dt.timezone.utc).year
    for match in re.finditer(r"\b(20\d{2}-\d{2}-\d{2})\b", text or ""):
        parsed = _meditation_parse_date(match.group(1))
        if parsed:
            dates.append(parsed)
    for match in re.finditer(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(20\d{2})\b", text or "", re.I):
        day, month, year = match.groups()
        parsed = _meditation_parse_date(f"{int(day):02d} {month[:3]} {year}")
        if parsed:
            dates.append(parsed)
    for match in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:,)?(?:\s+(20\d{2}))?\b", text or "", re.I):
        month, day, year = match.groups()
        parsed = _meditation_parse_date(f"{month[:3]} {int(day):02d} {year or current_year}")
        if parsed:
            dates.append(parsed)
    return dates


def _meditation_source_date(source_path: str | None) -> dt.date | None:
    path = source_path or ""
    match = re.search(r"(20\d{2})[-_/](\d{2})[-_/](\d{2})", path)
    if not match:
        return None
    return _meditation_parse_date("-".join(match.groups()))


def _meditation_staleness_penalty(text: str, source_path: str | None) -> float:
    evidence = (text or "").lower()
    dates = []
    dates.extend(_meditation_extract_dates(text or ""))
    source_date = _meditation_source_date(source_path or "")
    if source_date:
        dates.append(source_date)
    if not dates:
        return 1.0
    today = dt.datetime.now(dt.timezone.utc).date()
    newest = max(dates)
    age = (today - newest).days
    unresolved = _meditation_has_term(evidence, MEDITATION_OPEN_LOOP_TERMS)
    resolved = _meditation_has_term(evidence, MEDITATION_RESOLVED_TERMS)
    # Old resolved items should go quiet. Old unresolved/open-loop items should
    # not be forgotten: make them dormant and revalidation-worthy rather than
    # deleting/suppressing them entirely.
    if age > 60:
        return 0.02 if resolved else (0.35 if unresolved else 0.05)
    if age > 30:
        return 0.05 if resolved else (0.50 if unresolved else 0.12)
    if age > 14:
        return 0.12 if resolved else (0.70 if unresolved else 0.30)
    if age > 7:
        return 0.30 if resolved else (0.85 if unresolved else 0.55)
    return 1.0


def _meditation_seed_weight(row: sqlite3.Row) -> float:
    evidence = (row["evidence_text"] or "").lower()
    relation = row["relation"] or ""
    status = row["status"] or "candidate"
    strength = float(row["strength"] or 0.1)
    base = max(0.05, strength + 0.2)
    novelty = 2.0 if status == "candidate" else 1.0
    relation_weight = 0.08 if relation in MEDITATION_PLUMBING_RELATIONS else 1.4
    contradiction = 4.0 if any(w in evidence for w in ["contradiction", " not connected", "not related", "false", "wrong"]) else 1.0
    high_value = 1.6 if _meditation_has_term(evidence, MEDITATION_HIGH_VALUE_TERMS) else 1.0
    open_loop = 2.2 if _meditation_has_term(evidence, MEDITATION_OPEN_LOOP_TERMS) else 1.0
    resolved = 0.10 if _meditation_has_term(evidence, MEDITATION_RESOLVED_TERMS) else 1.0
    low_signal = 0.12 if _meditation_has_term(evidence, MEDITATION_LOW_SIGNAL_TERMS) else 1.0
    source_penalty = _meditation_path_penalty(row["source_path"], source_type=row["source_type"] if "source_type" in row.keys() else None, metadata_json=row["metadata_json"] if "metadata_json" in row.keys() else None)
    stale_penalty = _meditation_staleness_penalty(row["evidence_text"] or "", row["source_path"])
    semantic_node_bonus = 1.25 if row["src_type"] in {"project", "person", "place", "event", "finance", "vendor"} or row["dst_type"] in {"project", "person", "place", "event", "finance", "vendor"} else 1.0
    return max(0.001, base * novelty * relation_weight * contradiction * high_value * open_loop * resolved * low_signal * source_penalty * stale_penalty * semantic_node_bonus)


def _meditation_seed_edges(conn: sqlite3.Connection, *, rng: random.Random, walks: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """SELECT e.*,a.name src_name,b.name dst_name,a.type src_type,b.type dst_type
           FROM edges e JOIN nodes a ON a.id=e.src_id JOIN nodes b ON b.id=e.dst_id
           WHERE e.status != 'killed' AND COALESCE(e.strength,0) >= 0
           ORDER BY e.updated_at DESC LIMIT 1000"""
    ).fetchall()
    if not rows:
        return []
    weighted = []
    for row in rows:
        weight = _meditation_seed_weight(row)
        weighted.append((row, weight))
    chosen = []
    pool = weighted[:]
    for _ in range(min(max(walks, 1), len(pool))):
        total = sum(w for _, w in pool)
        pick = rng.random() * total
        upto = 0.0
        for idx, (row, weight) in enumerate(pool):
            upto += weight
            if upto >= pick:
                chosen.append(row)
                pool.pop(idx)
                break
    return chosen


def _edge_meditation_signal(edge: dict) -> tuple[str, float, str]:
    evidence = (edge.get("evidence") or "").lower()
    metadata = edge.get("metadata") or {}
    if metadata.get("contradicted") or any(w in evidence for w in ["contradiction", "not connected", "not related", "false", "wrong"]):
        return "weaken", 0.84, "current connection has explicit contradictory evidence"
    if metadata.get("validated") or any(w in evidence for w in ["explicit evidence", "confirmed", "receipt", "validated", "source-backed"]):
        return "strengthen", 0.82, "candidate connection has explicit supporting evidence"
    if _meditation_has_term(evidence, MEDITATION_OPEN_LOOP_TERMS):
        return "inspect", 0.68, "old or current open loop should be revalidated and converted into a concrete next action if still unresolved"
    return "inspect", 0.48, "interesting random walk but not enough evidence to adjust graph"


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def _meditation_reflection_prompt(edge: dict, *, iteration: int, previous: list[dict], deterministic_signal: tuple[str, float, str]) -> str:
    action, score, reason = deterministic_signal
    prior = previous[-3:]
    return json.dumps({
        "role": "Mneme dream/reflection engine",
        "instruction": (
            "Think creatively but sceptically. This is private inner monologue, not user output. "
            "Given one graph edge, produce exactly one JSON object. Make a surprising hypothesis if warranted, "
            "then attack it. Prefer silence over vague cleverness. Generated ideas are hypotheses, not truth."
        ),
        "required_json_schema": {
            "hypothesis": "one sentence",
            "supporting_evidence": ["quotes from supplied edge only"],
            "contradicting_evidence": ["quotes from supplied edge only"],
            "next_question": "what should be checked next",
            "action": "strengthen|weaken|inspect|discard|act",
            "confidence": "0..1",
            "novelty": "0..1",
            "usefulness": "0..1",
            "surface_score": "0..1",
            "reason": "brief explanation",
            "action_intent": "concrete next step if action is act or inspect finds an open loop"
        },
        "hard_rules": [
            "Do not invent evidence not supplied here.",
            "If evidence is old but describes an unresolved/open loop, do not discard because of age alone: choose inspect or act and ask for live-source revalidation.",
            "If evidence is old and also says done/resolved/sent/paid/completed, choose discard.",
            "If evidence is stale, generic, or merely structural with no open loop, choose inspect or discard.",
            "Choose act when the edge describes a still-open useful next step; action_intent must be concrete and source-checkable.",
            "Choose strengthen only for explicit supporting evidence.",
            "Choose weaken only for explicit contradictory evidence.",
            "Surface score should be high only if useful, timely, evidence-backed, and actionable."
        ],
        "edge": edge,
        "deterministic_hint": {"action": action, "score": score, "reason": reason},
        "recent_private_iterations": prior,
    }, ensure_ascii=False, indent=2)


def _run_meditation_reflection(
    edge: dict,
    *,
    iteration: int,
    previous: list[dict],
    deterministic_signal: tuple[str, float, str],
    provider: str | None,
    command: str | list[str] | None,
    timeout: int,
) -> dict | None:
    if not provider and not command:
        return None
    from .harness import run_llm

    prompt = _meditation_reflection_prompt(edge, iteration=iteration, previous=previous, deterministic_signal=deterministic_signal)
    result = run_llm(prompt, provider=provider or "custom", command=command, timeout=timeout)
    if not result.ok:
        return {"ok": False, "error": result.error or result.stderr or f"exit {result.exit_code}", "raw": result.stdout[:2000]}
    try:
        payload = _extract_json_object(result.stdout)
    except Exception as exc:
        return {"ok": False, "error": f"invalid_json: {exc}", "raw": result.stdout[:2000]}
    action = str(payload.get("action") or "inspect").lower().strip()
    if action not in {"strengthen", "weaken", "inspect", "discard", "act"}:
        action = "inspect"
    def clamp(name: str, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(payload.get(name, default))))
        except Exception:
            return default
    return {
        "ok": True,
        "hypothesis": str(payload.get("hypothesis") or "").strip()[:500],
        "supporting_evidence": [str(x)[:500] for x in (payload.get("supporting_evidence") or [])][:5],
        "contradicting_evidence": [str(x)[:500] for x in (payload.get("contradicting_evidence") or [])][:5],
        "next_question": str(payload.get("next_question") or "").strip()[:300],
        "action": action,
        "confidence": clamp("confidence", 0.4),
        "novelty": clamp("novelty", 0.5),
        "usefulness": clamp("usefulness", 0.4),
        "surface_score": clamp("surface_score", 0.0),
        "reason": str(payload.get("reason") or "").strip()[:500],
        "action_intent": str(payload.get("action_intent") or "").strip()[:500],
    }


def meditate_graph(
    db_path: Path,
    *,
    iterations: int = 10,
    walks: int = 6,
    random_seed: int | None = None,
    model: str | None = None,
    creative: bool = True,
    min_surface_score: float = 0.72,
    dry_run: bool = False,
    reflection_provider: str | None = None,
    reflection_command: str | list[str] | None = None,
    reflection_timeout: int = 120,
) -> dict:
    """Run a slow, creative graph meditation.

    This is intentionally evidence-conservative: it can strengthen supported
    links and weaken contradicted links, but generated ideas begin as hypotheses
    and only surface if their final score clears a high threshold. Randomized
    seed walks are part of the contract so the system can make non-obvious
    associations instead of always retrieving the top-ranked item.
    """
    rng = random.Random(random_seed)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    started = now_iso()
    meditation_id = uuid.uuid4().hex[:20]
    seed_strategy = {
        "randomness": "weighted_random_walk",
        "walks": walks,
        "seed": random_seed,
        "creative_instruction": "Dream: wander, associate, doubt yourself, cross-check, and keep quiet unless useful.",
        "reflection": "llm" if (reflection_provider or reflection_command) else "deterministic_fallback",
    }
    seed_rows = _meditation_seed_edges(conn, rng=rng, walks=walks)
    seed_edges = [_edge_row_payload(row) for row in seed_rows]
    if not seed_edges:
        conn.close()
        return {"ok": True, "dry_run": dry_run, "decision": "silent", "reason": "empty_graph", "iterations": [], "edge_changes": [], "creative_mode": creative, "seed_strategy": seed_strategy}
    if not dry_run:
        conn.execute(
            "INSERT INTO meditations(id,started_at,model,seed_strategy,status,metadata_json) VALUES(?,?,?,?,?,?)",
            (meditation_id, started, model, json.dumps(seed_strategy, ensure_ascii=False), "running", json.dumps({"seed_edges": seed_edges}, ensure_ascii=False)),
        )
    iteration_outputs: list[dict] = []
    hypotheses: list[dict] = []
    for idx in range(1, max(iterations, 1) + 1):
        edge = seed_edges[(idx - 1) % len(seed_edges)]
        deterministic = _edge_meditation_signal(edge)
        action, score, reason = deterministic
        reflection = _run_meditation_reflection(
            edge,
            iteration=idx,
            previous=iteration_outputs,
            deterministic_signal=deterministic,
            provider=reflection_provider,
            command=reflection_command,
            timeout=reflection_timeout,
        )
        if reflection and reflection.get("ok"):
            action = str(reflection.get("action") or action)
            score = float(reflection.get("surface_score", reflection.get("confidence", score)))
            reason = str(reflection.get("reason") or reason)
            claim = str(reflection.get("hypothesis") or f"{edge['src']} {edge['relation']} {edge['dst']} may need {action}")
            supporting = list(reflection.get("supporting_evidence") or [])
            contradicting = list(reflection.get("contradicting_evidence") or [])
            next_question = str(reflection.get("next_question") or "What source evidence would falsify this?")
            action_intent = str(reflection.get("action_intent") or "")
        else:
            jitter = rng.uniform(-0.04, 0.04)
            score = max(0.0, min(1.0, score + jitter))
            claim = f"{edge['src']} {edge['relation']} {edge['dst']} may need {action}"
            supporting = [edge["evidence"]] if action == "strengthen" else []
            contradicting = [edge["evidence"]] if action == "weaken" else []
            next_question = "What would live senses or source evidence show that would falsify this?"
            action_intent = "Revalidate this open loop against live sources, then perform or draft the smallest safe next step." if action == "inspect" and _meditation_has_term((edge.get("evidence") or "").lower(), MEDITATION_OPEN_LOOP_TERMS) else ""
        decision = "cross_check" if action in {"strengthen", "weaken"} else ("actionable" if action == "act" else ("discard" if action == "discard" else "continue"))
        out = {
            "iteration": idx,
            "edge_id": edge["id"],
            "dream_prompt": "creative random graph walk; form a hypothesis, then attack it",
            "reflection_used": bool(reflection and reflection.get("ok")),
            "reflection_error": None if (not reflection or reflection.get("ok")) else reflection.get("error"),
            "hypothesis": claim,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "score": round(score, 3),
            "decision": decision,
            "next_question": next_question,
            "action_intent": action_intent,
            "reason": reason,
        }
        iteration_outputs.append(out)
        if action in {"strengthen", "weaken", "act"}:
            hypotheses.append({"edge": edge, "action": action, "score": score, "claim": claim, "reason": reason, "action_intent": action_intent})
        if not dry_run:
            iter_id = hashlib.sha1(f"{meditation_id}:{idx}:{edge['id']}".encode()).hexdigest()[:20]
            conn.execute(
                """INSERT INTO meditation_iterations(id,meditation_id,iteration_index,prompt,output_json,hypothesis,supporting_evidence_json,contradicting_evidence_json,next_question,score,decision,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    iter_id,
                    meditation_id,
                    idx,
                    out["dream_prompt"],
                    json.dumps(out, ensure_ascii=False),
                    claim,
                    json.dumps(out["supporting_evidence"], ensure_ascii=False),
                    json.dumps(out["contradicting_evidence"], ensure_ascii=False),
                    out["next_question"],
                    score,
                    decision,
                    now_iso(),
                ),
            )
            hyp_id = hashlib.sha1(f"{meditation_id}:{edge['id']}:{action}".encode()).hexdigest()[:20]
            conn.execute(
                """INSERT OR REPLACE INTO hypotheses(id,meditation_id,claim,entities_json,relation,confidence,novelty,usefulness,evidence_count,contradiction_count,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    hyp_id,
                    meditation_id,
                    claim,
                    json.dumps([edge["src"], edge["dst"]], ensure_ascii=False),
                    edge["relation"],
                    score,
                    0.75 if creative else 0.45,
                    score,
                    len(out["supporting_evidence"]),
                    len(out["contradicting_evidence"]),
                    "cross_checked" if action in {"strengthen", "weaken"} else ("actionable" if action == "act" else "proposed"),
                    now_iso(),
                    now_iso(),
                ),
            )
    changes = []
    applied_edges = set()
    for hyp in sorted(hypotheses, key=lambda h: h["score"], reverse=True):
        edge = hyp["edge"]
        if edge["id"] in applied_edges:
            continue
        applied_edges.add(edge["id"])
        old_strength = float(edge["strength"] or 0.0)
        if hyp["action"] == "strengthen":
            new_strength = min(1.0, old_strength + 0.25)
            new_status = "active" if hyp["score"] >= 0.7 else edge["status"]
            event = "meditation_strengthened"
        elif hyp["action"] == "act":
            new_strength = min(1.0, old_strength + 0.10)
            new_status = edge["status"]
            event = "meditation_actionable"
        else:
            new_strength = max(0.0, old_strength * 0.35)
            new_status = edge["status"]
            event = "meditation_weakened"
        changes.append({"edge_id": edge["id"], "action": hyp["action"], "old_strength": old_strength, "new_strength": new_strength, "status": new_status, "reason": hyp["reason"], "action_intent": hyp.get("action_intent", "")})
        if not dry_run:
            conn.execute("UPDATE edges SET strength=?, status=?, updated_at=? WHERE id=?", (new_strength, new_status, now_iso(), edge["id"]))
            log_edge_event(conn, edge["id"], event, "meditation", {"hypothesis": hyp["claim"], "reason": hyp["reason"], "old_strength": old_strength, "new_strength": new_strength})
    final_score = max([h["score"] for h in hypotheses], default=0.0)
    # Action candidates from old/open evidence are useful private cognition, but
    # they are not user-surfaceable until a live-source/action layer revalidates
    # the loop. Meditation may propose action; it must not notify the user on old
    # evidence alone.
    surfaceable_scores = [h["score"] for h in hypotheses if h["action"] in {"strengthen", "weaken"}]
    surfaceable_score = max(surfaceable_scores, default=0.0)
    decision = "surface" if surfaceable_score >= min_surface_score else "silent"
    summary = "Meditation adjusted graph evidence silently." if changes else "Meditation found no evidence-backed graph adjustments."
    fingerprint = hashlib.sha1(summary.encode()).hexdigest()[:20]
    if not dry_run:
        conn.execute(
            "UPDATE meditations SET completed_at=?,status=?,final_summary=?,final_score=?,metadata_json=? WHERE id=?",
            (now_iso(), "surfaced" if decision == "surface" else "distilled", summary, final_score, json.dumps({"seed_edges": seed_edges, "edge_changes": changes}, ensure_ascii=False), meditation_id),
        )
        conn.execute(
            "INSERT INTO thought_fingerprints(id,fingerprint,topic_entities_json,last_seen_at,surfaced_count) VALUES(?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET last_seen_at=excluded.last_seen_at,surfaced_count=thought_fingerprints.surfaced_count+excluded.surfaced_count",
            (fingerprint, fingerprint, json.dumps([e["src"] for e in seed_edges], ensure_ascii=False), now_iso(), 1 if decision == "surface" else 0),
        )
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    return {
        "ok": True,
        "dry_run": dry_run,
        "id": meditation_id,
        "decision": decision,
        "creative_mode": creative,
        "seed_strategy": seed_strategy,
        "seed_edges": seed_edges,
        "iterations": iteration_outputs,
        "hypotheses": [{"claim": h["claim"], "action": h["action"], "score": round(h["score"], 3), "action_intent": h.get("action_intent", "")} for h in hypotheses],
        "edge_changes": changes,
        "surface_score": round(surfaceable_score, 3),
        "user_message": summary if decision == "surface" else "[SILENT]",
    }


def _sense_bridge_terms(*parts: str) -> set[str]:
    text = " ".join(p or "" for p in parts).lower()
    words = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text)
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "still", "needs", "need", "follow", "update", "task", "event", "email", "calendar", "notion", "open"}
    return {w for w in words if w not in stop}


def _event_payload(event: Any) -> dict:
    return {
        "id": str(getattr(event, "id", "") or uuid.uuid4().hex),
        "sense_id": str(getattr(event, "sense_id", "unknown")),
        "sense_type": str(getattr(event, "sense_type", "unknown")),
        "source_id": str(getattr(event, "source_id", "")),
        "source_uri": getattr(event, "source_uri", None),
        "observed_at": str(getattr(event, "observed_at", "") or now_iso()),
        "title": str(getattr(event, "title", "") or ""),
        "text": str(getattr(event, "text", "") or ""),
        "event_type": str(getattr(event, "event_type", "event") or "event"),
        "metadata": getattr(event, "metadata", None) or {},
    }


def _bridge_match_score(candidate_terms: set[str], event_terms: set[str]) -> float:
    if not candidate_terms or not event_terms:
        return 0.0
    overlap = candidate_terms & event_terms
    return len(overlap) / max(3, min(len(candidate_terms), 12))


def revalidate_action_candidates(
    db_path: Path,
    *,
    events: Iterable[Any] | None = None,
    candidate_limit: int = 20,
    min_match_score: float = 0.34,
    dry_run: bool = False,
) -> dict:
    """Bridge private action candidates to live source senses.

    Meditation may propose an action from old graph evidence, but it cannot
    surface that action by itself. This bridge ingests fresh sense events
    (Gmail/calendar/tasks/Notion/etc.), checks whether any event overlaps the
    candidate's entities/claim/connected nodes, and writes explicit
    ``revalidated_by`` evidence edges only for matched live source packets.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    event_payloads = [_event_payload(e) for e in (events or [])]
    if event_payloads and not dry_run:
        from .senses.base import SenseEvent
        sense_events = [SenseEvent(
            id=e["id"], sense_id=e["sense_id"], sense_type=e["sense_type"], source_id=e["source_id"], source_uri=e["source_uri"], observed_at=e["observed_at"], title=e["title"], text=e["text"], event_type=e["event_type"], metadata=e["metadata"],
        ) for e in event_payloads]
        ingest_sense_events(conn, sense_events)
    candidates = conn.execute(
        """SELECT h.* FROM hypotheses h
           WHERE h.status='actionable'
           ORDER BY COALESCE(h.updated_at,h.created_at) DESC LIMIT ?""",
        (candidate_limit,),
    ).fetchall()
    revalidated = []
    for hyp in candidates:
        entities = []
        try:
            entities = json.loads(hyp["entities_json"] or "[]")
        except Exception:
            entities = []
        connected = conn.execute(
            """SELECT a.name src,b.name dst,e.evidence_text,e.source_path FROM edges e
               JOIN nodes a ON a.id=e.src_id JOIN nodes b ON b.id=e.dst_id
               WHERE a.name IN (%s) OR b.name IN (%s) LIMIT 20""" % (",".join("?" for _ in entities) or "''", ",".join("?" for _ in entities) or "''"),
            tuple(entities) + tuple(entities),
        ).fetchall() if entities else []
        candidate_text = " ".join([str(hyp["claim"] or ""), " ".join(map(str, entities))] + [f"{r['src']} {r['dst']} {r['evidence_text']}" for r in connected])
        c_terms = _sense_bridge_terms(candidate_text)
        matches = []
        for ev in event_payloads:
            e_terms = _sense_bridge_terms(ev["title"], ev["text"], ev["event_type"], ev["source_id"])
            score = _bridge_match_score(c_terms, e_terms)
            if score >= min_match_score:
                matches.append({"event": ev, "score": round(score, 3), "overlap": sorted(c_terms & e_terms)[:12]})
        if not matches:
            continue
        best = sorted(matches, key=lambda m: m["score"], reverse=True)[0]
        revalidated.append({"hypothesis_id": hyp["id"], "claim": hyp["claim"], "sense_event_id": best["event"]["id"], "sense_type": best["event"]["sense_type"], "score": best["score"], "overlap": best["overlap"]})
        if not dry_run:
            hyp_node = upsert_node(conn, "hypothesis", str(hyp["claim"])[:120], f"mneme://hypothesis/{hyp['id']}", confidence=float(hyp["confidence"] or 0.7), metadata={"hypothesis_id": hyp["id"], "status": hyp["status"]})
            source_node = upsert_node(conn, "source_event", best["event"]["title"] or best["event"]["source_id"], best["event"]["source_uri"] or best["event"]["source_id"], confidence=0.9, metadata={"sense_event_id": best["event"]["id"], "sense_type": best["event"]["sense_type"], "event_type": best["event"]["event_type"]})
            eid = upsert_edge(conn, hyp_node, source_node, "revalidated_by", best["event"]["source_uri"] or best["event"]["source_id"], best["event"]["text"], 0.92, status="active", strength=0.92, source_type="sense_bridge", metadata={"hypothesis_id": hyp["id"], "match_score": best["score"], "overlap": best["overlap"]})
            log_edge_event(conn, eid, "sense_revalidated", "sense_bridge", {"hypothesis_id": hyp["id"], "sense_event_id": best["event"]["id"], "match_score": best["score"], "overlap": best["overlap"]})
    if not dry_run:
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    return {"ok": True, "dry_run": dry_run, "checked_candidates": len(candidates), "events_checked": len(event_payloads), "revalidated": len(revalidated), "matches": revalidated}


def forget_source(db_path: Path, source_path: str, *, dry_run: bool = False) -> dict:
    if not source_path.startswith("mneme://"):
        raise ValueError("forget_source only removes mneme:// scoped test or agent memory sources")
    conn = sqlite3.connect(db_path)
    init_db(conn)
    counts = {
        "observations": conn.execute("SELECT COUNT(*) FROM observations WHERE source_path=?", (source_path,)).fetchone()[0],
        "edges": conn.execute("SELECT COUNT(*) FROM edges WHERE source_path=?", (source_path,)).fetchone()[0],
        "nodes": conn.execute("SELECT COUNT(*) FROM nodes WHERE source_path=?", (source_path,)).fetchone()[0],
    }
    world_model_removed = delete_world_model_source(conn, source_path, dry_run=dry_run)
    if not dry_run:
        conn.execute("DELETE FROM observations WHERE source_path=?", (source_path,))
        conn.execute("DELETE FROM edge_debug_log WHERE edge_id IN (SELECT id FROM edges WHERE source_path=?)", (source_path,))
        conn.execute("DELETE FROM edges WHERE source_path=?", (source_path,))
        conn.execute("DELETE FROM nodes WHERE source_path=?", (source_path,))
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    return {
        "ok": True,
        "dry_run": dry_run,
        "source_path": source_path,
        "removed": counts,
        "world_removed": world_model_removed,
        "world_model_removed": world_model_removed,
    }


def forget_past_dates(db_path: Path, *, days_threshold: int = 30, dry_run: bool = False) -> dict:
    """Set edge weights to 0 for observations with dates older than threshold.
    
    This is Mneme's version of forgetting — edges stay in the graph but have
    zero weight so they don't surface. Never deletes nodes or observations.
    
    Args:
        db_path: Path to SQLite database
        days_threshold: Observations with dates older than this many days ago
        dry_run: If True, only report what would be affected
    
    Returns:
        Dict with counts of edges forgotten
    """
    import re
    from datetime import datetime, timedelta, timezone
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_threshold)).date()
    
    # Find all observations with date-like patterns in their text
    date_patterns = [
        r'\b(\d{4}-\d{2}-\d{2})\b',  # ISO date: 2026-04-21
        r'\b(Apr|Mar|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b',  # Apr 21
        r'\b(\d{1,2})\s+(Apr|Mar|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\b',  # 21 Apr 2026
    ]
    
    obs_rows = conn.execute("SELECT id, text, source_path FROM observations").fetchall()
    
    forgotten = []
    for obs in obs_rows:
        obs_id = obs['id']
        text = obs['text']
        
        # Extract dates from observation text
        extracted_dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        # Handle different match group patterns
                        if len(match) == 3:  # 21 Apr 2026
                            day, month, year = match
                            date_str = f"{year}-{month}-{int(day):02d}"
                        elif len(match) == 2:  # Apr 21 or 2026-04-21
                            if match[0].isdigit():  # 2026-04-21
                                date_str = match[0]
                            else:  # Apr 21
                                month, day = match
                                date_str = f"2026-{month}-{int(day):02d}"
                        else:
                            continue
                    else:
                        date_str = match
                    
                    # Try to parse the date
                    for fmt in ['%Y-%m-%d', '%Y-%b-%d']:
                        try:
                            parsed = datetime.strptime(date_str, fmt).date()
                            extracted_dates.append(parsed)
                            break
                        except ValueError:
                            continue
                except Exception:
                    continue
        
        # Check if any extracted date is older than threshold
        for extracted_date in extracted_dates:
            if extracted_date < cutoff:
                # Get edges connected to this observation via source_path
                edge_rows = []
                if obs['source_path']:
                    edge_rows = conn.execute("""
                        SELECT e.id, e.strength, e.status 
                        FROM edges e
                        WHERE e.source_path = ?
                    """, (obs['source_path'],)).fetchall()
                
                # If no edges by source_path, try matching evidence_text containing obs ID
                if not edge_rows:
                    edge_rows = conn.execute("""
                        SELECT e.id, e.strength, e.status 
                        FROM edges e
                        WHERE e.evidence_text LIKE ?
                    """, (f'%{obs_id[:12]}%',)).fetchall()
                
                for edge in edge_rows:
                    if edge['strength'] > 0:
                        forgotten.append({
                            'edge_id': edge['id'],
                            'obs_id': obs_id,
                            'previous_strength': edge['strength'],
                            'date_found': str(extracted_date),
                            'source_path': obs['source_path']
                        })
                break  # Move to next observation once we've found a past date
    
    # Apply weight changes and update thought candidates
    if not dry_run and forgotten:
        for item in forgotten:
            conn.execute("""
                UPDATE edges 
                SET strength = 0.0, status = 'candidate', updated_at = ?
                WHERE id = ? AND strength > 0
            """, (datetime.now(timezone.utc).isoformat(), item['edge_id']))
            
            # Mark related thought candidates as resolved
            conn.execute("""
                UPDATE thought_candidates
                SET status = 'resolved', updated_at = ?
                WHERE seed_observation_id = ? AND status = 'candidate'
            """, (datetime.now(timezone.utc).isoformat(), item['obs_id']))
            
            # Log the forget event
            conn.execute("""
                INSERT INTO edge_debug_log (edge_id, event, actor, thinking_json, created_at)
                VALUES (?, 'forgotten', 'past_date_auto_forget', ?, ?)
            """, (item['edge_id'], json.dumps({
                'previous_strength': item['previous_strength'],
                'date_found': item['date_found'],
                'threshold_days': days_threshold
            }), datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
    
    conn.close()
    
    return {
        "ok": True,
        "dry_run": dry_run,
        "threshold_days": days_threshold,
        "cutoff_date": str(cutoff),
        "forgotten_count": len(forgotten),
        "forgotten_edges": forgotten[:20] if not dry_run else []  # Limit output
    }


def configured_senses(config: dict | None) -> list[dict]:
    senses = (config or {}).get("senses")
    if isinstance(senses, list):
        return senses
    vault = (config or {}).get("vault")
    return [{"id": "vault", "type": "md", "enabled": True, "config": {"path": vault}}] if vault else []


def ingest_sense_events(conn: sqlite3.Connection, events: Iterable[Any], *, hints: list[str] | None = None) -> dict:
    init_db(conn)
    hints = hints or DEFAULT_HINTS
    stats = {"events": 0, "nodes": 0, "observations": 0, "edges": 0, "by_sense": {}, "by_event_type": {}}
    for event in events:
        event_id = str(getattr(event, "id", "") or uuid.uuid4().hex)
        sense_id = str(getattr(event, "sense_id", "unknown"))
        sense_type = str(getattr(event, "sense_type", "unknown"))
        source_id = str(getattr(event, "source_id", event_id))
        source_uri = getattr(event, "source_uri", None)
        event_type = str(getattr(event, "event_type", "event") or "event")
        title = str(getattr(event, "title", source_id) or source_id)
        text = str(getattr(event, "text", "") or "")
        observed_at = str(getattr(event, "observed_at", "") or now_iso())
        metadata = getattr(event, "metadata", None) or {}
        text_hash = hashlib.sha1(text.encode()).hexdigest()
        conn.execute(
            """INSERT OR REPLACE INTO sense_events(id,sense_id,sense_type,source_id,source_uri,event_type,title,text_hash,observed_at,ingested_at,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, sense_id, sense_type, source_id, source_uri, event_type, title, text_hash, observed_at, now_iso(), json.dumps(metadata, ensure_ascii=False)),
        )
        source_path = metadata.get("path") or source_uri or source_id
        node_type = metadata.get("node_type") or "note"
        node_id = upsert_node(conn, node_type, title, source_path, metadata={"sense_event_id": event_id, "sense_type": sense_type, **metadata})
        stats["nodes"] += 1
        for link in getattr(event, "links", None) or []:
            dst = upsert_node(conn, "wikilink", str(link), source_path)
            upsert_edge(conn, node_id, dst, "links_to", source_path, f"[[{link}]]", 0.7, status="candidate", strength=0.7, source_type=sense_type)
            stats["edges"] += 1
        for kind, obs_text, score in extract_observations(text, hints):
            add_observation(conn, node_id, kind, obs_text, source_path, score, sense_event_id=event_id)
            obs_id = upsert_node(conn, "observation", obs_text[:90], source_path, min(1.0, score / 6), {"kind": kind, "sense_event_id": event_id})
            stats["nodes"] += 1
            upsert_edge(
                conn,
                node_id,
                obs_id,
                f"has_{kind}",
                source_path,
                obs_text,
                min(1.0, score / 6),
                status=deterministic_ingest_status(f"has_{kind}"),
                strength=min(1.0, score / 6),
                source_type=sense_type,
                metadata={"sense_event_id": event_id},
            )
            stats["edges"] += 1
            for date_text in DATE_RE.findall(obs_text):
                date_id = upsert_node(conn, "date", date_text, source_path, 0.75)
                stats["nodes"] += 1
                upsert_edge(
                    conn,
                    obs_id,
                    date_id,
                    "mentions_date",
                    source_path,
                    obs_text,
                    0.75,
                    status=deterministic_ingest_status("mentions_date"),
                    strength=0.75,
                    source_type=sense_type,
                    metadata={"sense_event_id": event_id},
                )
                stats["edges"] += 1
            stats["observations"] += 1
        stats["events"] += 1
        stats["by_sense"][sense_id] = stats["by_sense"].get(sense_id, 0) + 1
        stats["by_event_type"][event_type] = stats["by_event_type"].get(event_type, 0) + 1
    return stats


def weaken_edge(db_path: Path, edge_id: str, reason: str = "User dismissed this proposal", factor: float = 0.5, floor: float = 0.0) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    row = conn.execute("SELECT id,strength,status FROM edges WHERE id=?", (edge_id,)).fetchone()
    if not row:
        conn.close()
        return {"weakened": 0, "id": edge_id, "error": "not_found"}
    if row["status"] == "killed":
        conn.close()
        return {"weakened": 0, "id": edge_id, "status": "killed"}
    previous = float(row["strength"] or 0)
    new_strength = round(max(float(floor), previous * float(factor)), 6)
    new_status = "candidate" if row["status"] == "active" and new_strength < 0.10 else row["status"]
    conn.execute("UPDATE edges SET strength=?, status=?, updated_at=? WHERE id=? AND status!='killed'", (new_strength, new_status, now_iso(), edge_id))
    log_edge_event(conn, edge_id, "weakened", "user_feedback", {"reason": reason, "factor": factor, "previous_strength": previous, "new_strength": new_strength, "previous_status": row["status"], "new_status": new_status})
    conn.commit()
    conn.close()
    return {"weakened": 1, "id": edge_id, "previous_strength": previous, "strength": new_strength, "status": new_status}


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
    query = " ".join(hints or DEFAULT_HINTS)
    surfaced = surface_thoughts(db_path, query, limit=1, hops=hops, hints=hints)
    if isinstance(surfaced, dict) and surfaced.get("thoughts"):
        return surfaced["thoughts"][0]
    candidates = list_thought_candidates(db_path, limit=12, hops=hops, hints=hints)
    chosen = _weighted_candidate_choice(candidates)
    if chosen:
        return generate_thought(db_path, chosen["path"], chosen)
    return generate_thought(db_path, walk_graph(db_path, hops=hops, hints=hints))


def save_thought(db_path: Path, thought: dict, image_path: str | None = None):
    conn=sqlite3.connect(db_path); tid=hashlib.sha1((thought["title"]+json.dumps([n["id"] for n in thought["path"]])+now_iso()).encode()).hexdigest()[:16]
    conn.execute("INSERT INTO thoughts(id,seed_id,path_json,title,insight,action,image_path,created_at) VALUES(?,?,?,?,?,?,?,?)",(tid,thought["path"][0].get("id"),json.dumps(thought["path"],ensure_ascii=False),thought["title"],thought["insight"],thought["action"],image_path,now_iso()))
    conn.commit(); conn.close(); return tid
