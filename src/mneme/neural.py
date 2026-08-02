from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import struct
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

from .contract import CONTRACT_NAME, CONTRACT_VERSION

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]+", re.I)
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_DIMENSIONS = 256
DEFAULT_LEXICAL_SEEDS = 2
LEXICAL_SCORE_SCALE = 15.0
LEXICAL_ACTIVATION_CAP = 0.9
EVIDENCE_TEXT_LIMIT = 600
ACTION_INTENT_TOKENS = frozenset(
    {
        "action", "attention", "blocked", "deadline", "deadlines", "due", "need", "needs",
        "overdue", "pending", "task", "tasks", "todo", "urgent",
    }
)
OPERATOR_SOURCE_FILES = frozenset({"agents.md", "heartbeat.md", "soul.md", "user.md"})

# Ordinary English function words filtered from lexical query routing so that
# stopword-only overlap (e.g. "is", "for", "and") cannot seed a match. Deliberately
# excludes anything that could double as a person/project name.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
        "had", "has", "have", "here", "how", "i", "if", "in", "into", "is", "it", "its", "of",
        "on", "or", "our", "that", "the", "their", "there", "these", "this", "those", "to",
        "was", "were", "what", "when", "where", "which", "who", "why", "will", "with", "you",
        "your", "me", "my", "we", "us", "do", "does", "did", "not", "no", "yes", "can", "could",
        "would", "should", "about", "above", "after", "again", "all", "also", "am", "any",
        "because", "before", "below", "between", "both", "during", "each", "few", "further",
        "just", "more", "most", "one", "only", "other", "over", "own", "same", "so", "some",
        "such", "than", "then", "too", "under", "until", "up", "very", "while",
    }
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _source_is_retrieval_eligible(source_path: str | None) -> bool:
    """Keep operator control files and intentionally retired evidence out of recall."""
    if not source_path:
        return True
    parts = [part for part in source_path.replace("\\", "/").casefold().split("/") if part]
    if not parts:
        return True
    if any(part in {"archive", "archives", "context", "merged-duplicates"} for part in parts[:-1]):
        return False
    filename = parts[-1]
    return filename not in OPERATOR_SOURCE_FILES and not filename.endswith("_ops.md")


def _retrieval_eligibility_sql(column: str) -> str:
    """SQL equivalent of _source_is_retrieval_eligible for bounded preselection."""
    path = f"LOWER('/' || COALESCE({column},''))"
    return f"""(
        {path} NOT GLOB '*/archive/*'
        AND {path} NOT GLOB '*/archives/*'
        AND {path} NOT GLOB '*/context/*'
        AND {path} NOT GLOB '*/merged-duplicates/*'
        AND {path} NOT GLOB '*/*_ops.md'
        AND {path} NOT GLOB '*/agents.md'
        AND {path} NOT GLOB '*/heartbeat.md'
        AND {path} NOT GLOB '*/soul.md'
        AND {path} NOT GLOB '*/user.md'
    )"""


def _is_action_prompt(prompt: str) -> bool:
    return bool({token.casefold() for token in TOKEN_RE.findall(prompt)} & ACTION_INTENT_TOKENS)


def _intent_multiplier(prompt: str, row: sqlite3.Row) -> float:
    if not _is_action_prompt(prompt):
        return 1.0
    node_type = (row["type"] or "").casefold()
    source_path = (row["source_path"] or "").casefold()
    if node_type == "task" or source_path.startswith(("task:", "gws://tasks/")):
        return 1.0
    if node_type == "project":
        return 0.95
    if node_type == "person":
        normalized_prompt = " ".join(TOKEN_RE.findall(prompt.casefold()))
        normalized_name = " ".join(TOKEN_RE.findall((row["name"] or "").casefold()))
        return 1.0 if normalized_name and normalized_name in normalized_prompt else 0.7
    if node_type == "note":
        return 0.82
    return 0.85


def ensure_latent_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS latent_neurons(
               node_id TEXT PRIMARY KEY,
               provider TEXT NOT NULL,
               model TEXT NOT NULL,
               dimensions INTEGER NOT NULL,
               content_hash TEXT NOT NULL,
               vector BLOB NOT NULL,
               indexed_at TEXT NOT NULL,
               FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_latent_neurons_model ON latent_neurons(provider,model)")


def _normalize(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


def _hash_embed(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """Dependency-free signed feature hashing; deterministic fallback, not semantic inference."""
    vector = [0.0] * dimensions
    tokens = TOKEN_RE.findall(text.casefold())
    features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        vector[bucket] += 1.0 if digest[4] & 1 else -1.0
    return _normalize(vector)


def _ollama_embed(texts: list[str], *, model: str, endpoint: str) -> list[list[float]]:
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/embed",
        data=json.dumps({"model": model, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"local Ollama embedding failed ({exc.code}): {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"local Ollama embedding failed: {exc}") from exc
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError("local Ollama returned an invalid embedding payload")
    return [_normalize(vector) for vector in embeddings]


def embed_texts(
    texts: list[str],
    *,
    provider: str = "ollama",
    model: str = DEFAULT_MODEL,
    endpoint: str = "http://127.0.0.1:11434",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> list[list[float]]:
    if provider == "hash":
        return [_hash_embed(text, dimensions) for text in texts]
    if provider == "ollama":
        return _ollama_embed(texts, model=model, endpoint=endpoint)
    raise ValueError("provider must be 'ollama' or 'hash'")


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes, dimensions: int) -> tuple[float, ...]:
    return struct.unpack(f"<{dimensions}f", blob)


def _neuron_rows(conn: sqlite3.Connection, *, limit: int | None = None) -> list[sqlite3.Row]:
    # Bound the candidate set before joining evidence. The former query applied
    # LIMIT after aggregating every node and multiplied observations by edges,
    # making a 1,000-neuron no-op index take tens of seconds on a modest graph.
    limit_sql = "" if limit is None else " LIMIT ?"
    params: list[int] = [] if limit is None else [limit]
    eligibility_sql = _retrieval_eligibility_sql("source_path")
    sql = f"""WITH selected AS (
                  SELECT id,name,type,source_path,updated_at
                  FROM nodes
                  WHERE type NOT IN ('heading','observation','wikilink','date')
                    AND {eligibility_sql}
                  ORDER BY updated_at DESC,id{limit_sql}
              ),
              observation_items AS (
                  SELECT DISTINCT o.note_id AS node_id,o.text
                  FROM observations o JOIN selected s ON s.id=o.note_id
                  WHERE o.text IS NOT NULL AND o.text <> ''
                  ORDER BY o.note_id,o.text
              ),
              observation_text AS (
                  SELECT node_id,GROUP_CONCAT(text, CHAR(10)) AS observations
                  FROM observation_items
                  GROUP BY node_id
              ),
              edge_items AS (
                  SELECT e.src_id AS node_id,
                         e.relation || ' ' || COALESCE(e.evidence_text,'') AS item
                  FROM edges e
                  JOIN selected s ON s.id=e.src_id
                  JOIN selected other ON other.id=e.dst_id
                  WHERE e.status='active'
                    AND COALESCE(e.strength,0.5) > 0
                    AND COALESCE(e.confidence,0.5) > 0
                  UNION
                  SELECT e.dst_id AS node_id,
                         e.relation || ' ' || COALESCE(e.evidence_text,'') AS item
                  FROM edges e
                  JOIN selected s ON s.id=e.dst_id
                  JOIN selected other ON other.id=e.src_id
                  WHERE e.status='active'
                    AND COALESCE(e.strength,0.5) > 0
                    AND COALESCE(e.confidence,0.5) > 0
              ),
              synapse_text AS (
                  SELECT node_id,GROUP_CONCAT(item, CHAR(10)) AS synapses
                  FROM edge_items
                  GROUP BY node_id
              )
              SELECT s.id,s.name,s.type,s.source_path,s.updated_at,
                     o.observations,e.synapses
              FROM selected s
              LEFT JOIN observation_text o ON o.node_id=s.id
              LEFT JOIN synapse_text e ON e.node_id=s.id
              ORDER BY s.updated_at DESC,s.id"""
    return conn.execute(sql, params).fetchall()


def _neuron_text(row: sqlite3.Row) -> str:
    return "\n".join(
        value for value in (
            row["name"],
            row["type"],
            row["source_path"],
            row["observations"],
            row["synapses"],
        ) if value
    )[:1500]


def build_latent_index(
    conn_or_path: sqlite3.Connection | str | Path,
    *,
    provider: str = "ollama",
    model: str = DEFAULT_MODEL,
    endpoint: str = "http://127.0.0.1:11434",
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = 32,
    max_neurons: int | None = None,
    rebuild: bool = False,
) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        ensure_latent_index(conn)
        if rebuild:
            conn.execute("DELETE FROM latent_neurons")
        rows = _neuron_rows(conn, limit=max_neurons)
        selected_ids = {row["id"] for row in rows}
        existing_ids = {row[0] for row in conn.execute("SELECT node_id FROM latent_neurons").fetchall()}
        stale_ids = existing_ids - selected_ids
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"DELETE FROM latent_neurons WHERE node_id IN ({placeholders})",
                sorted(stale_ids),
            )
        pending: list[tuple[sqlite3.Row, str, str]] = []
        for row in rows:
            text = _neuron_text(row)
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "SELECT content_hash,provider,model,dimensions FROM latent_neurons WHERE node_id=?",
                (row["id"],),
            ).fetchone()
            if (
                existing
                and existing["content_hash"] == content_hash
                and existing["provider"] == provider
                and existing["model"] == model
                and (provider != "hash" or existing["dimensions"] == dimensions)
            ):
                continue
            pending.append((row, text, content_hash))
        indexed = 0
        resolved_dimensions = dimensions
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            vectors = embed_texts(
                [item[1] for item in batch],
                provider=provider,
                model=model,
                endpoint=endpoint,
                dimensions=dimensions,
            )
            for (row, _text, content_hash), vector in zip(batch, vectors):
                resolved_dimensions = len(vector)
                conn.execute(
                    """INSERT INTO latent_neurons(node_id,provider,model,dimensions,content_hash,vector,indexed_at)
                       VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(node_id) DO UPDATE SET
                         provider=excluded.provider,model=excluded.model,dimensions=excluded.dimensions,
                         content_hash=excluded.content_hash,vector=excluded.vector,indexed_at=excluded.indexed_at""",
                    (row["id"], provider, model, len(vector), content_hash, _pack(vector), _now_iso()),
                )
                indexed += 1
            conn.commit()
        conn.commit()
        if indexed == 0:
            stored = conn.execute(
                "SELECT dimensions FROM latent_neurons WHERE provider=? AND model=? LIMIT 1",
                (provider, model),
            ).fetchone()
            if stored is not None:
                resolved_dimensions = int(stored[0])
        return {
            "neurons": len(rows),
            "indexed": indexed,
            "unchanged": len(rows) - indexed,
            "removed": len(stale_ids),
            "provider": provider,
            "model": model,
            "dimensions": resolved_dimensions,
        }
    finally:
        if close:
            conn.close()
        else:
            conn.row_factory = original_row_factory


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _entity_tokens(row: sqlite3.Row) -> set[str]:
    tokens = TOKEN_RE.findall(f"{row['name']} {row['type']} {row['source_path'] or ''}".casefold())
    return {token for token in tokens if token not in STOPWORDS}


def _document_frequency(rows: list[sqlite3.Row]) -> dict[str, int]:
    frequency: dict[str, int] = {}
    for row in rows:
        for token in _entity_tokens(row):
            frequency[token] = frequency.get(token, 0) + 1
    return frequency


def _lexical_matches(
    prompt: str, rows: list[sqlite3.Row], document_frequency: dict[str, int], total: int
) -> dict[str, tuple[float, set[str]]]:
    """Score neurons by rare/exact prompt tokens; common tokens (high df) contribute ~0 via idf."""
    query_tokens = {
        token
        for token in TOKEN_RE.findall(prompt.casefold())
        if token not in STOPWORDS and token not in ACTION_INTENT_TOKENS
    }
    if not query_tokens or total == 0:
        return {}
    normalized_prompt = _normalize_phrase(prompt)
    matches: dict[str, tuple[float, set[str]]] = {}
    for row in rows:
        matched = query_tokens & _entity_tokens(row)
        if not matched:
            continue
        score = sum(math.log(total / document_frequency[token]) for token in matched)
        normalized_name = _normalize_phrase(row["name"] or "")
        if normalized_name and re.search(rf"(?<!\w){re.escape(normalized_name)}(?!\w)", normalized_prompt):
            score = max(score, LEXICAL_SCORE_SCALE * LEXICAL_ACTIVATION_CAP)
        if score > 0:
            matches[row["node_id"]] = (score, matched)
    return matches


DEFAULT_EVIDENCE_CAP = 3


def _normalize_phrase(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def _compact_evidence_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > EVIDENCE_TEXT_LIMIT:
        return text[: EVIDENCE_TEXT_LIMIT - 3].rstrip() + "..."
    return text


def _gws_time(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _sense_event_text(row: sqlite3.Row) -> str | None:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    gws = metadata.get("gws") if isinstance(metadata, dict) else None
    gws = gws if isinstance(gws, dict) else {}
    title = (row["title"] or "").strip()
    start = _gws_time(gws.get("start"))
    end = _gws_time(gws.get("end"))
    description = gws.get("description")
    description = description.strip() if isinstance(description, str) else ""
    parts = [title] if title else []
    if start and end:
        parts.append(f"{start} - {end}")
    elif start:
        parts.append(start)
    if description:
        parts.append(description)
    text = "; ".join(part for part in parts if part)
    return text or None


def _hydrate_evidence(conn: sqlite3.Connection, node_ids: list[str], *, cap: int = DEFAULT_EVIDENCE_CAP) -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = {node_id: [] for node_id in node_ids}
    if not node_ids:
        return evidence
    seen: dict[str, set[str]] = {node_id: set() for node_id in node_ids}

    def _add(node_id: str, item: dict) -> None:
        bucket = evidence.get(node_id)
        text = _compact_evidence_text(item.get("text"))
        if bucket is None or len(bucket) >= cap or not text or text in seen[node_id]:
            return
        seen[node_id].add(text)
        bucket.append({**item, "text": text})

    placeholders = ",".join("?" for _ in node_ids)
    for row in conn.execute(
        f"""SELECT note_id,kind,text,source_path FROM observations
            WHERE note_id IN ({placeholders})
            ORDER BY score DESC,id""",
        node_ids,
    ).fetchall():
        _add(row["note_id"], {"kind": row["kind"], "text": row["text"], "source_path": row["source_path"]})

    seen_event_nodes: set[str] = set()
    for row in conn.execute(
        f"""SELECT n.id AS node_id,se.event_type,se.title,se.source_uri,se.metadata_json
            FROM nodes n JOIN sense_events se ON se.source_uri=n.source_path
            WHERE n.id IN ({placeholders}) AND n.source_path IS NOT NULL AND n.source_path <> ''
            ORDER BY n.id,se.ingested_at DESC,se.observed_at DESC,se.id DESC""",
        node_ids,
    ).fetchall():
        if row["node_id"] in seen_event_nodes:
            continue
        seen_event_nodes.add(row["node_id"])
        text = _sense_event_text(row)
        if text is None:
            continue
        _add(row["node_id"], {"kind": "sense_event", "event_type": row["event_type"], "text": text, "source_path": row["source_uri"]})

    for row in conn.execute(
        f"""SELECT id,src_id,dst_id,relation,source_path,evidence_text FROM edges
            WHERE status='active' AND COALESCE(strength,0.5) > 0 AND COALESCE(confidence,0.5) > 0
              AND (src_id IN ({placeholders}) OR dst_id IN ({placeholders}))
            ORDER BY id""",
        node_ids + node_ids,
    ).fetchall():
        if not row["evidence_text"]:
            continue
        item = {"kind": "edge", "relation": row["relation"], "text": row["evidence_text"], "source_path": row["source_path"]}
        for node_id in (row["src_id"], row["dst_id"]):
            _add(node_id, item)
    return evidence


def _context_line(item: dict) -> str:
    line = f"- {item['name']} [{item['type']}] activation={item['activation']}; source={item['source_path'] or 'unknown'}"
    if item["reason"]["kind"] == "synapse":
        line += f"; via {item['reason'].get('relation')}"
    if item["evidence"]:
        excerpt = item["evidence"][0]["text"]
        if len(excerpt) > 140:
            excerpt = excerpt[:137] + "..."
        line += f"; evidence: {excerpt}"
    return line


def _decay_for_date(event_date: dt.date, source_path: str | None, *, now: dt.datetime) -> float:
    comparison_date = now.astimezone(dt.timezone.utc).date() if now.tzinfo is not None else now.date()
    age_days = max(0, (comparison_date - event_date).days)
    floor = 0.6 if (source_path or "").casefold().startswith("projects/") else 0.15
    return max(floor, math.exp(-age_days / 45.0))


def _temporal_decay(name: str, source_path: str | None, *, now: dt.datetime) -> float:
    dates = DATE_RE.findall(f"{source_path or ''} {name}")
    if not dates:
        return 1.0
    newest = max(dt.date.fromisoformat(value) for value in dates)
    return _decay_for_date(newest, source_path, now=now)


def _parse_gws_date(value: str) -> dt.date | None:
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed.date()
    except ValueError:
        return None


def _gws_event_date(gws: dict) -> dt.date | None:
    """Prefer the event's end time for decay purposes; fall back to start."""
    for key in ("end", "start"):
        raw = _gws_time(gws.get(key))
        if raw is None:
            continue
        parsed = _parse_gws_date(raw)
        if parsed is not None:
            return parsed
    return None


def _event_dates_by_source(conn: sqlite3.Connection, source_paths: Iterable[str]) -> dict[str, dt.date]:
    """Load structured GWS event dates from sense_events, keyed by source_uri.

    sense_events.observed_at is ingestion time, not event time, and is never
    consulted here -- only metadata_json.gws.start/end represent when the
    event actually occurs.
    """
    paths = [path for path in dict.fromkeys(source_paths) if path]
    if not paths:
        return {}
    placeholders = ",".join("?" for _ in paths)
    dates: dict[str, dt.date] = {}
    for row in conn.execute(
        f"""SELECT source_uri,metadata_json FROM sense_events
            WHERE source_uri IN ({placeholders})
            ORDER BY source_uri,ingested_at DESC,observed_at DESC,id DESC""",
        paths,
    ).fetchall():
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        gws = metadata.get("gws") if isinstance(metadata, dict) else None
        if not isinstance(gws, dict):
            continue
        event_date = _gws_event_date(gws)
        if event_date is not None:
            dates.setdefault(row["source_uri"], event_date)
    return dates


def _effective_temporal_decay(row: sqlite3.Row, event_dates: dict[str, dt.date], *, now: dt.datetime) -> float:
    source_path = row["source_path"]
    event_date = event_dates.get(source_path) if source_path else None
    if event_date is not None:
        return _decay_for_date(event_date, source_path, now=now)
    return _temporal_decay(row["name"], source_path, now=now)


def think(
    conn_or_path: sqlite3.Connection | str | Path,
    prompt: str,
    *,
    provider: str = "ollama",
    model: str = DEFAULT_MODEL,
    endpoint: str = "http://127.0.0.1:11434",
    seeds: int = 8,
    lexical_seeds: int = DEFAULT_LEXICAL_SEEDS,
    hops: int = 2,
    limit: int = 12,
    spread: float = 0.62,
    now: str | None = None,
    evidence_cap: int = DEFAULT_EVIDENCE_CAP,
) -> dict:
    if evidence_cap < 0:
        raise ValueError("evidence_cap must be non-negative")
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        ensure_latent_index(conn)
        rows = [
            row
            for row in conn.execute(
                """SELECT l.node_id,l.dimensions,l.vector,n.name,n.type,n.source_path
                   FROM latent_neurons l JOIN nodes n ON n.id=l.node_id
                   WHERE l.provider=? AND l.model=?""",
                (provider, model),
            ).fetchall()
            if _source_is_retrieval_eligible(row["source_path"])
        ]
        if not rows:
            raise ValueError("latent index is empty for this provider/model; run `mneme index` first")
        stored_dimensions = {int(row["dimensions"]) for row in rows}
        if len(stored_dimensions) != 1:
            raise ValueError("latent index contains mixed embedding dimensions; run `mneme index --rebuild`")
        indexed_dimensions = stored_dimensions.pop()
        query = embed_texts([prompt], provider=provider, model=model, endpoint=endpoint, dimensions=indexed_dimensions)[0]
        if len(query) != indexed_dimensions:
            raise ValueError(
                f"embedding dimensions changed from {indexed_dimensions} to {len(query)}; "
                "run `mneme index --rebuild`"
            )
        now_dt = dt.datetime.fromisoformat((now or _now_iso()).replace("Z", "+00:00"))
        event_dates = _event_dates_by_source(conn, (row["source_path"] for row in rows))
        intent_multiplier_by_id = {row["node_id"]: _intent_multiplier(prompt, row) for row in rows}
        document_frequency = _document_frequency(rows)
        lexical_matches = _lexical_matches(prompt, rows, document_frequency, len(rows))
        subject_anchored = bool(lexical_matches) and _is_action_prompt(prompt)
        ranked = sorted(
            (
                (
                    max(0.0, _cosine(query, _unpack(row["vector"], row["dimensions"])))
                    * _effective_temporal_decay(row, event_dates, now=now_dt)
                    * intent_multiplier_by_id[row["node_id"]],
                    row,
                )
                for row in rows
            ),
            key=lambda item: (-item[0], item[1]["node_id"]),
        )
        rows_by_id = {row["node_id"]: row for row in rows}
        decayed_score_by_id = {row["node_id"]: score for score, row in ranked}
        cosine_ranked_ids: list[str] = []
        semantic_only_count = 0
        semantic_only_budget = max(1, seeds // 4) if subject_anchored and seeds > 0 else max(0, seeds)
        for score, row in ranked:
            if len(cosine_ranked_ids) >= max(0, seeds):
                break
            if score <= 0:
                continue
            node_id = row["node_id"]
            if subject_anchored and node_id not in lexical_matches:
                if semantic_only_count >= semantic_only_budget:
                    continue
                semantic_only_count += 1
            cosine_ranked_ids.append(node_id)
        cosine_top_ids = set(cosine_ranked_ids)

        lexical_ranked_ids: list[str] = []
        lexical_extras = 0
        for node_id, _score in sorted(lexical_matches.items(), key=lambda item: (-item[1][0], item[0])):
            if node_id in cosine_top_ids:
                lexical_ranked_ids.append(node_id)
                continue
            if lexical_extras >= max(0, lexical_seeds):
                continue
            lexical_ranked_ids.append(node_id)
            lexical_extras += 1
        lexical_top_ids = set(lexical_ranked_ids)

        activations: dict[str, float] = {}
        reasons: dict[str, dict] = {}
        frontier: dict[str, float] = {}
        seed_ids = list(dict.fromkeys(cosine_ranked_ids + lexical_ranked_ids))
        for node_id in seed_ids:
            row = rows_by_id[node_id]
            decay = _effective_temporal_decay(row, event_dates, now=now_dt)
            intent_multiplier = intent_multiplier_by_id[node_id]
            in_latent = node_id in cosine_top_ids
            in_lexical = node_id in lexical_top_ids

            latent_component = decayed_score_by_id.get(node_id, 0.0) if in_latent else 0.0
            lexical_component = 0.0
            matched_tokens: list[str] = []
            lexical_raw_score = 0.0
            lexical_calibrated_score = 0.0
            if in_lexical:
                raw_score, tokens = lexical_matches[node_id]
                lexical_raw_score = raw_score
                lexical_calibrated_score = min(LEXICAL_ACTIVATION_CAP, raw_score / LEXICAL_SCORE_SCALE)
                lexical_component = lexical_calibrated_score * decay * intent_multiplier
                matched_tokens = sorted(tokens)

            activation = max(latent_component, lexical_component)
            if activation <= 0:
                continue

            if in_latent and in_lexical:
                kind = "hybrid_seed"
            elif in_latent:
                kind = "latent_seed"
            else:
                kind = "lexical_seed"

            signals: dict[str, dict] = {}
            if in_latent:
                signals["latent"] = {"cosine": round(decayed_score_by_id.get(node_id, 0.0), 6)}
            if in_lexical:
                signals["lexical"] = {
                    "raw_score": round(lexical_raw_score, 6),
                    "calibrated_score": round(lexical_calibrated_score, 6),
                    "score": round(lexical_component, 6),
                    "matched_tokens": matched_tokens,
                }

            activations[node_id] = activation
            frontier[node_id] = activation
            reasons[node_id] = {
                "kind": kind,
                "activation": round(activation, 6),
                "temporal_decay": round(decay, 6),
                "intent_multiplier": round(intent_multiplier, 6),
                "signals": signals,
            }
        for hop in range(1, hops + 1):
            if not frontier:
                break
            ids = sorted(frontier)
            placeholders = ",".join("?" for _ in ids)
            edges = conn.execute(
                f"""SELECT e.id,e.src_id,e.dst_id,e.relation,e.status,e.strength,e.confidence,e.source_path,e.evidence_text
                    FROM edges e
                    WHERE e.status='active'
                      AND (e.src_id IN ({placeholders}) OR e.dst_id IN ({placeholders}))""",
                ids + ids,
            ).fetchall()
            next_frontier: dict[str, float] = {}
            for edge in edges:
                for origin, target in ((edge["src_id"], edge["dst_id"]), (edge["dst_id"], edge["src_id"])):
                    if origin not in frontier or target not in rows_by_id:
                        continue
                    strength = 0.5 if edge["strength"] is None else float(edge["strength"])
                    confidence = 0.5 if edge["confidence"] is None else float(edge["confidence"])
                    weight = max(0.0, min(1.0, strength * confidence))
                    activation = frontier[origin] * spread * weight
                    if activation <= activations.get(target, 0.0):
                        continue
                    activations[target] = activation
                    next_frontier[target] = activation
                    reasons[target] = {
                        "kind": "synapse",
                        "from": origin,
                        "edge_id": edge["id"],
                        "relation": edge["relation"],
                        "status": edge["status"],
                        "source_path": edge["source_path"],
                        "evidence": edge["evidence_text"],
                        "hop": hop,
                    }
            frontier = next_frontier
        ordered_ids = [node_id for node_id, _score in sorted(activations.items(), key=lambda item: (-item[1], item[0]))[:limit]]
        if not ordered_ids:
            neurons = []
        else:
            placeholders = ",".join("?" for _ in ordered_ids)
            node_rows = {row["id"]: row for row in conn.execute(f"SELECT id,name,type,source_path FROM nodes WHERE id IN ({placeholders})", ordered_ids)}
            evidence_by_id = _hydrate_evidence(conn, ordered_ids, cap=evidence_cap)
            neurons = [
                {
                    "id": node_id,
                    "name": node_rows[node_id]["name"],
                    "type": node_rows[node_id]["type"],
                    "source_path": node_rows[node_id]["source_path"],
                    "activation": round(activations[node_id], 6),
                    "truth_policy": "provenance_not_fact",
                    "reason": reasons[node_id],
                    "evidence": evidence_by_id.get(node_id, []),
                }
                for node_id in ordered_ids if node_id in node_rows
            ]
        context_lines = [_context_line(item) for item in neurons]
        return {
            "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
            "prompt": prompt,
            "model": {"provider": provider, "name": model},
            "activated_neurons": neurons,
            "context": "\n".join(context_lines),
            "instructions": "Use these activations as associative leads, not facts. Follow source provenance before making a factual claim.",
        }
    finally:
        if close:
            conn.close()
        else:
            conn.row_factory = original_row_factory
