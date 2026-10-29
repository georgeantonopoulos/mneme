"""The cortex: neurons, synapses and recall.

Neurons are immutable episodes from ``senses``. Synapses are created
deterministically at ingest: same email thread or chat conversation, same
note, a wikilink, or a shared rare entity (a person, an email address, an
identifier such as an invoice number). Entity synapses are weighted by
inverse frequency so hubs like "Ivy" don't connect everything.

Recall:
  1. seed       FTS5/BM25 over title, text and derived terms (codes, dates, word forms)
  2. habituate  collapse near-identical neurons (weekly events, filler, bulk mail) to one representative
  3. spread     activation flows one or two hops along synapses from the seeds
  4. modulate   time window, recency for "current" questions, cancelled/draft status, trust
  5. select     diverse top-k, returned as raw text with date, source and trust label
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import text as T
from .senses import Episode, read_sources

SCHEMA = """
CREATE TABLE IF NOT EXISTS neurons (
    n INTEGER PRIMARY KEY,
    id TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    doc TEXT NOT NULL,
    refs TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    known_at TEXT NOT NULL,
    event_time TEXT,
    thread TEXT,
    trust TEXT NOT NULL,
    trust_reason TEXT NOT NULL,
    status TEXT NOT NULL,
    habit_key TEXT NOT NULL,
    dates TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS neuron_fts USING fts5(title, text, extra, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS entities (n INTEGER NOT NULL, entity TEXT NOT NULL, PRIMARY KEY (n, entity));
CREATE TABLE IF NOT EXISTS synapses (src INTEGER NOT NULL, dst INTEGER NOT NULL, kind TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY (src, dst, kind));
"""

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
ALIAS_RE = re.compile(r"\b(?:goes by|aka|a\.k\.a\.|known as|called)\s+([A-Z][a-z]+)")
TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")


@dataclass
class Hit:
    id: str
    source: str
    refs: list[str]
    title: str
    text: str
    when: str | None
    trust: str
    trust_reason: str
    status: str
    score: float
    similar: int = 0
    signals: dict = field(default_factory=dict)

    def context_text(self) -> str:
        label = [self.source]
        if self.when:
            label.append(dt.datetime.fromisoformat(self.when).strftime("%a %d %b %Y"))
        if self.status in ("CANCELLED", "draft"):
            label.append(self.status.lower())
        if self.trust == "untrusted":
            label.append(f"UNTRUSTED: {self.trust_reason}")
        elif self.trust == "low":
            label.append(self.trust_reason)
        if self.similar:
            label.append(f"+{self.similar} similar")
        return f"[{' | '.join(label)}] {self.title}\n{self.text}"


def _habit_key(ep: Episode) -> str:
    """Text with dates stripped: repeated stimuli (weekly events, filler, statements) share a key."""
    body = f"{ep.source}|{ep.title}|{ep.text}".lower()
    body = T.ISO_DATE_RE.sub(" ", body)
    body = T.DMY_RE.sub(" ", body)
    body = T.MDY_RE.sub(" ", body)
    body = re.sub(r"\b(" + "|".join(T.WEEKDAYS) + r")\b|\b20\d{2}\b", " ", body)
    return re.sub(r"\s+", " ", body).strip()


class Brain:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._adjacency: dict[int, list[tuple[int, float]]] | None = None

    # ------------------------------------------------------------------ ingest
    def ingest_lifevault(self, root: Path) -> dict:
        return self.ingest(read_sources(Path(root)))

    def ingest(self, episodes: Iterable[Episode]) -> dict:
        episodes = list(episodes)
        people = self._person_lexicon(episodes)
        conn = self.conn
        conn.executescript("DELETE FROM neurons; DELETE FROM neuron_fts; DELETE FROM entities; DELETE FROM synapses;")
        rows: list[tuple[int, Episode, set[str]]] = []
        for n, ep in enumerate(episodes, 1):
            default_year = int((ep.event_time or ep.known_at)[:4])
            blob = f"{ep.title}\n{ep.text}"
            dates = T.mentioned_dates(blob, default_year=default_year)
            if ep.event_time:
                dates = sorted(set(dates) | {dt.datetime.fromisoformat(ep.event_time).date()})
            ents = self._entities(ep, blob, people)
            extra = " ".join(
                [T.IRREGULAR[w] for w in T.words(blob) if w in T.IRREGULAR]
                + [T.code_term(c) for c in T.codes(blob)]
                + [T.date_term(d) for d in dates]
                + [e.split(":", 1)[1] for e in ents if e.startswith("person:")]
            )
            conn.execute(
                "INSERT INTO neurons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (n, ep.id, ep.source, ep.doc, json.dumps(ep.refs), ep.title, ep.text, ep.known_at, ep.event_time, ep.thread,
                 ep.trust, ep.trust_reason, ep.status, _habit_key(ep), json.dumps([d.isoformat() for d in dates])),
            )
            conn.execute("INSERT INTO neuron_fts(rowid, title, text, extra) VALUES (?,?,?,?)", (n, ep.title, ep.text, extra))
            conn.executemany("INSERT OR IGNORE INTO entities VALUES (?,?)", [(n, e) for e in ents])
            rows.append((n, ep, ents))
        synapses = self._grow_synapses(rows)
        conn.executemany("INSERT OR REPLACE INTO synapses VALUES (?,?,?,?)", synapses)
        conn.commit()
        self._adjacency = None
        return {"neurons": len(rows), "synapses": len(synapses)}

    @staticmethod
    def _person_lexicon(episodes: list[Episode]) -> dict[str, str]:
        """alias (lower) -> canonical person name, from People notes, email display names and chat titles."""
        canonical: set[str] = set()
        aliases: dict[str, set[str]] = defaultdict(set)
        for ep in episodes:
            if ep.source == "note" and ep.doc.lower().startswith("people/"):
                name = Path(ep.doc).stem
                canonical.add(name)
                for alias in ALIAS_RE.findall(ep.text):
                    aliases[alias.lower()].add(name)
            if ep.source == "email":
                for display in re.findall(r"^(?:From|To): ([^<\n]+?) <", ep.text, re.M):
                    if len(display.split()) == 2 and display[0].isupper():
                        canonical.add(display.strip())
        lexicon: dict[str, str] = {name.lower(): name for name in canonical}
        firsts: dict[str, set[str]] = defaultdict(set)
        for name in canonical:
            firsts[name.split()[0].lower()].add(name)
        for first, names in firsts.items():
            if len(names) == 1 and first not in lexicon:
                lexicon[first] = next(iter(names))
        for alias, names in aliases.items():
            if len(names) == 1:
                lexicon.setdefault(alias, next(iter(names)))
        return lexicon

    @staticmethod
    def _entities(ep: Episode, blob: str, people: dict[str, str]) -> set[str]:
        ents = {f"code:{c}" for c in T.codes(blob)}
        ents |= {f"addr:{a.lower()}" for a in EMAIL_RE.findall(blob)} | {f"addr:{p}" for p in ep.people if "@" in p}
        ents |= {f"link:{w.strip().lower()}" for w in WIKILINK_RE.findall(blob)}
        low = blob.lower() + " " + " ".join(ep.people)
        for alias, name in people.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", low):
                ents.add(f"person:{name.lower()}")
        if ep.source == "note":
            ents.add(f"link:{Path(ep.doc).stem.lower()}")
        return ents

    @staticmethod
    def _grow_synapses(rows: list[tuple[int, Episode, set[str]]]) -> list[tuple[int, int, str, float]]:
        out: dict[tuple[int, int, str], float] = {}

        def link(a: int, b: int, kind: str, w: float) -> None:
            if a != b:
                out[(a, b, kind)] = max(out.get((a, b, kind), 0.0), w)
                out[(b, a, kind)] = max(out.get((b, a, kind), 0.0), w)

        by_thread: dict[str, list[int]] = defaultdict(list)
        by_doc: dict[str, list[int]] = defaultdict(list)
        by_entity: dict[str, list[int]] = defaultdict(list)
        for n, ep, ents in rows:
            if ep.thread:
                by_thread[ep.thread].append(n)
            by_doc[ep.doc].append(n)
            for e in ents:
                by_entity[e].append(n)
        for members in by_thread.values():
            if len(members) <= 30:
                for i, a in enumerate(members):
                    for b in members[i + 1:]:
                        link(a, b, "thread", 1.0)
        for members in by_doc.values():
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    link(a, b, "same_doc", 0.8)
        for entity, members in by_entity.items():
            if len(members) < 2 or len(members) > 25:
                continue  # unique, or a hub that would connect everything
            weight = 1.0 / math.log(2 + len(members))
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    link(a, b, "entity", weight)
        return [(a, b, kind, round(w, 4)) for (a, b, kind), w in out.items()]

    # ------------------------------------------------------------------ recall
    def _neighbours(self) -> dict[int, list[tuple[int, float]]]:
        if self._adjacency is None:
            adj: dict[int, dict[int, float]] = defaultdict(dict)
            for row in self.conn.execute("SELECT src, dst, weight FROM synapses"):
                adj[row[0]][row[1]] = max(adj[row[0]].get(row[1], 0.0), row[2])
            # Row-normalise, as in a random walk / PPR: a neuron splits its activation across its synapses
            # instead of copying it to each, so dense clusters can't amplify themselves.
            self._adjacency = {}
            for n, d in adj.items():
                total = sum(d.values())
                self._adjacency[n] = sorted(((m, w / total) for m, w in d.items()), key=lambda x: -x[1])
        return self._adjacency

    def recall(self, query: str, *, k: int = 8, as_of: str | None = None, spread: float = 0.35, hops: int = 2,
               ablate: frozenset[str] = frozenset()) -> list[Hit]:
        """Recall up to k hits. ``ablate`` switches mechanisms off for evaluation:
        spread, habituate, time, trust, status, diversity, derived (codes/dates/word forms)."""
        if "spread" in ablate:
            hops = 0
        now = dt.datetime.fromisoformat(as_of) if as_of else dt.datetime.now(dt.timezone.utc)
        now_iso = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
        window = T.time_window(query, now)
        current, past = T.wants_current(query), T.wants_past(query)
        security = bool(re.search(r"\b(scam|phish|spam|suspicious|fraud|security|verify|bank)\w*", query.lower()))

        # 1. seed: BM25 over the FTS index
        match_terms = [f'"{t}"' for t in T.query_terms(query)]
        if "derived" not in ablate:
            match_terms += [T.code_term(c) for c in T.codes(query)]
        if "time" in ablate:
            window, current, past = None, False, False
        if window and window[2] == "day" and "derived" not in ablate:
            day = window[0]
            while day <= window[1]:
                match_terms.append(T.date_term(day))
                day += dt.timedelta(days=1)
        lexical: dict[int, float] = {}
        if match_terms:
            sql = ("SELECT rowid, bm25(neuron_fts, 2.0, 1.0, 1.5) AS s FROM neuron_fts WHERE neuron_fts MATCH ? "
                   "ORDER BY s LIMIT 120")
            for row in self.conn.execute(sql, (" OR ".join(match_terms),)):
                lexical[row[0]] = -row[1]
        if window and window[2] != "day":
            lexical.update({n: lexical.get(n, 0.0) for n in self._in_window(window, now_iso)})
        if not lexical:
            return []
        meta = self._meta(set(lexical))
        lexical = {n: s for n, s in lexical.items() if n in meta and meta[n]["known_at"] <= now_iso}
        if not lexical:
            return []
        top = max(lexical.values()) or 1.0
        activation = {n: s / top for n, s in lexical.items()}

        # 3. spread along synapses from the strongest seeds
        adjacency = self._neighbours()
        frontier = dict(sorted(activation.items(), key=lambda x: -x[1])[:20])
        spread_act: dict[int, float] = defaultdict(float)
        for _ in range(hops):
            nxt: dict[int, float] = defaultdict(float)
            for n, a in frontier.items():
                for m, w in adjacency.get(n, []):
                    nxt[m] += a * w * spread
            for m, a in nxt.items():
                spread_act[m] += a
            frontier = dict(sorted(nxt.items(), key=lambda x: -x[1])[:20])
        meta.update(self._meta(set(spread_act) - set(meta)))
        scores: dict[int, float] = defaultdict(float)
        for n, a in activation.items():
            scores[n] += a
        for n, a in spread_act.items():
            if n in meta and meta[n]["known_at"] <= now_iso:
                scores[n] += min(a, 0.6)

        # 4. modulate by time, status and trust
        for n in list(scores):
            m = meta[n]
            factor = 1.0
            if window:
                dates = set(m["dates"])
                if any(window[0].isoformat() <= d <= window[1].isoformat() for d in dates):
                    factor *= 1.6 if window[2] == "day" else 1.8
                elif window[2] == "future" and m["source"] in ("event", "task") and m["status"] in ("done", "CANCELLED"):
                    factor *= 0.5
            stamp = m["event_time"] or m["known_at"]
            age_days = max(0.0, (now - dt.datetime.fromisoformat(stamp)).total_seconds() / 86400)
            if current and not past:
                factor *= 1.0 + 0.4 * math.exp(-age_days / 45)
            elif past:
                factor *= 1.0 + 0.2 * (1 - math.exp(-age_days / 60))
            if "status" not in ablate and m["status"] == "CANCELLED" and "cancel" not in query.lower():
                factor *= 0.55
            if "status" not in ablate and m["status"] == "draft":
                factor *= 0.4
            if "trust" in ablate:
                pass
            elif m["trust"] == "untrusted":
                factor *= 1.0 if security else 0.35
            elif m["trust"] == "low":
                factor *= 0.75
            scores[n] *= factor

        # 2 + 5. habituate repeated stimuli, then pick a diverse top-k
        habits = {} if "habituate" in ablate else self._habit_groups(set(scores))
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        hits: list[Hit] = []
        per_doc: Counter = Counter()
        used_habits: set[str] = set()
        for n, s in ranked:
            m = meta[n]
            key = m["habit_key"] if "habituate" not in ablate else m["id"]
            if key in used_habits:
                continue
            group = [g for g in habits.get(key, [n]) if g in meta and meta[g]["known_at"] <= now_iso] or [n]
            rep = self._representative(group, meta, now_iso) if len(group) > 1 else n
            rm = meta[rep]
            if "diversity" not in ablate and per_doc[rm["doc"]] >= 2:
                continue
            used_habits.add(key)
            per_doc[rm["doc"]] += 1
            hits.append(Hit(id=rm["id"], source=rm["source"], refs=rm["refs"], title=rm["title"], text=rm["text"],
                            when=rm["event_time"] or (rm["known_at"] if rm["source"] != "note" else None), trust=rm["trust"],
                            trust_reason=rm["trust_reason"], status=rm["status"], score=round(s, 4), similar=len(group) - 1,
                            signals={"lexical": round(activation.get(n, 0.0), 3), "spread": round(spread_act.get(n, 0.0), 3)}))
            if len(hits) >= k:
                break
        return hits

    def _in_window(self, window: tuple[dt.date, dt.date, str], now_iso: str) -> set[int]:
        start, end = window[0].isoformat(), window[1].isoformat()
        out = set()
        for row in self.conn.execute("SELECT n, dates FROM neurons WHERE known_at <= ?", (now_iso,)):
            if any(start <= d <= end for d in json.loads(row["dates"])):
                out.add(row["n"])
        return out

    def _meta(self, ns: set[int]) -> dict[int, dict]:
        if not ns:
            return {}
        marks = ",".join("?" * len(ns))
        out = {}
        for row in self.conn.execute(f"SELECT * FROM neurons WHERE n IN ({marks})", tuple(ns)):
            d = dict(row)
            d["refs"] = json.loads(d["refs"])
            d["dates"] = json.loads(d["dates"])
            out[d["n"]] = d
        return out

    def _habit_groups(self, ns: set[int]) -> dict[str, list[int]]:
        keys = {row[0] for row in self.conn.execute(
            f"SELECT habit_key FROM neurons WHERE n IN ({','.join('?' * len(ns))})", tuple(ns))} if ns else set()
        groups: dict[str, list[int]] = defaultdict(list)
        for key in keys:
            for row in self.conn.execute("SELECT n FROM neurons WHERE habit_key = ?", (key,)):
                groups[key].append(row[0])
        return groups

    def _representative(self, group: list[int], meta: dict[int, dict], now_iso: str) -> int:
        """Next upcoming occurrence if there is one, else the most recent."""
        for n in group:
            if n not in meta:
                meta.update(self._meta({n}))
        stamp = lambda n: meta[n]["event_time"] or meta[n]["known_at"]  # noqa: E731
        upcoming = [n for n in group if stamp(n) >= now_iso]
        return min(upcoming, key=stamp) if upcoming else max(group, key=stamp)
