# System Architecture

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [AI](../ai/AI_AGENT_ARCHITECTURE.md) · [Data](DATA_ARCHITECTURE.md) · [Backend](BACKEND_API.md) · [Frontend](FRONTEND.md)

## 1. Architectural style

A **modular monolith** for the hackathon: one Python service (FastAPI) with clearly separated internal modules, one database file, and a React single-page app served as static files by the same service. Module boundaries are drawn where production would split into services, so scaling is a deployment change, not a rewrite.

Why not microservices now: a 36-hour build, one team, one dataset. Network hops, service discovery and distributed tracing add failure modes without adding demo value.

## 2. Context diagram

```
          ┌──────────────────┐        ┌───────────────────┐
          │  Site supervisor │        │ Planner / PM      │
          │  (phone/browser) │        │ (desktop browser) │
          └────────┬─────────┘        └─────────┬─────────┘
                   │ chat / voice / upload      │ review, schedule, analytics
                   ▼                            ▼
          ┌───────────────────────────────────────────────┐
          │                 P2E Bridge                    │
          │   (FastAPI + React SPA + DB + LLM gateway)    │
          └───┬───────────────┬──────────────────┬────────┘
              │ import        │ export           │ inference
              ▼               ▼                  ▼
     Primavera P6 / MSP   P6 / MSP / PMIS     Open-weight LLM + embeddings
     (XER, MSPDI, CSV)    (MSPDI/CSV actuals)  (HF endpoint / on-prem vLLM)
```

## 3. Internal modules

```
p2e/
├── api/            HTTP layer: routers, auth, request validation, SSE stream
├── plan/           Schedule import (CSV, MSPDI, XER*), plan-node index, glossary
├── ingest/         File intake, type detection, storage of raw evidence
├── extract/        Free text → events (LLM), spreadsheet → events (mapping + rules)
├── link/           Candidate retrieval, scoring, LLM adjudication, confidence
├── decide/         Thresholds, validation rules, apply/queue/flag, granularity aggregation
├── agent/          LangGraph time agent (chat/voice), tools, session memory
├── memory/         Alias memory, project memory, knowledge store, OKF export*
├── analytics/      Plan-vs-actual, productivity, delay causes, Q&A (RAG)
├── audit/          Append-only audit log, evidence links
├── llm/            Model gateway: chat model, embeddings, cached prompt prefixes (CAG)
└── db/             Schema, migrations, repositories
* = stretch
```

**Dependency rule:** `api → (agent | ingest | decide | analytics) → (extract | link | memory) → (plan | llm | db | audit)`. Lower layers never import upper ones. `link` and `extract` are pure functions over data plus an injected LLM, which keeps them testable without a server.

## 4. Primary data flow

```
 ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐
 │ Source  │──►│ Ingest  │──►│ Extract  │──►│  Link   │──►│  Decide  │──►│ Schedule │
 │ (file / │   │ store   │   │ events   │   │ top-k + │   │ apply /  │   │ actuals  │
 │  chat)  │   │ raw +   │   │ (schema- │   │ confid. │   │ review / │   │ + audit  │
 └─────────┘   │ hash    │   │ validated│   └────┬────┘   │ unmatched│   └────┬─────┘
               └─────────┘   └──────────┘        │        └────┬─────┘        │
                                                 │             │ planner      │ SSE
                                     alias memory◄──────────────┘ decisions    ▼
                                                                        UI, export,
                                                                        analytics, memory
```

1. **Ingest**: validate the file (type, size), store raw bytes plus SHA-256 (dedupe), and create a `source_document`.
2. **Extract**: produce `progress_event` rows (status `extracted`) with the raw span as evidence.
3. **Link**: for each event, retrieve candidate plan nodes, score them, and optionally LLM-adjudicate. Store `link_candidate` rows plus a chosen link and confidence.
4. **Decide**: run validation rules (dates sane, discipline consistent, no regression). Then route:
   - `confidence ≥ T_auto` and rules pass → **apply** (update actuals, audit).
   - `T_review ≤ confidence < T_auto` or a rule warning → **review queue**.
   - `< T_review` or no candidate → **unmatched / possible new activity** queue.
5. **Apply**: update `plan_node` actual start/finish via granularity rules, write an `audit_log` entry, and push an SSE event.
6. **Learn**: planner confirmations write `alias` entries (field phrase → activity), which improve future linking.

## 5. Time-agent flow (synchronous path)

```
Supervisor: "Started hydrotest on line 1203 this morning"
   → agent: parse intent (log_event) + slots (activity text, event=start, time=today AM)
   → tool: search_activities("hydrotest line 1203", discipline=piping) → top-3
   → if one clear match: confirm in one turn ("Hydrotest 24"-P-1203, Area 3 — mark started today 09:00?")
   → supervisor: "yes" → tool: log_event(...) → same Decide pipeline (source=time_agent, higher prior)
   → reply with confirmation + audit id
```

The agent never writes to the DB directly. It calls the same `log_event` service as file ingestion, so every path shares validation, confidence, and audit.

## 6. Hackathon topology

```
┌──────────────────────── one machine (laptop / VM) ────────────────────────┐
│  uvicorn: FastAPI app  ── serves /api/* and the built React SPA at /      │
│      │                                                                    │
│      ├── SQLite file  (data/p2e.db)       raw uploads: data/uploads/      │
│      └── LLM gateway ──► Hugging Face Inference endpoint (open-weight)    │
│                         or local OpenAI-compatible server (fallback)      │
└───────────────────────────────────────────────────────────────────────────┘
```

Background work (extraction of a 50-row spreadsheet) runs in FastAPI `BackgroundTasks`. Progress is streamed via SSE. No broker.

## 7. Production topology (target)

```
            ┌──────────── OIL on-prem / sovereign cloud ─────────────┐
 Users ──► Reverse proxy (TLS, SSO/OIDC) ──► API pods (FastAPI, stateless)
                                             │        │
                              Postgres + pgvector     Job queue (Postgres-based or Redis)
                              (events, plan, audit,         │
                               aliases, embeddings)    Worker pods: extraction, OCR, ASR,
                                             │          linking, nightly memory build
                              Object storage (MinIO/S3): raw evidence files
                                             │
                              LLM serving: vLLM on GPU (open-weight instruct model)
                              Embeddings service
                              Connectors: P6 EPPM API, MS Project Online, PMIS
                              Observability: OpenTelemetry → Prometheus/Grafana, LLM trace store
```

What changes between hackathon and production: SQLite → Postgres (same schema), BackgroundTasks → queue workers, HF endpoint → on-prem vLLM, file export → API connectors, demo roles → SSO/RBAC. The modules stay the same.

## 8. Cross-cutting concerns

| Concern | Hackathon | Production |
|---|---|---|
| AuthN/Z | Role-scoped API keys (supervisor, planner, admin) in `.env` | OIDC SSO, RBAC per project/discipline |
| Input validation | Pydantic on every request. File type/size limits. `defusedxml` for XML. Formulas read as values (no macros) | Same plus AV scanning of uploads |
| LLM safety | No write tools in extraction. Schema-validated outputs. Candidate-ID whitelist | Same plus red-team prompt-injection tests, output monitoring |
| Audit | Append-only table. Every apply/undo has actor, source, before/after, evidence | Same plus WORM/backup retention |
| Idempotency | Source hash dedupe. Event fingerprint (activity + type + date + source) | Same |
| Time | All timestamps stored UTC. Display IST. Report date anchors relative dates ("yesterday") | Same, with project calendars |
| Observability | Structured logs. LLM calls logged with prompt hash, latency, tokens | Tracing, dashboards, drift alerts on confidence distribution |
| Privacy | Synthetic data only | Data stays on-prem. No external LLM calls |

## 9. Quality attributes and how the architecture meets them

| Attribute | Mechanism |
|---|---|
| Trust | Confidence + review queue + audit + reversible applies |
| Accuracy | Tag-number extraction, hybrid retrieval, alias memory, LLM adjudication on ambiguous cases only |
| Latency | Rules/fuzzy first (ms). LLM only where needed. CAG prefix reduces repeated prompt cost |
| Cost | Most events never hit the LLM. Small open-weight model |
| Evolvability | Pluggable `DecisionScorer`, `ChatModel`, `ScheduleConnector` interfaces at the three seams that will change (introduced when the second implementation arrives, not before) |
