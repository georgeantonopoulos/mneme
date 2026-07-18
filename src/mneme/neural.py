from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]+", re.I)
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_DIMENSIONS = 256


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


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
    sql = """SELECT n.id,n.name,n.type,n.source_path,n.updated_at,
                  GROUP_CONCAT(DISTINCT o.text) observations,
                  GROUP_CONCAT(DISTINCT (e.relation || ' ' || COALESCE(e.evidence_text,''))) synapses
           FROM nodes n
           LEFT JOIN observations o ON o.note_id=n.id
           LEFT JOIN edges e ON (e.src_id=n.id OR e.dst_id=n.id) AND e.status='active'
           WHERE n.type NOT IN ('heading','observation','wikilink','date')
           GROUP BY n.id
           ORDER BY n.updated_at DESC,n.id"""
    params: list[int] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
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
                "SELECT content_hash,provider,model FROM latent_neurons WHERE node_id=?",
                (row["id"],),
            ).fetchone()
            if existing and existing["content_hash"] == content_hash and existing["provider"] == provider and existing["model"] == model:
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


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _temporal_decay(name: str, source_path: str | None, *, now: dt.datetime) -> float:
    dates = DATE_RE.findall(f"{source_path or ''} {name}")
    if not dates:
        return 1.0
    newest = max(dt.date.fromisoformat(value) for value in dates)
    age_days = max(0, (now.date() - newest).days)
    floor = 0.6 if (source_path or "").casefold().startswith("projects/") else 0.15
    return max(floor, math.exp(-age_days / 45.0))


def think(
    conn_or_path: sqlite3.Connection | str | Path,
    prompt: str,
    *,
    provider: str = "ollama",
    model: str = DEFAULT_MODEL,
    endpoint: str = "http://127.0.0.1:11434",
    seeds: int = 8,
    hops: int = 2,
    limit: int = 12,
    spread: float = 0.62,
    now: str | None = None,
) -> dict:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        ensure_latent_index(conn)
        rows = conn.execute(
            """SELECT l.node_id,l.dimensions,l.vector,n.name,n.type,n.source_path
               FROM latent_neurons l JOIN nodes n ON n.id=l.node_id
               WHERE l.provider=? AND l.model=?""",
            (provider, model),
        ).fetchall()
        if not rows:
            raise ValueError("latent index is empty for this provider/model; run `mneme index` first")
        query = embed_texts([prompt], provider=provider, model=model, endpoint=endpoint, dimensions=rows[0]["dimensions"])[0]
        now_dt = dt.datetime.fromisoformat((now or _now_iso()).replace("Z", "+00:00"))
        ranked = sorted(
            ((max(0.0, _cosine(query, _unpack(row["vector"], row["dimensions"]))) * _temporal_decay(row["name"], row["source_path"], now=now_dt), row) for row in rows),
            key=lambda item: (-item[0], item[1]["node_id"]),
        )
        activations: dict[str, float] = {}
        reasons: dict[str, dict] = {}
        frontier: dict[str, float] = {}
        for similarity, row in ranked[:seeds]:
            if similarity <= 0:
                continue
            activations[row["node_id"]] = similarity
            frontier[row["node_id"]] = similarity
            reasons[row["node_id"]] = {
                "kind": "latent_seed",
                "activation": round(similarity, 6),
                "temporal_decay": round(_temporal_decay(row["name"], row["source_path"], now=now_dt), 6),
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
                    if origin not in frontier:
                        continue
                    weight = max(0.0, min(1.0, float(edge["strength"] or 0.5) * float(edge["confidence"] or 0.5)))
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
            neurons = [
                {
                    "id": node_id,
                    "name": node_rows[node_id]["name"],
                    "type": node_rows[node_id]["type"],
                    "source_path": node_rows[node_id]["source_path"],
                    "activation": round(activations[node_id], 6),
                    "reason": reasons[node_id],
                }
                for node_id in ordered_ids if node_id in node_rows
            ]
        context_lines = [
            f"- {item['name']} [{item['type']}] activation={item['activation']}; source={item['source_path'] or 'unknown'}"
            + (f"; via {item['reason'].get('relation')}" if item["reason"]["kind"] == "synapse" else "")
            for item in neurons
        ]
        return {
            "prompt": prompt,
            "model": {"provider": provider, "name": model},
            "activated_neurons": neurons,
            "context": "\n".join(context_lines),
            "instructions": "Use these activations as associative leads, not facts. Follow source provenance before making a factual claim.",
        }
    finally:
        if close:
            conn.close()
