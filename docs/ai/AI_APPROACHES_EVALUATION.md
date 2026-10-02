# JEV / OKF / RAG / MAG / CAG: Evaluation

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [AI / agent architecture](AI_AGENT_ARCHITECTURE.md)

**Method.** Verify what each term actually means (several of these acronyms are overloaded or very new). Then ask one question: *does it measurably help capture, link, apply or remember progress for SIH26122?* If not, it stays out. Verification done 2026-10-02 from the sources in §8.

> **Phase 3 update (2026-10-02).** RAG, CAG, MAG and OKF are now implemented in the linking layer and each is evaluated separately; JEV was re-investigated and is still not implemented. See [Linking layer](LINKING_LAYER.md). Re-verification: OKF is **v0.2** with an official spec in [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md); its frontmatter fields are `type` (required), `title`, `description`, `resource`, `tags`, `generated`, `sources`, `verified`, `status`, `stale_after` (the `id`/`category`/`updated`/`confidence` example in §4 below predates the spec check and is not what the export writes). Jev: the official TypeSafe announcement and docs describe hosted early access only, with vendor-reported benchmarks; the release date and the Jev-Mem paper cited in §5/§8 come from secondary sources and were not re-verified.

---

## 1. RAG: Retrieval-Augmented Generation

**Verified meaning.** Retrieve relevant documents or records at query time and give them to the LLM as context, so its output is grounded in data it was not trained on. Well established since 2020.

**Relevance to SIH26122: high, in two places.**

| Use | How | Benefit |
|---|---|---|
| **Linking** | Retrieve top-k plan nodes (tag index + aliases + fuzzy + embeddings), and the LLM adjudicates only among them | Grounds every link in real plan IDs. The LLM cannot hallucinate an activity. Keeps prompts small even for 50k-activity schedules |
| **Institutional memory Q&A** | Retrieve actual-progress records and knowledge entries, then answer with citations | "What really delayed cable pulling last project?" answered from data, with sources |

**Decision: ADOPT** (Phases 3 and 6). Hybrid retrieval (lexical + tag + semantic) rather than vectors only, because tag numbers and abbreviations are poorly served by embeddings alone.

---

## 2. CAG: Cache-Augmented Generation

**Verified meaning.** Chan et al., *"Don't Do RAG: When Cache-Augmented Generation is All You Need for Knowledge Tasks"* (arXiv 2412.15605, Dec 2024). Preload a **small, stable** knowledge corpus into the model's context once and reuse its KV cache, or the provider's prompt cache, for every query. No retrieval step. Fast and simple, but only viable when the corpus fits the context window and rarely changes.

**Relevance: medium, narrow and real.** Some of our knowledge is exactly that shape:
- discipline glossary and abbreviations (~2–5k tokens),
- tag/line numbering conventions for the project,
- event-type definitions and extraction rules,
- the supervisor's own discipline/area profile.

The same thing is sent on every extraction, adjudication and agent call.

**Decision: ADOPT, narrowly.** A fixed, versioned **prompt prefix per project** (`llm/prefixes/`) placed first in every prompt, so serving-side prefix caching applies (vLLM automatic prefix caching in production; provider prompt caching where available). **Not** used for the schedule itself: 300–50,000 activities change daily, which is RAG territory. No custom KV-cache engineering in the hackathon. The gain comes from prompt ordering, and the serving layer does the caching.

---

## 3. MAG: Memory-Augmented Generation

**Verified meaning.** The term is used loosely in 2025–26 writing. The common sense is an LLM system with **persistent memory across interactions** (store, update and recall facts or experiences), as distinct from RAG (retrieve from a fixed corpus) and CAG (preload a static corpus). Summarized as "RAG retrieves, MAG remembers, CAG caches." It is occasionally used for "multi-agent graph". We treat that as a separate question (§6).

**Relevance: high. This is where the system learns.**

| Memory | What it remembers | Effect |
|---|---|---|
| **Alias memory** | Planner/supervisor-confirmed "field phrase → activity" pairs | Next time "spool erected L-1203" links instantly with high confidence. Accuracy rises with use (we plot this learning curve) |
| Session memory | The conversation with a supervisor | "Mark *that one* finished too" works |
| Supervisor profile | Discipline, areas, open activities | Narrows retrieval. Fewer clarifying questions |
| Template memory | Spreadsheet header mappings | The same template needs zero LLM calls after the first upload |
| Project memory → institutional memory | Real durations, delays, productivity | Feeds analytics, RAG Q&A and future planning |

**Decision: ADOPT** (Phases 3, 4, 6). Implemented with plain DB tables and the LangGraph checkpointer. No memory framework dependency. Safety: aliases need confirmation thresholds, are project-scoped by default, and are visible and deletable.

---

## 4. OKF: Open Knowledge Format

**Verified meaning.** An open specification announced by Google Cloud (2026) that formalizes the "LLM wiki" pattern: knowledge as **Markdown files with YAML frontmatter** (id, category, updated, confidence, source/provenance), with link conventions between entries, intended to be portable and readable by any agent without custom integration. It is a *format* for curated knowledge, complementary to RAG (a *retrieval* method), not a replacement for it.

**Caveat.** It is young. Secondary sources describe it consistently, but tooling and adoption are early. Before implementing, check the official spec for exact field names.

**Relevance: medium, aligned with the PS's "institutional memory" outcome.** The PS wants project execution knowledge to outlive the project and feed future planning. A portable, human-readable, git-versionable, provenance-carrying export fits that well:

```markdown
---
id: oil-knowledge/piping/hydrotest-24in-duration
category: piping/productivity
updated: 2026-10-02
confidence: 0.82
source: [project:CGS-EXP-01, activities: PIP-A3-1203-HT, PIP-A3-1207-HT, ...]
---
# Hydrotest duration: 24" carbon-steel lines
Planned 2 days; actual median 3.5 days (n=11). Main causes: test-pack documentation
holds (6/11), water availability (3/11). See [[piping/test-pack-delays]].
```

**Decision: ADOPT as an export format, not as the system of record** (Phase 6 stretch). The database remains the source of truth. OKF files are a generated, read-only knowledge bundle per closed project, also indexed for RAG. Cost: one generator module plus PyYAML. If the spec turns out unstable, the same Markdown+frontmatter bundle is still useful on its own.

---

## 5. JEV: "Jev" (not an acronym)

**Verified meaning.** *Jev* is TypeSafe AI's hosted "System-One" model, released **18 September 2026** (two weeks before this plan). It is non-autoregressive: it takes structured application state plus a typed question or permitted-action list and returns a decision with probability/confidence, instead of generating text. Vendor claims: up to 100× faster/cheaper than LLMs for such decisions. Related research: *Jev-Mem* (arXiv 2609.23986) uses a fast System-One controller for agent-memory operations, with a slower LLM for reasoning.

**Where it could fit.** Conceptually, our "pick one candidate from top-k with a confidence" step is exactly a structured decision. The *architecture idea* (fast decision layer for routine choices, LLM for hard reasoning) is something we already apply: the deterministic scorer handles most events, and the LLM handles only ambiguous ones.

**Why we do not adopt the product now**

| Factor | Assessment |
|---|---|
| Data sovereignty | Hosted third-party API. OIL data is under NDA, so external decision calls on project data are not acceptable in production |
| Maturity | Two weeks old. Benchmarks are vendor-reported, not independently verified. Demos are simulator-only |
| Need | Our calibrated logistic scorer already gives millisecond, explainable, offline decisions with confidence |
| Auditability | A planner must see *why* a link was chosen. Our features are inspectable; an external model's are not |
| Demo risk | A new external dependency during judging |

**Decision: DO NOT ADOPT (re-evaluate later).** Keep the System-One/System-Two split as a *design principle*. When a second scorer implementation is actually needed, introduce a `DecisionScorer` seam and benchmark Jev against our scorer on **synthetic data only**, measuring precision at `T_auto`, calibration and latency. Recorded in [Future scope](../plan/FUTURE_SCOPE.md).

---

## 6. Related question: single agent vs multi-agent

"MAG" and "agentic" often imply multi-agent systems. For this problem:
- Extraction, linking and decision are a **pipeline** with clear inputs and outputs, so a deterministic graph is better than negotiating agents.
- The time agent is **one LangGraph agent** with tools and explicit nodes (understand → fill slots → resolve → confirm → log).
- The memory Q&A is a second, independent LangGraph flow.

**Decision:** LangGraph state graphs, one agent per user-facing task, no agent-to-agent orchestration. Revisit only if a future feature needs genuinely independent planners (e.g. an autonomous recovery-schedule proposer).

---

## 7. Summary matrix

| Approach | Meaning verified | Benefit here | Cost | Decision | Phase |
|---|---|---|---|---|---|
| RAG | ✔ | Grounded linking; memory Q&A | Low (hybrid index) | **Adopt** | 3, 6 |
| CAG | ✔ | Cheaper, consistent prompts for stable glossary/rules | ~0 (prompt ordering) | **Adopt narrowly** | 2–4 |
| MAG | ✔ (loose term) | Learning aliases, session context, institutional memory | Low (tables + checkpointer) | **Adopt** | 3, 4, 6 |
| OKF | ✔ (new spec) | Portable institutional-memory export | Low (generator) | **Adopt as export (stretch)** | 6 |
| JEV | ✔ (product, not acronym) | Conceptual fit for decisions | Sovereignty, maturity, audit risk | **Defer; principle only** | Future |

## 8. Sources

- RAG: Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* (2020).
- CAG: Chan et al., *Don't Do RAG: When Cache-Augmented Generation is All You Need for Knowledge Tasks*, <https://arxiv.org/pdf/2412.15605>
- RAG vs MAG vs CAG overview: <https://blog.seeb4coding.in/rag-vs-mag-vs-cag-which-one-is-better-for-ai-agents/>
- OKF: <https://www.mindstudio.ai/blog/what-is-open-knowledge-format-okf-google-llm-wiki-standard>; Google Cloud Tech announcement: <https://x.com/GoogleCloudTech/status/2067012903337664886>
- Jev: <https://www.mindstudio.ai/blog/jev-system-one-model-launch>; Jev-Mem: <https://arxiv.org/abs/2609.23986>
