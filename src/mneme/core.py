from __future__ import annotations

import datetime as dt
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
STATUS_WORDS = {
    "blocked": ["blocked", "stuck", "waiting", "awaiting", "needs", "need to", "todo", "to do", "follow up", "unresolved"],
    "done": ["paid", "resolved", "closed", "completed", "done", "accepted", "confirmed"],
    "risk": ["deadline", "expires", "due", "appeal", "fine", "penalty", "urgent", "overdue", "risk"],
}
DEFAULT_HINTS = ["deadline", "project", "invoice", "lease", "tax", "school", "move", "certification", "payment"]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def stable_id(kind: str, name: str) -> str:
    return hashlib.sha1(f"{kind}:{name.lower()}".encode()).hexdigest()[:16]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,source_path TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confidence REAL DEFAULT 1.0,metadata_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,src_id TEXT NOT NULL,dst_id TEXT NOT NULL,relation TEXT NOT NULL,source_path TEXT,confidence REAL DEFAULT 1.0,evidence_text TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,note_id TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,source_path TEXT NOT NULL,score REAL DEFAULT 0,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS thoughts(id TEXT PRIMARY KEY,seed_id TEXT,path_json TEXT NOT NULL,title TEXT NOT NULL,insight TEXT NOT NULL,action TEXT,image_path TEXT,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
    CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
    CREATE INDEX IF NOT EXISTS idx_obs_note ON observations(note_id);
    """)


def upsert_node(conn, kind, name, source_path=None, confidence=1.0, metadata=None):
    nid = stable_id(kind, name); ts = now_iso()
    conn.execute("""INSERT INTO nodes(id,type,name,source_path,created_at,updated_at,confidence,metadata_json) VALUES(?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, source_path=COALESCE(excluded.source_path,nodes.source_path), confidence=max(nodes.confidence, excluded.confidence), metadata_json=excluded.metadata_json""",
    (nid, kind, name.strip(), source_path, ts, ts, confidence, json.dumps(metadata or {}, ensure_ascii=False)))
    return nid


def upsert_edge(conn, src, dst, relation, source_path, evidence="", confidence=1.0):
    eid = hashlib.sha1(f"{src}:{relation}:{dst}:{source_path}:{evidence[:80]}".encode()).hexdigest()[:20]; ts = now_iso()
    conn.execute("""INSERT INTO edges(id,src_id,dst_id,relation,source_path,confidence,evidence_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, confidence=max(edges.confidence, excluded.confidence)""",
    (eid, src, dst, relation, source_path, confidence, evidence[:500], ts, ts))
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


def ingest_vault(vault: Path, db_path: Path, hints: list[str] | None = None, max_notes: int | None = None, rebuild: bool = True, follow_symlinks: bool = False) -> dict:
    hints = hints or DEFAULT_HINTS; db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path); init_db(conn)
    if rebuild:
        # Privacy-first default: avoid stale private content when a DB is reused
        # with a different or sanitized vault.
        conn.executescript("DELETE FROM thoughts; DELETE FROM observations; DELETE FROM edges; DELETE FROM nodes;")
    else:
        conn.execute("DELETE FROM observations")
    notes=edges=observations=0
    for index, path in enumerate(iter_markdown(vault, {".git", "node_modules"}, follow_symlinks=follow_symlinks)):
        if max_notes is not None and index >= max_notes: break
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip(): continue
        rel = str(path.relative_to(vault)); nid = upsert_node(conn, note_type(path), title_from_text(path, text), rel, metadata={"path":rel,"chars":len(text)}); notes += 1
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


def get_node(conn, node_id):
    row=conn.execute("SELECT id,type,name,source_path,metadata_json FROM nodes WHERE id=?",(node_id,)).fetchone()
    return {} if not row else {"id":row[0],"type":row[1],"name":row[2],"source_path":row[3],"metadata":json.loads(row[4] or "{}")}


def neighbors(conn, node_id):
    rows=conn.execute("""SELECT e.relation,n.id,n.name FROM edges e JOIN nodes n ON n.id=e.dst_id WHERE e.src_id=? UNION ALL SELECT 'reverse_'||e.relation,n.id,n.name FROM edges e JOIN nodes n ON n.id=e.src_id WHERE e.dst_id=?""",(node_id,node_id)).fetchall()
    return [(r,i,n) for r,i,n in rows]


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
        def weight(item):
            rel,nid,name=item; node=get_node(conn,nid); ntype=node.get("type",""); low=name.lower(); score=1.0
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


def observations_for_seed(db_path: Path, seed_id: str, limit: int = 4):
    conn=sqlite3.connect(db_path); rows=conn.execute("SELECT text FROM observations WHERE note_id=? ORDER BY score DESC LIMIT ?",(seed_id,limit)).fetchall(); conn.close(); return [r[0] for r in rows]


def generate_thought(db_path: Path, path):
    seed=path[0]; names=[n.get("name","?") for n in path]; obs=observations_for_seed(db_path, seed["id"], 4); low=" ".join(names+obs).lower()
    if any(w in low for w in ["blocked","needs","awaiting","unresolved","todo"]):
        title="Open loop hiding in the graph"; insight=f"{names[0]} is connected to an unresolved thread. The useful move is to compress it into one concrete next action."; action=obs[0] if obs else "Pick the smallest next action and attach it to the source note."
    elif any(w in low for w in ["due","deadline","expires","urgent","overdue"]):
        title="Deadline path worth checking"; insight=f"This path links {names[0]} to time-sensitive language. Verify the status before it becomes background noise."; action=obs[0] if obs else "Check whether the deadline/status is still current."
    else:
        title="Graph thought"; joined=" → ".join(names[:5]); insight=f"The notes currently associate: {joined}. This may be worth revisiting because nearby nodes keep connecting."; action=obs[0] if obs else "If this still matters, promote it to an explicit next action."
    return {"title":title,"insight":insight,"action":action,"path":path,"observations":obs}


def save_thought(db_path: Path, thought: dict, image_path: str | None = None):
    conn=sqlite3.connect(db_path); tid=hashlib.sha1((thought["title"]+json.dumps([n["id"] for n in thought["path"]])+now_iso()).encode()).hexdigest()[:16]
    conn.execute("INSERT INTO thoughts(id,seed_id,path_json,title,insight,action,image_path,created_at) VALUES(?,?,?,?,?,?,?,?)",(tid,thought["path"][0].get("id"),json.dumps(thought["path"],ensure_ascii=False),thought["title"],thought["insight"],thought["action"],image_path,now_iso()))
    conn.commit(); conn.close(); return tid
