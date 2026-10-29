#!/usr/bin/env python3
"""Score retrieval systems against the LifeVault questions.

    python eval/lifevault/run_baseline.py [--k 8] [--out eval/lifevault/results]

This is a retrieval-only benchmark: no LLM writes answers. For each question a
system returns ranked items, each tagged with the evidence refs it came from.
We report:

    hit@3 / hit@k     any gold evidence ref in the top 3 / top k
    recall@k          fraction of gold evidence refs found in the top k
    answer_in_ctx@k   every `accept` group has a string present in the top-k text
                      (a proxy for "an LLM could answer from this context")
    stale_in_ctx@k    a `reject` string appears in the top-k text
    forbidden@k       a forbidden ref (e.g. the phishing email) was retrieved

Abstention questions have no gold evidence; they are reported separately.

Systems:
    mneme-retrieve/notes   current `mneme retrieve` over the Markdown vault only
    mneme-retrieve/all     same, with email/calendar/chat/tasks rendered to Markdown
    mneme-think/all        `mneme think` (hash embeddings: no Ollama offline)
    bm25/all               plain Okapi BM25 over small chunks of every source
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import json
import math
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from email import policy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True

from mneme.core import ingest_vault, retrieve_context  # noqa: E402
from mneme.neural import build_latent_index, think  # noqa: E402

DATA = HERE / "data"


# ---------------------------------------------------------------------------
# Corpus: every source as small text units, each tagged with evidence refs
# ---------------------------------------------------------------------------
def _strip_html(html: str) -> str:
    # Deliberately naive, like a careless converter: hidden text survives.
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def load_documents() -> list[dict]:
    """One document per source item: {path, refs, title, text}.

    ``path`` is the Markdown path used when the item is rendered for Mneme.
    """
    docs: list[dict] = []
    vault = DATA / "vault"
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        text = path.read_text(encoding="utf-8")
        ref = f"journal:{path.stem}" if rel.startswith("Journal/") else f"note:{rel}"
        docs.append({"path": rel, "refs": [ref], "title": path.stem, "text": text, "kind": "note"})
    for path in sorted((DATA / "sources" / "email").glob("*.eml")):
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        eid = msg["X-LifeVault-Id"]
        plain = msg.get_body(preferencelist=("plain",))
        html = msg.get_body(preferencelist=("html",))
        body = plain.get_content() if plain else ""
        if html is not None and html is not plain:
            body += "\n" + _strip_html(html.get_content())
        attachments = [part.get_filename() for part in msg.iter_attachments() if part.get_filename()]
        text = (f"# {msg['Subject']}\n\nFrom: {msg['From']}\nTo: {msg['To']}\nDate: {msg['Date']}\n"
                + (f"Attachments: {', '.join(attachments)}\n" if attachments else "") + f"\n{body}")
        docs.append({"path": f"Sources/Email/{eid}.md", "refs": [f"email:{eid}"], "title": msg["Subject"], "text": text, "kind": "email"})
    for block in (DATA / "sources" / "calendar" / "nia.ics").read_text(encoding="utf-8").split("BEGIN:VEVENT")[1:]:
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.split(";")[0]] = value.replace("\\,", ",").replace("\\n", "\n")
        uid = fields["UID"].split("@")[0]
        start = fields["DTSTART"]
        text = (f"# {fields['SUMMARY']}\n\nStart: {start}\nEnd: {fields['DTEND']}\nStatus: {fields['STATUS']}\n"
                + (f"Location: {fields['LOCATION']}\n" if "LOCATION" in fields else ""))
        docs.append({"path": f"Sources/Calendar/{uid}.md", "refs": [f"event:{uid}"], "title": fields["SUMMARY"], "text": text, "kind": "event"})
    by_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in (DATA / "sources" / "chat" / "messages.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by_day[(row["chat"], row["ts"][:10])].append(row)
    for (conversation, day), rows in sorted(by_day.items()):
        slug = re.sub(r"[^a-z0-9]+", "-", conversation.lower()).strip("-")
        text = f"# Chat with {conversation} on {day}\n\n" + "\n".join(f"- {r['ts'][11:16]} {r['from']}: {r['text']}" for r in rows)
        docs.append({"path": f"Sources/Chat/{slug}/{day}.md", "refs": [f"chat:{conversation}@{r['ts']}" for r in rows],
                     "title": f"Chat {conversation} {day}", "text": text, "kind": "chat"})
    for row in json.loads((DATA / "sources" / "tasks" / "tasks.json").read_text(encoding="utf-8")):
        state = f"done {row['completed']}" if row["completed"] else "open"
        text = (f"# {row['title']}\n\n- [{'x' if row['completed'] else ' '}] {row['title']}\n"
                f"Project: {row['project']}\nCreated: {row['created']}\nDue: {row['due'] or 'none'}\nStatus: {state}\n"
                + (f"Notes: {row['notes']}\n" if row["notes"] else ""))
        docs.append({"path": f"Sources/Tasks/{row['id']}.md", "refs": [f"task:{row['id']}"], "title": row["title"], "text": text, "kind": "task"})
    return docs


def write_markdown_vault(docs: list[dict], dest: Path, *, notes_only: bool) -> dict[str, list[str]]:
    refs_by_path: dict[str, list[str]] = {}
    for doc in docs:
        if notes_only and doc["kind"] != "note":
            continue
        path = dest / doc["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc["text"], encoding="utf-8")
        refs_by_path[doc["path"]] = doc["refs"]
    return refs_by_path


# ---------------------------------------------------------------------------
# Systems. Each returns a ranked list of {"refs": [...], "text": str}.
# ---------------------------------------------------------------------------
class MnemeRetrieve:
    def __init__(self, name: str, docs: list[dict], workdir: Path, *, notes_only: bool):
        self.name = name
        vault = workdir / name.replace("/", "_") / "vault"
        self.db = vault.parent / "mneme.sqlite"
        self.refs_by_path = write_markdown_vault(docs, vault, notes_only=notes_only)
        started = time.perf_counter()
        ingest_vault(vault, self.db)
        self.ingest_seconds = time.perf_counter() - started

    def search(self, question: dict, k: int) -> list[dict]:
        result = retrieve_context(self.db, question["question"], max_items=k, budget=100_000, as_of=question["as_of"])
        items = []
        for item in result["items"]:
            text = " ".join(str(item.get(key) or "") for key in ("title", "snippet"))
            items.append({"refs": self.refs_by_path.get(item.get("source_path") or "", []), "text": text})
        return items


class MnemeThink(MnemeRetrieve):
    def __init__(self, name: str, docs: list[dict], workdir: Path):
        super().__init__(name, docs, workdir, notes_only=False)
        build_latent_index(self.db, provider="hash", model="hash-v1")

    def search(self, question: dict, k: int) -> list[dict]:
        result = think(self.db, question["question"], provider="hash", model="hash-v1", limit=k, now=question["as_of"])
        items = []
        for neuron in result["activated_neurons"]:
            evidence = " ".join(e.get("text", "") for e in neuron.get("evidence", []))
            items.append({"refs": self.refs_by_path.get(neuron.get("source_path") or "", []), "text": f"{neuron.get('name', '')} {evidence}"})
        return items


STOP = set("""a an and are as at be been but by can could did do does for from had has have how i if in is it its
me my of on or our so than that the their them then there these they this to too was we were what when where
which who whom why will with would you your yet am any all about into up out over just not no""".split())
WORD_RE = re.compile(r"[a-z0-9£#]+(?:[-.][a-z0-9]+)*")


def _tokens(text: str) -> list[str]:
    out = []
    for word in WORD_RE.findall(text.lower()):
        if word in STOP:
            continue
        out.append(word)
        if "-" in word:
            out.extend(part for part in word.split("-") if part and part not in STOP)
    return out


class BM25:
    """Okapi BM25 over small chunks: one per email/event/task/chat-day, one per note block."""

    name = "bm25/all"

    def __init__(self, docs: list[dict], k1: float = 1.2, b: float = 0.75):
        self.chunks: list[dict] = []
        for doc in docs:
            if doc["kind"] != "note":
                self.chunks.append({"refs": doc["refs"], "text": doc["text"]})
                continue
            body = re.sub(r"^---.*?---\n", "", doc["text"], flags=re.S)
            for block in re.split(r"\n(?=#)|\n\s*\n", body):
                if block.strip():
                    self.chunks.append({"refs": doc["refs"], "text": f"{doc['title']}\n{block.strip()}"})
        started = time.perf_counter()
        self.tf = [Counter(_tokens(c["text"])) for c in self.chunks]
        self.lengths = [sum(tf.values()) for tf in self.tf]
        self.avg = sum(self.lengths) / len(self.lengths)
        df = Counter(term for tf in self.tf for term in tf)
        n = len(self.chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self.k1, self.b = k1, b
        self.ingest_seconds = time.perf_counter() - started

    def search(self, question: dict, k: int) -> list[dict]:
        terms = _tokens(question["question"])
        scored = []
        for i, tf in enumerate(self.tf):
            score = 0.0
            for term in terms:
                if term in tf:
                    f = tf[term]
                    score += self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg))
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.chunks[i] for _, i in scored[:k]]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(question: dict, items: list[dict], k: int) -> dict:
    gold = set(question["evidence"])
    ranked_refs: list[set[str]] = [set(item["refs"]) for item in items[:k]]
    first_hit = next((rank for rank, refs in enumerate(ranked_refs, 1) if refs & gold), None)
    found = set().union(*ranked_refs) & gold if ranked_refs else set()
    context = " ".join(item["text"] for item in items[:k]).lower()
    answer_in_ctx = bool(question["accept"]) and all(any(s.lower() in context for s in group) for group in question["accept"])
    return {
        "id": question["id"],
        "split": question.get("split", "dev"),
        "category": question["category"],
        "returned": len(items[:k]),
        "first_hit_rank": first_hit,
        "hit@3": bool(first_hit and first_hit <= 3),
        "hit@k": bool(first_hit),
        "recall@k": round(len(found) / len(gold), 3) if gold else None,
        "answer_in_ctx@k": answer_in_ctx if question["accept"] else None,
        "stale_in_ctx@k": any(s.lower() in context for s in question["reject"]),
        "forbidden@k": bool(set(question["forbidden"]) & set().union(*ranked_refs)) if ranked_refs else False,
    }


def summarise(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["recall@k"] is not None]
    graded = [r for r in rows if r["answer_in_ctx@k"] is not None]
    mean = lambda vals: round(sum(vals) / len(vals), 3) if vals else None  # noqa: E731
    return {
        "questions": len(rows),
        "hit@3": mean([r["hit@3"] for r in answerable]),
        "hit@k": mean([r["hit@k"] for r in answerable]),
        "recall@k": mean([r["recall@k"] for r in answerable]),
        "mrr": mean([1 / r["first_hit_rank"] if r["first_hit_rank"] else 0 for r in answerable]),
        "answer_in_ctx@k": mean([r["answer_in_ctx@k"] for r in graded]),
        "stale_in_ctx@k": mean([r["stale_in_ctx@k"] for r in rows]),
        "forbidden@k": sum(r["forbidden@k"] for r in rows),
    }


def build_systems(names: list[str] | None, docs: list[dict], work: Path) -> list:
    factories = {
        "mneme-retrieve/notes": lambda: MnemeRetrieve("mneme-retrieve/notes", docs, work, notes_only=True),
        "mneme-retrieve/all": lambda: MnemeRetrieve("mneme-retrieve/all", docs, work, notes_only=False),
        "mneme-think/all": lambda: MnemeThink("mneme-think/all", docs, work),
        "bm25/all": lambda: BM25(docs),
        "cortex/all": lambda: Cortex(work),
    }
    return [factories[name]() for name in (names or list(factories))]


class Cortex:
    """The rebuilt core (``mneme.cortex``), reading the raw LifeVault sources directly."""

    name = "cortex/all"

    def __init__(self, work: Path):
        from mneme.cortex import Brain

        self.brain = Brain(work / "cortex.sqlite")
        started = time.perf_counter()
        self.brain.ingest_lifevault(DATA)
        self.ingest_seconds = time.perf_counter() - started

    def search(self, question: dict, k: int) -> list[dict]:
        return [{"refs": hit.refs, "text": hit.context_text()} for hit in self.brain.recall(question["question"], k=k, as_of=question["as_of"])]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score retrieval systems on LifeVault")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--systems", nargs="*", help="Subset of systems to run (default: all)")
    parser.add_argument("--no-write", action="store_true", help="Print only; do not overwrite results/")
    args = parser.parse_args()
    questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    docs = load_documents()
    report = {"k": args.k, "fixture_now": json.loads((DATA / "manifest.json").read_text())["now"],
              "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "systems": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for system in build_systems(args.systems, docs, Path(tmp)):
            rows, latencies = [], []
            for question in questions:
                started = time.perf_counter()
                items = system.search(question, args.k)
                latencies.append(time.perf_counter() - started)
                rows.append(score(question, items, args.k))
            dev = [r for r in rows if r["split"] == "dev"]
            holdout = [r for r in rows if r["split"] == "holdout"]
            by_category: dict[str, list[dict]] = defaultdict(list)
            for row in dev:
                by_category[row["category"]].append(row)
            latencies.sort()
            report["systems"][system.name] = {
                "summary": summarise(dev),
                "holdout": summarise(holdout),
                "by_category": {cat: summarise(cat_rows) for cat, cat_rows in sorted(by_category.items())},
                "latency_ms": {"p50": round(latencies[len(latencies) // 2] * 1000, 1), "p95": round(latencies[int(len(latencies) * 0.95)] * 1000, 1)},
                "ingest_seconds": round(system.ingest_seconds, 2),
                "per_question": dev,
                "per_question_holdout": holdout,
            }
    if not args.no_write:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "baseline.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for split in ("summary", "holdout"):
        print(f"\n[{'dev' if split == 'summary' else 'holdout'}]")
        print(f"{'system':24} {'hit@3':>6} {'hit@k':>6} {'recall':>7} {'mrr':>6} {'ans_ctx':>8} {'stale':>6} {'forbid':>6} {'p50ms':>7}")
        for name, data in report["systems"].items():
            s = data[split]
            print(f"{name:24} {s['hit@3']:>6} {s['hit@k']:>6} {s['recall@k']:>7} {s['mrr']:>6} {s['answer_in_ctx@k']:>8} {s['stale_in_ctx@k']:>6} {s['forbidden@k']:>6} {data['latency_ms']['p50']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
