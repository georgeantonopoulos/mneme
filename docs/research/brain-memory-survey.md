# Brain-inspired memory for LLM agents: what the evidence supports

*Survey for the Mneme redesign. Compiled 2026-10-29.*

**How this was researched.** Web search covered arXiv, venue proceedings, official repositories and vendor posts. Direct fetches of arxiv.org were blocked in this session, so I took figures from abstracts, search-indexed paper text and secondary summaries. Where a number comes only from a secondary source, or the sources disagree, the text says so. Check any figure you plan to quote against the paper's own tables.

**Labels used throughout:**
- *Measured* means a result in a paper or reproducible harness.
- *Self-reported* means a vendor or author ran their own comparison.
- *Reproduced* means someone without a stake in the system re-ran it.

---

## 1. The short version

1. **The baselines are much stronger than the brain metaphors suggest.** A late-2026 controlled study, ["Is Complex Agentic Memory Always Needed?"](https://arxiv.org/abs/2610.30755) ([code](https://github.com/Litmeb/RAW-RAG)), used dense retrieval plus reranking over *raw* conversation chunks.
   - It ranked first in 6 of 7 benchmark/model settings across LoCoMo, LongMemEval, MEME and MemoryAgentBench, by margins of 0.13 to 5.53 points.
   - Adding atomic facts or summaries to the index *lowered* scores.
   - Full-context reading still beat everything on one benchmark (MEME: 63.2 vs. about 44).
2. **Graph structure helps on multi-hop and associative questions and often hurts simple lookups.** The controlled comparison [RAG vs. GraphRAG](https://arxiv.org/abs/2502.11371) found the two complementary. KG construction captured only about 65.8% of HotpotQA answer entities. [HippoRAG 2](https://arxiv.org/abs/2502.14802) itself states that earlier structure-augmented methods (GraphRAG, RAPTOR, LightRAG, HippoRAG 1) fall below strong dense retrieval on basic factual memory.
3. **Benchmark numbers for commercial memory products are largely self-reported, mutually disputed, and run under different judges.** LoCoMo also has known answer-key errors.
4. **Some cheap mechanisms are well supported:**
   - fine-grained memory units (turns or facts, not whole sessions)
   - hybrid lexical plus dense retrieval
   - timestamped keys with time-aware query handling
   - a recency × frequency prior (ACT-R / generative-agents style)
   - fact *invalidation*, not deletion, for updates (Zep)
   - Personalized PageRank (PPR) seeded from retrieval hits
5. **Hebbian edge learning, Ebbinghaus forgetting and sleep consolidation have little independent evidence for helping QA accuracy.** Each has at most author-run ablations.

---

## 2. Approach-by-approach

### 2.1 HippoRAG (NeurIPS 2024) and HippoRAG 2 (ICML 2025)

**Mechanism.** HippoRAG is based on hippocampal indexing theory.
- **Indexing.** An LLM performs open information extraction (OpenIE) on each passage, producing triples. The phrases in those triples become KG nodes, and synonym edges link similar phrases by embedding similarity.
- **Querying.** Entities in the query seed a **Personalized PageRank** walk over the KG. Node probabilities are then aggregated back onto passages.
- **HippoRAG 2 changes.** It adds passage nodes to the graph and seeds PPR from query-to-*triple* embedding matches. An LLM "recognition memory" step filters those triples. It also mixes dense passage scores into the seeding.
- Repo: [OSU-NLP-Group/HippoRAG](https://github.com/osu-nlp-group/hipporag).

**Brain mapping.**
- The LLM plus passages play the neocortex (pattern separation and storage).
- The KG plus PPR play the hippocampal index (pattern completion).
- Synonym edges stand in for the parahippocampal region.

**Evidence.**
- [HippoRAG 1](https://proceedings.neurips.cc/paper_files/paper/2024/file/6ddc001d07ca4f319af96a3024f6dbd1-Paper-Conference.pdf):
  - up to about 20% higher Recall@5 on 2WikiMultiHopQA
  - only about 3% higher on MuSiQue
  - single-step retrieval 10–30x cheaper and 6–13x faster than iterative IRCoT, at comparable accuracy
- [HippoRAG 2](https://arxiv.org/abs/2502.14802):
  - average F1 of about 59.8 vs. 57.0 for NV-Embed-v2 across 7 QA sets (secondary summary; check Table 2)
  - +9.5 F1 on 2Wiki, +3.1 on LV-Eval
  - about 7 points better on associativity
  - roughly parity with the dense retriever on NQ and PopQA
- Measured by the authors, with code released. These are Wikipedia-style multi-hop QA sets, not personal memory.
- Follow-ups like [PropRAG](https://arxiv.org/pdf/2504.18070) use it as a baseline. I found no independent refutation, but also no evaluation on personal or conversational data.

**Cost.**
- One LLM OpenIE call per passage at ingest. The paper used Llama-3.3-70B, and quality depends on the extractor.
- At query time: one embedding call, an LLM triple-filter call (v2), and a PPR run, which takes milliseconds on small graphs.

**Failure modes.**
- Entity-centric. Questions with no clear entities give poor seeds.
- OpenIE errors and missed entities directly cap recall.
- Synonym merging produces false merges, for example two different people with the same first name.
- No notion of time or of updates.
- The gains concentrate in multi-hop questions; on single-hop the method reaches parity at best.

### 2.2 Spreading activation and ACT-R

**Mechanism.** ACT-R gives each chunk an activation score:

```
A_i = B_i + Σ_j W_j·S_ji + noise
```

- **Base-level term.** `B_i = ln(Σ_k t_k^-d)`, summed over the times *t_k* since each past use, with `d ≈ 0.5`. It encodes the power law of recency and frequency.
- **Spreading term.** Each context cue *j* adds `W_j·S_ji` to chunk *i*.

Graph RAG variants instead seed activation at query-matched nodes and propagate it with decay over edges, up to a threshold or hop limit.

**Brain mapping.** This is literally neurons with an activation level, synapses as weighted edges, and the cue as the stimulus.

**Evidence.**
- [SA-RAG](https://arxiv.org/abs/2512.15922) (Dec 2025), with spreading activation over an auto-built KG plus iterative chain-of-thought retrieval:
  - "up to 39% absolute" answer-correctness gain over *naive* RAG, with small open models
  - the comparison is against a weak baseline, not against HippoRAG or a hybrid retriever
- [Query-aware spreading activation](https://arxiv.org/abs/2606.30133) (2026):
  - matches QAFD-RAG on MuSiQue (32.8 vs. 33.5 EM)
  - *loses* to HippoRAG on 2Wiki
  - 1.5–4.9x faster than structural spreading
- ACT-R base-level activation appears in [ACT-R-inspired dialogue memory](https://dl.acm.org/doi/10.1145/3765766.3765803) and practitioner systems. I found no benchmark that isolates its contribution.

**Takeaway.** Spreading activation and PPR are close relatives: PPR is spreading activation with restart, converged to a stationary distribution. PPR has the stronger record (HippoRAG). Plain spreading activation needs careful normalisation, because hub nodes otherwise soak up all the activation.

**Cost.** No LLM calls once the graph exists, and milliseconds in SQLite with a recursive CTE or in-memory adjacency.

**Failure modes.**
- Hub explosion: "me", "email" and the user's own name connect to everything.
- Hand-tuned decay and threshold parameters.
- Garbage edges produce garbage activation.
- Without seeding from a good retriever it underperforms dense search.

### 2.3 Generative Agents memory stream (Park et al., 2023)

**Mechanism.** [Generative Agents](https://arxiv.org/abs/2304.03442) logs every observation to a memory stream. Retrieval score is a weighted sum of three terms, each min-max normalised and weighted 1 in the paper:
- **Recency:** exponential decay, 0.995 per game-hour.
- **Importance:** an LLM-rated 1–10 "poignancy" score assigned at write time.
- **Relevance:** cosine similarity to the query.

When summed importance crosses a threshold, a **reflection** step asks the LLM for higher-level insights. These are stored as new memories that cite their evidence, forming a tree.

**Brain mapping.**
- The memory stream is the hippocampal episodic store.
- Reflection is consolidation into semantic or neocortical knowledge.
- Importance plays the role of amygdala salience tagging.

**Evidence.** The ablations are human believability ratings (TrueSkill) in a simulated town, not QA accuracy. The full architecture beat versions without reflection, planning or observation. The scoring formula has been widely copied but never independently shown to beat plain relevance on a QA benchmark.

**Cost.** One LLM call per memory for importance, plus periodic reflection calls. Expensive at email or chat scale.

**Failure modes.**
- LLM importance ratings are noisy and not calibrated.
- Reflections can hallucinate and then become retrievable "facts".
- Recency decay hurts old but relevant facts, such as a birthday mentioned once a year ago.

### 2.4 MemoryBank (Ebbinghaus forgetting)

**Mechanism.** [MemoryBank](https://arxiv.org/abs/2305.10250) (AAAI 2024) gives each memory a retention value `R = e^(-t/S)`.
- Strength *S* increases every time the memory is recalled.
- Memories fall away as R decays.
- It also keeps daily and global LLM-generated summaries of events and user personality.

**Brain mapping.** Synaptic strength consolidated by spaced retrieval.

**Evidence.** Evaluation used qualitative and probing questions on a companion chatbot (SiliconFriend). I found **no ablation showing that forgetting improves QA accuracy over no forgetting**. Later work critiques it as one-dimensional (for example [MOOM](https://arxiv.org/pdf/2509.11860)) and only reuses the formula ([FadeMem](https://arxiv.org/pdf/2601.18642)).

**Assessment.** Decay is best treated as a *ranking prior* and a storage-management tool, not a deletion policy. On a personal knowledge base, hard forgetting is mostly a liability.

### 2.5 MemGPT / Letta (memory tiers)

**Mechanism.** [MemGPT](https://arxiv.org/abs/2310.08560) treats the context window like an OS treats RAM:
- **Core memory:** editable blocks that are always in context.
- **Recall memory:** searchable conversation history.
- **Archival memory:** vector store.
- The LLM pages data in and out through tool calls.
- Letta later added "sleep-time" agents that reorganise memory asynchronously.

**Brain mapping.**
- Core memory is working memory or prefrontal cortex.
- Recall and archival memory are the hippocampal and cortical stores.
- Sleep-time agents are offline consolidation.

**Evidence.**
- DMR (MSC-derived): 93.4%, per Zep's paper.
- Letta's own [filesystem experiment](https://www.letta.com/blog/benchmarking-ai-agent-memory) is the telling one. A GPT-4o-mini agent with only grep, search and open over raw transcript files scored **74.0% on LoCoMo**, above Mem0-graph's reported 68.5%. This is self-reported and the setup differs (adversarial category handling). The lesson is that agentic search over raw text is a strong baseline.

**Cost.** Many LLM calls per turn, because tool use drives every retrieval. Latency depends on the agent loop.

**Failure modes.**
- Depends on the LLM's judgement about when to search.
- Small local models handle tool loops poorly.

### 2.6 A-MEM (Zettelkasten agentic memory)

**Mechanism.** In [A-MEM](https://arxiv.org/abs/2502.12110) (NeurIPS 2025, [code](https://github.com/WujiangXu/A-mem)):
- Each new memory becomes a "note". An LLM generates its keywords, tags and context description.
- Embedding neighbours are retrieved, and an LLM decides which links to create.
- Linked older notes can be **rewritten** ("memory evolution").

**Brain mapping.** Notes are neurons and LLM-chosen links are synapses. Evolution is reconsolidation.

**Evidence.**
- LoCoMo, author-run, F1 and BLEU metrics.
- With GPT-4o-mini, the gains concentrate in temporal questions (F1 about 18 to 46), while multi-hop moves 25 to 27 (secondary table).
- About 7x fewer context tokens than full context.
- No independent reproduction found. Others use it only as a baseline and typically report it *below* Mem0, Zep and raw RAG.

**Cost.** Several LLM calls per memory at ingest: note construction, link decisions, evolution.

**Failure modes.**
- Memory evolution rewrites source material, a direct source of drift and hallucination. This is the exact transformation that the raw-RAG study found harmful.

### 2.7 Mem0 and Mem0-graph

**Mechanism.** In [Mem0](https://arxiv.org/abs/2504.19413):
- An LLM extracts candidate facts from each exchange.
- For each fact, an LLM chooses ADD, UPDATE, DELETE or NOOP against similar existing memories.
- Mem0ᵍ adds an entity-relation graph that marks conflicting edges as invalid.

**Brain mapping.** Facts are semantic neurons. Graph edges are synapses. Update and delete operations are reconsolidation.

**Evidence.** The paper's own LoCoMo LLM-judge scores:

| System | Score |
|---|---|
| Mem0 | 66.9 |
| Mem0ᵍ | 68.4 |
| **Full-context** | **72.9** |

- The memory systems trail full context. The selling point is about 91% lower p95 latency and about 90% fewer tokens.
- The graph variant adds only about 1.5 points for extra cost.
- The RAG baselines in the paper used tiny k values, which makes them weak.
- [Mem0 later self-reports](https://mem0.ai/blog/state-of-ai-agent-memory-2026) 92–94% on LoCoMo and LongMemEval with a new pipeline and newer models, on its managed platform. These figures are not reproduced.

**Cost.** One or two LLM calls per message at ingest, plus more for the graph variant.

**Failure modes.**
- Lossy extraction. Whatever isn't extracted is gone.
- An LLM DELETE destroys history.
- Errors compound over time.

### 2.8 Zep / Graphiti (bi-temporal knowledge graph)

**Mechanism.** In [Zep](https://arxiv.org/abs/2501.13956) ([Graphiti repo](https://github.com/getzep/graphiti)):
- **Graph layers.** Raw episodes form one layer. Entity and fact edges are extracted from them by LLM, and entity communities sit above.
- **Bi-temporal edges.** Every fact edge carries *valid_at* and *invalid_at* (event time) plus *created_at* and *expired_at* (ingest time).
- **Updates.** A contradicting new fact sets `invalid_at` on the old edge instead of deleting it.
- **Retrieval.** Cosine, BM25 and breadth-first graph expansion are fused with RRF, MMR or a cross-encoder.

**Brain mapping.**
- Episodes are hippocampal traces.
- Entities and facts are cortical semantic memory.
- Invalidation is reconsolidation with history kept.

**Evidence.**
- DMR: 94.8 vs. MemGPT's 93.4. DMR is near saturation and too easy.
- LongMemEval: up to +18.5% accuracy and about 90% lower latency vs. full-context baselines (e.g. 71.2 vs. 60.2 with GPT-4o). The largest gains are in temporal reasoning and multi-session questions.
- **Disputes:**
  - Zep first claimed 84% on LoCoMo, then corrected it to 75.1% after Mem0 pointed out that adversarial questions had been excluded from the denominator.
  - Mem0's re-run got 58.4%. ([Zep's rebuttal](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/))
  - Later self-reports of 90%+ on LongMemEval use newer readers.
- **Assessment:** the bi-temporal *data model* is the most defensible idea here. The headline numbers are not independently settled.

**Cost.** Heavy LLM use at ingest (entity extraction, resolution, edge dedup, contradiction checks). Graphiti asks for a structured-output-capable model. Querying uses no LLM by default, so it is fast.

**Failure modes.**
- Entity resolution errors.
- The LLM contradiction check misses contradictions or invents them.
- Small local models produce noisy extraction.

### 2.9 Cognee

**Mechanism.** In [Cognee](https://github.com/topoteretes/cognee), "cognify" chunks documents, LLM-extracts a KG, and stores vectors plus the graph. "Memify" post-processes the graph.

**Evidence.**
- [Self-reported](https://www.cognee.ai/ai-memory-tools-evaluation) HotpotQA on **24 questions**, LLM-judge scored. The authors themselves call it not neutral.
- Essentially no rigorous evidence.

**Cost.** LLM extraction at ingest.

### 2.10 Microsoft GraphRAG and LightRAG

**Mechanism.**
- **GraphRAG:** LLM entity and relation extraction, Leiden communities, then LLM summaries per community. "Global" search map-reduces over the community summaries.
- **LightRAG:** the same extraction with dual-level keyword retrieval, plus cheaper incremental updates.

**Brain mapping.** Community summaries are cortical schemas.

**Evidence.**
- Both originals were evaluated with **LLM-judge pairwise win rates** on sense-making questions, not accuracy.
- [An unbiased re-evaluation](https://arxiv.org/abs/2506.06331) found LightRAG's win rate vs. NaiveRAG dropped from 66.7% to 39.1% once position and length bias were controlled and ties allowed. NaiveRAG *won*.
- [RAG vs. GraphRAG](https://arxiv.org/abs/2502.11371): community-summary GraphRAG is weak on detail questions.
- [GraphRAG-Bench](https://arxiv.org/abs/2506.05690) notes that GraphRAG "frequently underperforms vanilla RAG" on real tasks.

**Cost.** The highest ingest cost of anything surveyed: tens of dollars of GPT-4o for a moderate corpus. Re-indexing on updates is also costly. LazyGraphRAG defers the work to query time.

**Verdict for Mneme.** Not suitable for a local-first personal store.

### 2.11 Hebbian co-activation learning

**Mechanism.** When two memories are retrieved together or used in the same answer, the edge between them is strengthened (`w += η`) and all edges decay (`w *= λ`). Spreading activation then follows learned edges.

**Evidence.**
- [HeLa-Mem](https://arxiv.org/abs/2604.16839) (ACL 2026) is the most serious attempt:
  - Hebbian graph with η=0.02 and λ=0.995, spreading strength 0.1, threshold 0.6
  - LoCoMo with fewer tokens, plus an ablation showing that removing spreading hurts multi-hop
  - author-run only
- [Validation-gated Hebbian learning](https://openreview.net/forum?id=EN9VRTnZbK) is a NeurIPS 2025 workshop paper that describes "promising initial results on minimal graphs".
- No independent replication.
- **Structural problem:** benchmarks are mostly one-shot (ingest, then ask once), so Hebbian learning from *use* barely gets to act. Its value would show only in long-lived, repeatedly queried stores. It is also a feedback loop: whatever gets retrieved gets reinforced, even when it was wrong.

**Recommendation.** Use it only as a small, bounded re-ranking prior with gating, for example reinforcing only items the agent actually *cited* or the user confirmed. Never make it a primary retrieval path.

### 2.12 Complementary learning systems and sleep consolidation

**Mechanism.** Offline jobs turn episodes into semantic facts, profiles and summaries, deduplicate traces, and prune low-value ones. Examples:
- [Human-inspired memory architecture](https://arxiv.org/abs/2605.08538)
- [SCM](https://arxiv.org/abs/2604.20943)
- Active Dreaming Memory
- Letta's sleep-time agents
- HippoRAG's framing of "non-parametric continual learning"

**Evidence.**
- Mostly proposals or author-run small evaluations.
- Counter-evidence: the [raw-RAG study](https://arxiv.org/abs/2610.30755) found that adding atomic facts or summaries to the index *reduced* accuracy compared with raw chunks.
- LongMemEval's own ablation is the positive case: **fact-augmented key expansion** gave roughly 4–9% higher recall and about 5% higher QA accuracy (sources differ on the exact figure). Distilled facts were used as *extra index keys* pointing at the raw value, not as replacements.

**Lesson.** Consolidated "cortical" summaries help as *additional retrieval keys* and for profile-type questions. They hurt when they replace the source.

---

## 3. Benchmarks: what they test, how systems score

**[LongMemEval](https://arxiv.org/abs/2410.10813)** (Wu et al., ICLR 2025)
- 500 questions over timestamped multi-session chat histories.
- Variants: S (about 115k tokens) and M (about 500 sessions, around 1.5M tokens).
- Five abilities: **information extraction**, **multi-session reasoning**, **temporal reasoning**, **knowledge updates**, **abstention** (questions about things never mentioned).
- Headline: commercial assistants and long-context LLMs lose about 30% accuracy compared with being given only the relevant sessions. Full-context GPT-4o is about 60% on S.
- Design findings from the authors:
  - **Value granularity:** splitting sessions into rounds helps.
  - **Key expansion:** adding extracted facts as keys helps.
  - **Time-aware query expansion:** narrowing the search to the inferred time range helps temporal questions, but needs a strong LLM.

**[LoCoMo](https://github.com/snap-research/locomo)** (Maharana et al., 2024)
- 10 conversations of about 600 turns and 26k tokens each.
- QA categories: single-hop, multi-hop, temporal, open-domain and commonsense, adversarial (unanswerable). Also event summarisation.
- **Problems:**
  - [An audit](https://github.com/dial481/locomo-audit) found 99 of 1,540 answer-key items wrong (6.4%). The author has a competing product, but [DolphinBench](https://arxiv.org/pdf/2609.24971) repeats the figure.
  - The gpt-4o-mini judge accepted about 63% of deliberately wrong answers.
  - The adversarial category is handled inconsistently, which caused the Zep/Mem0 dispute.
  - It does not really test knowledge updates.
  - At 26k tokens per conversation, it fits in context, which is why full context reaches about 73%.

**MSC / DMR**
- [Multi-Session Chat](https://arxiv.org/abs/2107.07567) is persona chat across 5 sessions.
- DMR (from MemGPT) is built on MSC and is saturated at about 93–95%. Ignore it.

**[MemoryAgentBench](https://arxiv.org/abs/2507.05257)** (ICLR 2026)
- Four competencies: **accurate retrieval**, **test-time learning**, **long-range understanding**, **selective forgetting / conflict resolution**.
- Every method struggles with multi-hop conflict resolution.
- BM25 is a competitive baseline for accurate retrieval (49.5 to 61% when k goes from 2 to 10).

**Newer**
- [Can Agent Memory Systems Track Evolving State?](https://arxiv.org/pdf/2608.19652) targets state tracking.
- A long-context baseline came within a point of the best memory system.
- Retriever choice and k dominate: BM25 stayed flat at 16.7% while dense retrieval rose to 51.7% as k grew, on that harness.

**Disputes summary.** The Mem0, Zep and Letta LoCoMo numbers are not comparable. The causes are different readers (gpt-4o-mini vs. gpt-4o vs. gpt-5.x), different judge prompts, adversarial-category handling, and LoCoMo's flawed key. No neutral third party has reproduced the vendor headline scores. A 2026 essay, ["The Benchmark Theatre"](https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/), catalogues these issues.

---

## 4. How strong is plain hybrid retrieval?

The evidence points to **very strong, provided the retrieval unit is small and you keep the raw text.**
- **Raw-RAG** (dense plus reranker over raw chunks) beat agentic memory systems in 6 of 7 settings.
- **Letta's grep-over-files agent** beat Mem0-graph on LoCoMo (self-reported).
- **Community runs** on LongMemEval-S report BM25 at about 86% R@5 and hybrid BM25 plus vectors at about 95% R@5 ([MemPalace discussion](https://github.com/MemPalace/mempalace/discussions/747); not peer-reviewed, and this measures retrieval recall, not QA accuracy).
- **Mem0's own paper** shows full context beating Mem0.
- **HippoRAG 2** only beats NV-Embed-v2 (a 7B embedder) by about 3 F1 on average, with gains confined to multi-hop.

**Where graphs genuinely add value:**
- multi-hop bridging, where entity A links to entity B in another document
- "everything about X" aggregation
- explicit temporal and update semantics, which are a data-model matter more than a graph matter

---

## 5. Synthesis for Mneme (SQLite + small local embedder)

### Solid evidence and cheap: build these
| Mechanism | Evidence | Local cost |
|---|---|---|
| Fine-grained units (turn, paragraph, email body, event) with raw text kept | LongMemEval granularity ablation; raw-RAG study | none |
| Hybrid FTS5 BM25 + vector similarity, fused with RRF | MemoryAgentBench BM25; LongMemEval recall; Zep's retrieval design | small embedder |
| Optional small cross-encoder reranker | raw-RAG (dense + rerank) | ~100 MB model; ms per candidate |
| Timestamps on every unit; time-aware query filtering | LongMemEval time-aware expansion; Zep temporal gains | rule-based date parser, optional LLM |
| Bi-temporal facts with invalidation (never delete) | Zep design; knowledge-update category | schema only, and needs a detector |
| PPR / spreading activation seeded by retrieval hits, over cheap edges | HippoRAG 1/2 multi-hop gains; SA-RAG | ms |
| ACT-R base-level prior (recency × frequency) as a small re-rank term | cognitive-science fit; practitioner use | trivial |

### Weak evidence or heavy LLM ingest: avoid or make optional
- **LLM-driven KG extraction** (GraphRAG, LightRAG, Graphiti, Cognee): costly, and noisy with small models. Raw text plus cheap entity edges captures most of the value.
- **Community summaries and GraphRAG global search:** biased evaluations, and weak on detail.
- **LLM importance scoring per memory** (generative agents): costly and noisy.
- **LLM rewriting of old memories** (A-MEM evolution, Mem0 DELETE): destroys provenance.
- **Hard forgetting** (MemoryBank): no evidence of accuracy gains, and bad for a personal archive.
- **Hebbian learning as primary retrieval:** only author-run evidence, with self-reinforcing failure modes.
- **"Sleep" consolidation that replaces sources:** measured to hurt. Keep it additive.

### Recommended minimal architecture, in brain terms

**Neuron = an immutable, timestamped episode chunk.** Store one email body section, one chat turn or small window, one calendar event, or one note paragraph. Fields:
- raw text
- `source`, `source_id`, `thread_id`
- `event_time` (when it happened) and `ingest_time`
- author and participants
- FTS5 index and embedding

Optionally add **semantic neurons** (facts, profile statements) produced by an offline pass. Each one *points to* its evidence episodes and is indexed as an extra key, never a replacement.

**Synapses: typed edges, mostly created deterministically at ingest.** Weights are 0–1 and each edge records a type and provenance.
- **Structural (free):** same thread, reply-to, same calendar event, same note, sequential adjacency in time.
- **Entity (cheap):** links to entity nodes for people (by email address or contact), projects, places and dates. Extract them with regex and contact matching, plus an optional small NER model. Entity nodes act as hub neurons, so cap their fan-out or down-weight by inverse degree, the way IDF does.
- **Semantic (cheap):** k-nearest-neighbour edges above a similarity threshold, computed at ingest. These are HippoRAG's synonym edges.
- **Hebbian (optional, gated):** strengthen an edge when two neurons are *both cited in an accepted answer*. Cap the weight, decay toward a baseline, and store it separately so it can be ablated.

**Query activation (deterministic, no LLM required).**
1. Parse time expressions with rules such as "last March" and "before the trip". Turn them into an `event_time` window filter or a soft prior.
2. **Seed:** take the top ~50 from hybrid BM25 + vector, fused with RRF.
3. **Spread:** run 2–3 iterations of PPR from the seeds over synapses (restart probability about 0.5, degree-normalised so hubs don't dominate).
4. **Re-rank:** score each candidate as `relevance + α·PPR + β·ACT-R base-level (recency/frequency of past access) + γ·validity`. Validity is penalised when a superseding fact exists. A cross-encoder can replace the hand weights.
5. **Return raw text with timestamps and provenance.** Let the agent LLM reason over it. The agent can call again for iterative multi-hop, which HippoRAG shows combines well with IRCoT.

**Updates and contradictions.** Episodes are never mutated. For facts like "X's phone number", "meeting moved to Thursday" or "I now live in Lisbon", keep a `facts` table with `subject, predicate, object, valid_from, valid_to, superseded_by, evidence_ids`.
- **Detection:** cheap first, using the same subject and predicate slot, high similarity and a newer `event_time`. An optional local LLM can confirm.
- **Querying:** current-state questions prefer the newest valid fact. "What did I think in 2024" questions use the `valid_from/valid_to` window. Both values stay retrievable, as in Zep.

**Time.**
- Store `event_time` separately from `ingest_time`, which matters for imported email archives.
- Treat recency as a *prior*, not a filter, unless the query says otherwise.
- Answer explicitly temporal questions ("how many days between…", "what happened first") by returning timestamps to the reader. Don't expect retrieval to compute them.

**Consolidation ("sleep").** An optional background job using a local LLM can do the following. Everything stays additive and traceable:
- dedupe near-identical episodes
- build per-entity profile cards and per-thread summaries, used as extra keys and linked to their sources
- propose fact extractions for the facts table

**Forgetting.** No deletion by default. Decay affects ranking only. Archive tiers are acceptable for performance.

### Evaluation plan
- Build a fictional vault (notes, emails, calendar, chats spanning 1–2 simulated years) with a gold answer *and gold evidence IDs* for every question.
- Report **retrieval recall@k on evidence IDs** separately from end-to-end QA accuracy, so you can tell retrieval failures from reasoning failures.
- Run every question against these baselines:
  1. BM25 only
  2. vector only
  3. hybrid with RRF
  4. hybrid + rerank
  5. full Mneme
  6. full context, where it fits
- Ablate each brain mechanism (PPR, ACT-R prior, Hebbian, facts table, consolidation keys) one at a time.
- Use a deterministic or exact-match judge where possible. Where you must use an LLM judge, spot-check it with deliberately wrong answers, as the LoCoMo audit did.

**Eval categories to replicate in the test vault:**
1. **Single-hop factual recall:** "What's Dana's dentist's name?"
2. **Cross-source multi-hop / bridging:** "Who organised the event I emailed Priya about?", which needs an email, then the calendar, then a contact.
3. **Multi-session aggregation and counting:** "How many times did I meet Leo in Q2?" and "List all the books I said I wanted to read."
4. **Temporal reasoning (absolute):** "What was I doing on 12 March?"
5. **Temporal reasoning (relative and ordering):** "Did the offsite happen before or after I changed teams?" and "How many days between X and Y?"
6. **Knowledge updates / current state:** a moved address, a rescheduled meeting, a changed preference. Ask for the latest value.
7. **Historical state:** "Where did I live when I first met Sam?" This tests that superseded facts are kept.
8. **Contradiction surfacing:** two sources disagree, and the system should report both with dates.
9. **Abstention / adversarial:** questions about entities or events that never occurred, including plausible near-misses with real names but the wrong event.
10. **Entity disambiguation:** two people named "Alex", and a person known by a nickname and an email alias.
11. **Paraphrase and vocabulary mismatch:** query wording that shares no keywords with the source, which tests the dense half.
12. **Exact-token lookup:** order numbers, flight codes, rare names, which tests the BM25 half.
13. **Preference and profile synthesis:** "What kind of restaurants do I like?", built from scattered evidence.
14. **Implicit or indirect evidence:** facts stated only in passing, mid-thread.
15. **Long-tail recency stress:** an old but important fact against many recent distractors, to check that the recency prior doesn't bury it.
16. **Usage-learning test (for Hebbian):** repeated related queries over time, measuring whether accuracy or latency improves on later queries without hurting unrelated ones.
17. **Scale and latency:** p50/p95 query latency and ingest cost at 10k, 100k and 1M neurons.

---

*Sources are linked inline. Primary arXiv IDs cited: 2405.14831, 2502.14802, 2512.15922, 2606.30133, 2304.03442, 2305.10250, 2310.08560, 2502.12110, 2504.19413, 2501.13956, 2502.11371, 2506.05690, 2506.06331, 2604.16839, 2605.08538, 2604.20943, 2410.10813, 2507.05257, 2608.19652, 2610.30755.*
