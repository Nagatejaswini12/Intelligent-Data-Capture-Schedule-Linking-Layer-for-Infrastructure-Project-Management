# Backend / API Architecture

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [System architecture](SYSTEM_ARCHITECTURE.md) · [Data](DATA_ARCHITECTURE.md) · [AI](../ai/AI_AGENT_ARCHITECTURE.md)

## 0. Implemented so far (Phase 1)

```
p2e/
├── main.py            create_app(db_url): routers + RFC 9457 problem+json error handlers
├── config.py          env settings: P2E_DB_URL (default sqlite:///data/p2e.db), P2E_SYNTHETIC_DIR
├── db/models.py       SQLAlchemy models (DB layer)
├── db/session.py      engine (SQLite FK pragma), init_db (create_all), sessionmaker
├── plan/importers.py  read_schedule (CSV | MSPDI via defusedxml) → validate_rows → import_schedule → verify_import; compare_schedules
├── plan/tags.py       regex tag extraction (LINE-1203, P-101A, TP-017, …)
├── plan/queries.py    read services: summary, filtered node list, node detail, hierarchy tree
├── api/schemas.py     Pydantic response contracts (never ORM objects)
└── api/routes.py      HTTP layer
scripts/phase1/init_database.py   create DB + import + verify + summary (idempotent)
tests/                            conftest.py, test_import.py (28 tests), test_api.py (12 tests)
```

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{status, database, version}`; 503 if the DB is unreachable |
| GET | `/api/v1/projects` | `ProjectOut[]` (code, name, timezone, data_date, timestamps, schedule_sources) |
| GET | `/api/v1/projects/{code}` | `ProjectOut` |
| GET | `/api/v1/projects/{code}/summary` | total nodes, executable activities, counts by type / level / discipline / area, planned date range, data date |
| GET | `/api/v1/projects/{code}/plan` | `PlanNodePage {items, total, limit, offset}`. Filters: `node_type`, `executable` (true = L5/L6 activities), `level`, `discipline`, `area`, `q` (case-insensitive literal substring of the name), `tag` (exact canonical tag), `limit` ≤ 1000, `offset`. Ordered as in the source schedule |
| GET | `/api/v1/projects/{code}/plan/{node_code}` | `PlanNodeDetailOut`: node + `ancestors`, `children`, `predecessors`, `successors` |
| GET | `/api/v1/projects/{code}/hierarchy` | nested `TreeNodeOut`; `root` (start node), `depth` (levels below root) |

Errors: `404`/`503` as `application/problem+json` `{type, title, status, detail}`; invalid query parameters (unknown discipline, level 9, limit 5000, …) → `422` problem with field locations. Dates are ISO `YYYY-MM-DD`; timestamps ISO 8601 with offset. OpenAPI at `/docs`.

Phase 1 is read-only, so there is no auth yet. Role API keys arrive with the first write endpoint (Phase 2). The planned `/plan/search` (linker candidates) is Phase 3.

**Tests (40):** database (clean import counts, single root, level nesting, DB equals source CSV field by field, logic-link count, tag index), tag gate (≥ 95% vs ground truth), idempotency (same file twice → one copy), conflict (different file refused, nothing changed), MSPDI equivalence and import, the init command run twice, 13 malformed-CSV cases + missing column + 4 malformed/unsafe XML cases + unsupported format (each rejected with nothing written), and API (health, projects, 404 problem responses, summary, every filter, literal search, tag lookup, pagination, 422 on bad parameters, activity / L6 / WBS detail, unknown ID, hierarchy full / depth / sub-tree / unknown root).

**Run**

```
.venv\Scripts\python -m pip install -r requirements-dev.txt         # once (fastapi, uvicorn, SQLAlchemy, defusedxml, pytest)
.venv\Scripts\python scripts\phase0\validate_dataset.py            # Phase 0 still 26/26
.venv\Scripts\python scripts\phase1\init_database.py               # create data/p2e.db + import schedule (re-runnable; --rebuild to start over)
.venv\Scripts\python -m pytest                                      # 40 tests
.venv\Scripts\python -m uvicorn p2e.main:app --port 8000            # API; interactive docs at http://localhost:8000/docs
```

## 1. Stack

| Layer | Choice | Status |
|---|---|---|
| Language | Python 3.14 (existing `.venv`) | installed |
| Web | FastAPI + Uvicorn | installed (Phase 1) |
| Validation | Pydantic v2 | installed |
| DB | SQLAlchemy 2 (SQLite → Postgres) | installed (Phase 1) |
| Agents | LangGraph + langchain-core | installed |
| Model access | langchain-huggingface | installed |
| Matching | rapidfuzz, NumPy | to add |
| Files | defusedxml (installed, Phase 1); openpyxl, python-multipart | to add (Phase 2) |
| Tests | pytest | installed (dev, `requirements-dev.txt`) |

Justification per dependency: [Technology decisions](../decisions/TECHNOLOGY_DECISIONS.md).

## 2. Repository layout (planned)

```
SIH26122/
├── docs/                    ← these documents
├── p2e/                     ← backend package (modules per System architecture §3)
│   ├── main.py              FastAPI app factory; mounts web/dist at /
│   ├── config.py            env settings (pydantic)
│   ├── api/                 routers: projects, plan, uploads, events, review, agent, analytics, stream, export
│   ├── plan/ ingest/ extract/ link/ decide/ agent/ memory/ analytics/ audit/ llm/ db/
├── web/                     ← React + Vite + TS frontend
├── data/synthetic/          ← Phase 0 dataset + generator
├── eval/                    ← evaluation harness + reports
├── tests/
├── requirements.txt
├── Dockerfile, compose.yaml
└── README.md
```

## 3. API (v1, prefix `/api/v1`)

All bodies are JSON validated by Pydantic. Errors use RFC 9457-style `{type, title, detail}`. Auth uses the header `X-API-Key` (hackathon) or a Bearer JWT (production).

### Projects & plan
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/projects` | any | List projects |
| POST | `/projects` | admin | Create project |
| POST | `/projects/{pid}/schedule` | planner | Upload schedule (CSV/MSPDI XML; XER stretch). Returns an import summary |
| GET | `/projects/{pid}/plan?level=&discipline=&area=&q=&status=` | any | Query plan nodes |
| GET | `/projects/{pid}/plan/{node_id}` | any | Node detail + events + audit |
| GET | `/projects/{pid}/plan/search?text=&discipline=` | any | Linker candidate search (used by the agent and the review UI) |

### Ingestion & events
| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/projects/{pid}/documents` | supervisor, planner | Upload a DPR/spreadsheet (multipart). Returns `202` + document id |
| POST | `/projects/{pid}/documents/text` | supervisor | Paste free-text report |
| GET | `/projects/{pid}/documents/{doc_id}` | any | Status + extracted events |
| GET | `/projects/{pid}/events?state=&discipline=&from=&to=` | any | Query events |
| POST | `/projects/{pid}/events` | supervisor | Log an event directly (used by the agent tool `log_event`) |

### Review & decisions
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/projects/{pid}/review?kind=in_review\|unmatched` | planner | Queue with candidates, features, evidence |
| POST | `/projects/{pid}/review/{event_id}/approve` | planner | `{node_id}`. Apply + learn alias |
| POST | `/projects/{pid}/review/{event_id}/reject` | planner | `{reason}` |
| POST | `/projects/{pid}/review/{event_id}/create-node` | planner | `{parent_id, name, …}`. NEW activity + apply |
| POST | `/projects/{pid}/review/merge` | planner | Merge duplicate events |
| POST | `/projects/{pid}/actuals/{audit_id}/undo` | planner | Compensating change |
| GET | `/projects/{pid}/audit?entity_id=` | planner | Audit trail |
| GET / DELETE | `/projects/{pid}/aliases[/{id}]` | planner | Inspect and remove learned aliases |

### Agent
| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/agent/sessions` | supervisor | New session (binds user, project) |
| POST | `/agent/sessions/{sid}/messages` | supervisor | `{text}` → `{reply, options[], pending_confirmation?, logged_event?}` (streamed variant via SSE) |

### Analytics, memory, export, live
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/projects/{pid}/analytics/summary` | any | KPIs per discipline/area |
| GET | `/projects/{pid}/analytics/dataset.csv` | planner | Actual-progress dataset |
| POST | `/memory/ask` | any | `{question, project_ids?}` → answer + citations |
| GET | `/projects/{pid}/export/schedule.xml` | planner | MSPDI with actuals |
| GET | `/projects/{pid}/export/actuals.csv` | planner | CSV for P6 import |
| GET | `/projects/{pid}/export/okf.zip` | planner | OKF knowledge bundle (stretch) |
| GET | `/projects/{pid}/stream` | any | SSE: `event_applied`, `review_added`, `doc_status` |
| GET | `/health` | public | Liveness + DB + LLM reachability |

## 4. Processing model

```
POST /documents ─► validate ─► store raw ─► 202 Accepted
                                   │
                                   └─► BackgroundTask: extract → link → decide → apply
                                                     (each event committed independently,
                                                      SSE notifications per step)
```

- Each event is processed in its own transaction, so one bad row never blocks a report.
- A document-level failure sets `status=failed` with an error. The raw file is retained for reprocessing (`POST /documents/{id}/reprocess`).
- Production: replace BackgroundTasks with queue workers. Same functions, different runner.

## 5. Security at trust boundaries (not simplified)

| Boundary | Control |
|---|---|
| Upload | Extension and magic-byte check. Max 10 MB. Max 5,000 spreadsheet rows. Stored under a hash name (never a user path) |
| XML (MSPDI) | `defusedxml` (blocks XXE and entity expansion) |
| XLSX | `openpyxl` read-only, `data_only=True` (cached values, no formula evaluation). Macros are never executed (`.xlsm` rejected) |
| CSV export | Formula-injection escape for cells starting with `= + - @` |
| LLM input | Report text is wrapped as data with explicit delimiters. The system prompt states the text is untrusted. No tools are exposed during extraction |
| LLM output | Schema validation. `source_span` substring check. Candidate-ID whitelist. Date/range rules |
| AuthZ | Role + project + discipline checks on every route. Supervisors can only log for their scope |
| Secrets | `.env` (already git-ignored). Never logged. HF token server-side only |
| Rate limits | Per-key limit on agent and upload endpoints (simple in-process token bucket for the hackathon) |
| Audit | Append-only, hash-chained |

## 6. Configuration (`.env`)

```
P2E_DB_URL=sqlite:///data/p2e.db
P2E_UPLOAD_DIR=data/uploads
P2E_LLM_PROVIDER=huggingface        # or openai_compatible (local server)
P2E_LLM_MODEL=<hf model id>
P2E_EMBED_MODEL=BAAI/bge-small-en-v1.5
HF_TOKEN=...
P2E_LLM_REPLAY=false                # true = demo cassette mode
P2E_API_KEYS=supervisor:...,planner:...,admin:...
```

## 7. Performance budget (hackathon)

| Operation | Budget |
|---|---|
| Schedule import 350 nodes | < 2 s |
| Linking one event, no LLM | < 50 ms |
| Linking one event, with LLM adjudication | < 3 s |
| DPR with 15 items, end-to-end | < 10 s |
| Agent turn | < 3 s |
