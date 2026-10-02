# P2E Bridge — Project Master Plan (SIH26122)

> **Planning-to-Execution Bridge**: an intelligent data-capture and schedule-linking layer that turns messy site reporting into trusted, activity-level actual dates on the L5/L6 schedule.

| | |
|---|---|
| Problem statement | **SIH26122** — Intelligent Data Capture & Schedule-Linking Layer for Infrastructure Project Management: Real-Time Actual Progress Tracking (Planning-to-Execution Bridge) |
| Organization | Oil India Limited |
| Category / Theme | Software / Smart Automation |
| Status | Phase 0 (synthetic data) and Phase 1 (foundation: DB, schedule import, schedule API) done 2026-10-02; Phase 2 not started |
| Plan date | 2026-10-02 |

This document is the entry point. Every other planning document is linked from here.

---

## 1. Document map

| # | Document | What it answers |
|---|---|---|
| 1 | **This file** | What we build, why, in which order, and how the docs fit together |
| 2 | [Problem analysis & scope](plan/PROBLEM_AND_SCOPE.md) | What the problem statement really asks; scope in/out; success criteria |
| 3 | [System architecture](architecture/SYSTEM_ARCHITECTURE.md) | Components, boundaries, data flow, hackathon vs production topology |
| 4 | [Phase-by-phase development plan](plan/PHASE_PLAN.md) | Phases 0–8 with purpose, features, components, workflow, tech, I/O, dependencies, expected result |
| 5 | [AI / agent architecture](ai/AI_AGENT_ARCHITECTURE.md) | Extraction, linking, confidence, time agent, memory, guardrails |
| 6 | [JEV / OKF / RAG / MAG / CAG evaluation](ai/AI_APPROACHES_EVALUATION.md) | What each term really means, verified, and whether we use it |
| 6b | [Schedule-linking layer (Phase 3)](ai/LINKING_LAYER.md) | How RAG, CAG, MAG and OKF are implemented and evaluated; JEV decision |
| 7 | [Data & database architecture](architecture/DATA_ARCHITECTURE.md) | Entities, schema, event model, audit trail, synthetic data |
| 8 | [Backend / API architecture](architecture/BACKEND_API.md) | Modules, endpoints, pipelines, security at trust boundaries |
| 9 | [Frontend architecture](architecture/FRONTEND.md) | Screens, users, components, voice, real-time updates |
| 10 | [Testing & validation plan](quality/TESTING_AND_VALIDATION.md) | Unit/integration tests, AI evaluation metrics, acceptance gates |
| 11 | [Deployment plan](operations/DEPLOYMENT.md) | Hackathon demo deployment, production on-prem deployment |
| 12 | [End-to-end workflow & demo flow](plan/END_TO_END_WORKFLOW.md) | One report's journey from site to schedule; the judge demo script |
| 13 | [Technology decisions](decisions/TECHNOLOGY_DECISIONS.md) | Each tech choice, alternatives, and why |
| 14 | [Future scope](plan/FUTURE_SCOPE.md) | Hackathon → production roadmap |

---

## 2. The problem in one paragraph

Oil & gas infrastructure projects plan in Primavera/MS Project down to executable **L5/L6 activities** across civil, piping, static/rotating equipment, electrical, instrumentation and HSE. Execution reality comes back as daily progress reports, site diaries, discipline spreadsheets and verbal updates, each in its own format and vocabulary ("spool erected" vs the plan's "Erect Line 24"-XX"). Nobody reliably links those reports to plan activity IDs, so actual start/finish dates arrive late, wrong, or not at all. Everything downstream (delay analysis, forecasting, AI performance monitoring) inherits bad data, and when the project closes the knowledge of what really happened is lost.

## 3. What we build

A layer that sits **between the field and the schedule**:

1. **Capture**: ingests free-text daily reports, discipline spreadsheets, scanned diaries (stretch) and schedule exports, plus a conversational/voice **time agent** for supervisors.
2. **Extract**: turns each input into structured *progress events* (`activity description, event type start/finish/progress, date, discipline, location, quantity, evidence`).
3. **Link**: fuzzy and semantic matching of each event to the correct **L5/L6 plan node**, handling vocabulary and granularity mismatch, with a **confidence score**.
4. **Decide safely**: high-confidence links update actuals automatically. Medium-confidence links go to a **planner review queue**. Unmatched or new activities are **flagged, never dropped**.
5. **Write back**: actual start/finish dates in the schedule/PMIS with a **full audit trail**, plus a schedule export (MS Project XML / CSV) for P6/MSP.
6. **Remember**: builds a clean, discipline-tagged **actual-progress dataset** and an **institutional memory** (real durations, recurring delay causes, productivity) that can be queried in natural language and exported as portable knowledge.

## 4. Mandatory vs ideal (from the PS)

| PS asks | Our answer | Phase |
|---|---|---|
| Ingest 2–3 varied formats (free-text DPR + spreadsheet minimum) | Free text, XLSX/CSV, schedule CSV/MSPDI XML; XER and scanned diary are stretch | 1, 2 |
| LLM conversational/voice "time agent" | LangGraph agent, web chat + browser Web Speech API voice | 4 |
| Fuzzy-match to L5/L6, handle terminology and granularity, flag unmatched | Hybrid linker: tag/code match + fuzzy + embeddings + LLM adjudication + alias memory | 3 |
| Auto-update actuals near real time, with confidence and audit trail | Event store → apply rules → schedule actuals; SSE live updates; append-only audit log | 5 |
| Clean dataset for analytics and institutional memory | Actual-progress dataset, analytics views, RAG Q&A, OKF knowledge export | 6 |
| Full OCR/ASR not required | Native browser speech for demo; OCR is stretch | — |

## 5. Architecture at a glance

```
 Field inputs                      P2E Bridge                                   Consumers
 ───────────                 ─────────────────────────────────────────          ─────────
 DPR free text ─┐            ┌────────────┐   ┌─────────────┐  ┌──────────┐     Planner review UI
 Spreadsheets  ─┼─► Ingest ─►│ Extraction │──►│  Linking     │─►│ Decision │──►  Schedule actuals (PMIS)
 Scanned diary ─┤   (files)  │ (LLM+rules)│   │ (hybrid+LLM) │  │ & Apply  │     MSPDI/CSV export → P6/MSP
 Time agent ────┘            └────────────┘   └─────────────┘  └──────────┘     Analytics dashboard
 (chat/voice)                      │                 ▲   ▲            │          Institutional memory (RAG, OKF)
 Schedule export ─► Plan import ───┴──── plan nodes ─┘   └ alias memory ┘
                                          SQLite (hackathon) / PostgreSQL + pgvector (production)
```

Details: [System architecture](architecture/SYSTEM_ARCHITECTURE.md), [AI architecture](ai/AI_AGENT_ARCHITECTURE.md).

## 6. Core design principles

1. **Never silently drop or silently overwrite.** Every unmatched item lands in a queue. Every change is audited with evidence.
2. **Deterministic first, LLM where it earns its place.** Tag numbers, line numbers, dates and quantities are parsed with rules. The LLM handles language, ambiguity and conversation. The LLM proposes and validated code commits.
3. **Confidence is calibrated, not vibes.** Thresholds are chosen on labelled synthetic data so auto-applied links meet a target precision of at least 95%.
4. **The system gets smarter with use.** Every planner confirmation becomes an alias in memory, so the same field phrase links automatically next time.
5. **Sovereign by default.** Data is under NDA, so the design runs with an open-weight model on-prem. Hosted APIs are optional and swappable.
6. **Hackathon-small, production-shaped.** SQLite plus one process for the demo. The same schema and interfaces move to PostgreSQL, queues and on-prem GPUs.

## 7. AI approaches: verdict summary

Full analysis: [AI approaches evaluation](ai/AI_APPROACHES_EVALUATION.md).

| Approach | Verified meaning | Verdict |
|---|---|---|
| **RAG** | Retrieval-Augmented Generation | **Adopt.** Candidate plan-node retrieval for linking, and Q&A over institutional memory |
| **CAG** | Cache-Augmented Generation: preload a small, stable corpus into the context and reuse the cached prefix | **Adopt, narrowly.** Per-project glossary, abbreviations and conventions as a cached prompt prefix |
| **MAG** | Memory-Augmented Generation: persistent memory across interactions | **Adopt.** Alias memory (learned phrase→activity mappings), supervisor session memory, project memory |
| **OKF** | Open Knowledge Format: Google's Markdown+YAML spec for portable LLM-readable knowledge bases (2026) | **Adopt as an export format** for institutional memory (Phase 6). DB stays the source of truth |
| **JEV** | *Jev*: TypeSafe AI's hosted "System-One" structured-decision model (released 18 Sep 2026); not an acronym | **Do not adopt now.** Hosted, unverified, NDA conflict. Keep a pluggable decision-scorer interface and evaluate on synthetic data later |

## 8. Phases

Full detail per phase: [Phase plan](plan/PHASE_PLAN.md).

| Phase | Name | Core output | Hackathon priority |
|---|---|---|---|
| 0 | Domain model & synthetic data ✅ | Sample L5/L6 schedule, DPRs, spreadsheets, **ground-truth labels**, glossary ([dataset](../data/synthetic/README.md)) | Must |
| 1 | Foundation & plan import ✅ | Repo, FastAPI app, DB schema, schedule import (CSV/MSPDI), schedule API ([backend](architecture/BACKEND_API.md#0-implemented-so-far-phase-1)) | Must |
| 2 | Ingestion & extraction | Free text + spreadsheet → validated progress events | Must |
| 3 | Schedule-linking engine | Event → L5/L6 node with confidence; unmatched queue; alias memory | Must (core value) |
| 4 | Time agent (chat + voice) | Supervisor logs start/finish conversationally | Must |
| 5 | Review queue, write-back & audit | Planner approves; actuals update live; audit trail; schedule export | Must |
| 6 | Analytics & institutional memory | Plan vs actual dashboard, delay causes, RAG Q&A, OKF export | Should |
| 7 | Evaluation & hardening | Accuracy report on labelled data, security checks, tests | Must |
| 8 | Packaging, deployment & demo | One-command run, demo script, pitch assets | Must |

**Critical path:** 0 → 1 → 2 → 3 → 5 → 7 → 8. Phase 4 can run in parallel after Phase 3's linker API exists. Phase 6 starts after Phase 5's data exists.

### Suggested team split (6 members)

| Role | Owns |
|---|---|
| Domain & data lead | Phase 0, glossary, ground truth, demo narrative |
| Backend lead | Phases 1, 5, API, DB, audit |
| AI lead (extraction/linking) | Phases 2, 3, evaluation harness |
| AI lead (agent/memory) | Phase 4, memory, RAG/OKF (Phase 6) |
| Frontend lead | All UI, voice, live updates |
| QA / DevOps / pitch | Phase 7, 8, deck, video |

## 9. Success criteria (what "done" means for the hackathon)

| Metric | Target on synthetic labelled set |
|---|---|
| Formats ingested end-to-end | ≥ 3 (free text, XLSX, time agent), plus schedule import |
| Event extraction: activity + event type + date correct | ≥ 90% |
| Linking top-1 accuracy (all events) | ≥ 85% |
| Precision of **auto-applied** links | ≥ 95% |
| Unmatched or new activities flagged (not dropped) | 100% |
| Time-agent log: utterance → event recorded | ≤ 3 conversational turns typical |
| Report → schedule actual visible | ≤ 10 s for a single DPR |
| Every applied actual has an audit record with source evidence | 100% |

## 10. Key risks

| Risk | Mitigation |
|---|---|
| No real data (NDA) | Phase 0 synthetic generator modelled on real DPR/WBS conventions, with ground truth. Request OIL sample formats early |
| LLM hallucinates an activity ID | LLM picks only from retrieved candidate IDs. Output is schema-validated. IDs are checked against the DB |
| Over-trust in auto-updates | Calibrated thresholds, review queue, reversible applies, audit trail |
| Granularity mismatch (spools vs line) | Sub-progress aggregation rules, quantity-based completion ([AI architecture §5](ai/AI_AGENT_ARCHITECTURE.md)) |
| LLM latency or cost on CPU | Rules and fuzzy matching resolve most events. The LLM runs only on ambiguous cases and on free text |
| Prompt injection via free-text reports | The LLM has no write tools in extraction. Outputs are validated. Writes go through deterministic rules |
| Scope creep (OCR, P6 API) | Explicitly stretch. See [Future scope](plan/FUTURE_SCOPE.md) |

## 11. Current repository state (inspected 2026-10-02)

- Git repo on `main`, no commits yet. `README.md` is empty and `.gitignore` covers `.venv/`, `__pycache__/` and `.env`.
- `.venv` uses Python **3.14.7** with `langgraph 1.2.12`, `langchain-core 1.6.6`, `langchain-huggingface 1.2.2` and `pydantic 2.13.5` (pinned in `requirements.txt`).
- No application code yet. These docs are the first artifact.
- Implication: LangGraph (agent orchestration) and Hugging Face (open-weight model access) are already chosen and installed, and the plan builds on them. New dependencies are listed and justified in [Technology decisions](decisions/TECHNOLOGY_DECISIONS.md). **Nothing new is installed during planning.**

## 12. Sources

- Problem statement text: SIH 2026 PS dataset (GitHub mirrors of the official SIH portal): <https://github.com/NoBugNinja/Smart-India-Hackathon-SIH-2026-Problem-Statements>, <https://github.com/NIVION-HUB/SIH2026-PS>
- AI approach sources: see [AI approaches evaluation §8](ai/AI_APPROACHES_EVALUATION.md#8-sources)
