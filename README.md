# P2E Bridge — SIH26122

Intelligent data capture & schedule-linking layer for infrastructure project management: field reports (DPRs, trackers, supervisor messages) → extraction → schedule linking (RAG / CAG / MAG) → planner validation → verified, audited actuals → project analytics and cited Q&A. Synthetic demo project `CGS-EXP-01`.

## Run

```
# 1. backend (once): environment + data
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python scripts\phase1\init_database.py
.venv\Scripts\python scripts\phase2\ingest_documents.py
.venv\Scripts\python scripts\phase3\link_events.py

# 2. frontend (once): install + build -> web\dist (served by FastAPI at /)
cd web; npm install; npm run build; cd ..

# 3. run: choose your own keys (16+ characters), never commit them
$env:P2E_API_KEYS = "planner:<planner key>,supervisor:<supervisor key>"
.venv\Scripts\python -m uvicorn p2e.main:app --port 8000
# open http://localhost:8000 , sign in with one of the keys, set "As of" to 2026-09-16 for the synthetic project

# upgrade W1–W5 (docs/plan/UPGRADE_PLAN.md)
.venv\Scripts\python scripts\phase1\init_database.py --rebuild                  # needed once if data\p2e.db predates .docx/.xer support
.venv\Scripts\python scripts\phase1\init_database.py --schedule my_plan.xer     # Primavera P6 XER (also .csv / MS Project .xml)
.venv\Scripts\python scripts\phase8\generate_reports.py --period weekly --as-of 2026-09-16   # PM report -> exports\reports\
.venv\Scripts\python scripts\phase8\evaluate_blind.py --blind data\blind        # outside-written reports + labels.csv

# development with hot reload instead of step 2 (proxies /api to :8000)
cd web; npm run dev        # http://localhost:5173
```

Docs: [Master plan](docs/PROJECT_MASTER_PLAN.md) · [Phase plan](docs/plan/PHASE_PLAN.md) · [Backend API](docs/architecture/BACKEND_API.md) · [Frontend](docs/architecture/FRONTEND.md) · [Linking layer](docs/ai/LINKING_LAYER.md) · [Time Agent](docs/ai/TIME_AGENT.md)

## Checks

```
.venv\Scripts\python -m eval.run          # one-command evaluation -> eval/report.md
.venv\Scripts\python scripts\smoke.py      # end-to-end smoke over the HTTP API
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts\phase0\validate_dataset.py
.venv\Scripts\python scripts\phase3\evaluate_linking.py
.venv\Scripts\python scripts\phase5\evaluate_apply.py
.venv\Scripts\python scripts\phase6\evaluate_qa.py
cd web; npm test; npm run build
```
