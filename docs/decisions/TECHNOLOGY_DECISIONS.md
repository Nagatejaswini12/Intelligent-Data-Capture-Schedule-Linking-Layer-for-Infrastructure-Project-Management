# Technology Decisions

[← Master plan](../PROJECT_MASTER_PLAN.md)

Rule applied to every choice: **use what is installed → stdlib → native platform → a small, well-known dependency → only then something bigger.** Each new dependency has a one-line justification. Nothing is installed during planning.

## 1. Decision records

| # | Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Language | Python 3.14 (existing `.venv`) | Node/TS backend | AI ecosystem; LangGraph already installed |
| D2 | Agent orchestration | **LangGraph** (installed) | CrewAI, AutoGen, hand-rolled loop | Explicit state graph = predictable, testable slot-filling. Built-in checkpointer gives session memory |
| D3 | Model access | **langchain-huggingface** (installed) behind a `llm/gateway` | Direct vendor SDKs | Open-weight models (sovereignty). Same interface for HF endpoints and on-prem servers |
| D4 | LLM class | Open-weight 7–9B instruct, picked by a bake-off on dev data | Proprietary hosted frontier model | NDA/on-prem requirement. Small model suffices because rules/fuzzy handle most work |
| D5 | Web framework | **FastAPI** + Uvicorn | Flask, Django | Pydantic-native (installed), async, OpenAPI docs free, SSE support |
| D6 | DB (hackathon) | **SQLite** via SQLAlchemy 2 | Postgres from day 1 | Zero setup. SQLAlchemy keeps the move to Postgres a config change |
| D7 | DB (production) | **PostgreSQL + pgvector** | Separate vector DB (Qdrant, Milvus) | One system for relational + vectors + audit. Fewer moving parts |
| D8 | Vector search (hackathon) | **NumPy in-memory cosine** | FAISS, Chroma | ≤10k nodes takes microseconds; no extra service |
| D9 | Fuzzy matching | **rapidfuzz** | stdlib `difflib` | `difflib` is slow and lacks token-set scoring. rapidfuzz is small, MIT-licensed, C-fast |
| D10 | Embeddings | `BAAI/bge-small-en-v1.5` via **HF endpoint** (`HuggingFaceEndpointEmbeddings`) | Local sentence-transformers | Avoids pulling torch (~GBs) into the hackathon env. Self-host in production |
| D11 | Spreadsheets | **openpyxl** | pandas | Only reading cells is needed. pandas is heavy for that |
| D12 | XML | stdlib `xml.etree` + **defusedxml** for untrusted input | lxml | Security at the trust boundary; tiny dependency |
| D13 | P6 XER | Hand-written parser (XER is tab-delimited `%T/%F/%R` lines) using stdlib `csv` — stretch | `xerparser` package | ~40 lines. Add the package only if edge cases bite |
| D14 | Background jobs | FastAPI `BackgroundTasks` | Celery + Redis | One process for the demo. Production → queue workers |
| D15 | Live updates | **SSE** | WebSockets | One-way server→client is all that's needed. Native `EventSource` |
| D16 | Frontend | **React + TypeScript + Vite** | Next.js, server templates + HTMX | SPA with chat, live tables, review keyboard flow. Team familiarity. Static build served by FastAPI |
| D17 | Voice | **Browser Web Speech API** | Whisper (local/hosted) | PS says production ASR not required. Zero dependency. Whisper on-prem is future scope |
| D18 | Charts | **Recharts** | Chart.js, D3 | One library, React-native. Used on the dashboard only |
| D19 | Gantt/timeline | Custom CSS-grid bars | frappe-gantt, dhtmlx | Read-only plan-vs-actual bars are ~100 lines |
| D20 | Confidence model | **Logistic regression in NumPy** on hand-built features, calibrated | scikit-learn, GBDT, LLM self-confidence | Interpretable, calibratable, no extra dependency. LLM self-confidence is poorly calibrated |
| D21 | Memory (MAG) | DB tables + LangGraph checkpointer | mem0, Zep, Letta | Requirements are narrow (aliases, sessions). No framework needed |
| D22 | Knowledge export | **OKF**-style Markdown + YAML (PyYAML) — stretch | Custom JSON | Portable, human-readable, provenance-carrying; matches "institutional memory" |
| D23 | Jev | **Not used** | — | Hosted, 2 weeks old, unverified, conflicts with NDA. See [evaluation](../ai/AI_APPROACHES_EVALUATION.md#5-jev-jev-not-an-acronym) |
| D24 | Multi-agent | **No** (one graph per task) | Supervisor/worker agent swarm | Pipeline problem. Swarms add failure modes without benefit |
| D25 | Auth | API keys per role (hackathon) → OIDC SSO (production) | Full auth in hackathon | Demo realism without an IdP; RBAC checks are already in every route |
| D26 | Packaging | Docker Compose + a no-Docker path | Kubernetes in hackathon | One command. K8s is production only |
| D27 | Testing | pytest + fake LLM + replay cassettes | Live LLM in tests | Deterministic, fast, offline |
| D28 | Phase 0 data tooling | Stdlib only: own deterministic XLSX writer (`scripts/phase0/xlsx_min.py`), JSON glossary | openpyxl, PyYAML | Nothing new installed; openpyxl stamps timestamps, which breaks byte-identical regeneration. openpyxl is still the Phase 2 reader |
| D29 | Phase 1 dependencies | Installed: fastapi 0.142.2, uvicorn 0.54.0, SQLAlchemy 2.1.2, defusedxml 0.7.1 (`requirements.txt`); pytest 9.1.1 (`requirements-dev.txt`) | pydantic-settings, python-multipart, alembic | Only what Phase 1 runs. Env config is a 10-line dataclass. Upload and migrations are not needed yet. Transitive: starlette, annotated-doc, opentelemetry-api (pulled by FastAPI) |
| D30 | Plan storage shape | One `plan_node` table for L1–L6 (`node_type` wbs\|summary\|activity), integer surrogate PKs, business key (`project_id`, `code`), `plan_tag` + `plan_dependency` side tables | UUID PKs, separate WBS/activity tables, JSON tag column | Keeps the hierarchy queryable with one self-FK. Integer keys are simpler and portable. Side tables give indexed exact tag lookup and enforceable logic links. Supersedes the "uuid pk" note in the data design |
| D31 | Re-import policy | Same file (sha256) → no-op; different file for an existing project → refused | Upsert / merge | Merging changes into a baseline that already has captured actuals is re-baselining (Phase 5+ scope). Refusing is the safe default. `init_database.py --rebuild` starts over |
| D32 | MSPDI identity | Activities by Text1 (activity ID), WBS nodes by `WBS`, hierarchy by `OutlineNumber`; L5 summary tasks get `<WBS>#<outline>` | Name-based IDs | MSPDI has no own ID field for summary tasks in this export. CSV is the primary source; the XML is verified equivalent on every field both formats carry |

## 2. Dependency budget

### Already installed (pinned in `requirements.txt`)
`langgraph==1.2.12`, `langchain-core==1.6.6`, `langchain-huggingface==1.2.2` (+ transitive: pydantic, httpx, huggingface_hub, PyYAML, …)

### To add when implementation starts (not now)
| Package | Phase | Why |
|---|---|---|
| fastapi, uvicorn | 1 | API server (**installed**) |
| python-multipart | 2 | FastAPI file uploads |
| sqlalchemy | 1 | ORM / portable SQL (**installed**) |
| defusedxml | 1 | Safe XML import (**installed**) |
| openpyxl | 2 | XLSX ingestion |
| rapidfuzz | 2–3 | Fuzzy matching |
| numpy | 3 | Cosine, logistic fit |
| langgraph-checkpoint-sqlite | 4 | Persistent agent sessions |
| pytest (dev) | 1 | Tests (**installed**) |
| alembic (production) | 5+ | Migrations |

Frontend: `react`, `react-dom`, `react-router-dom`, `recharts`, plus `vite` and `typescript` (dev).

**Explicitly not added:** pandas, torch/sentence-transformers, Celery/Redis, a vector DB, a CSS framework, a state library, a Gantt library, a memory framework.

## 3. Python 3.14 compatibility note

The environment uses Python 3.14.7. Verify wheels exist for `rapidfuzz`, `numpy` and `openpyxl` at install time. If any lacks a 3.14 wheel, pin a 3.12 venv for the hackathon (record the change here).
