# Deployment Plan

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [System architecture](../architecture/SYSTEM_ARCHITECTURE.md#6-hackathon-topology)

## 1. Environments

| Env | Purpose | Where |
|---|---|---|
| Local dev | Daily work | Each laptop: `.venv` + `npm run dev` |
| Demo | Judging | One laptop (primary) + one backup laptop, same image |
| Pilot (future) | Shadow mode on one project | OIL on-prem VM |
| Production (future) | Multi-project | OIL on-prem / sovereign cloud, Kubernetes or VMs |

## 2. Hackathon deployment

### Option A: no Docker (fallback, fastest)
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
python -m scripts.seed            # loads synthetic project + history
uvicorn p2e.main:app --port 8000  # serves API + built SPA
```

### Option B: Docker Compose (primary)
```
compose.yaml
  app:   multi-stage image (node build → python runtime), port 8000,
         volume ./data:/app/data, env_file .env
  llm:   (optional profile "local-llm") OpenAI-compatible local model server
         for fully offline runs
```
`docker compose up` → seed runs on first start if the DB is empty.

### Demo resilience checklist
| Failure | Mitigation |
|---|---|
| Venue Wi-Fi down | `P2E_LLM_REPLAY=true`: recorded LLM responses for the demo dataset. A banner shows the mode honestly |
| HF endpoint slow or rate-limited | Replay mode, or the local-LLM profile |
| Laptop failure | Backup laptop with the identical image and DB snapshot |
| Browser voice blocked (no mic permission / non-Chrome) | Type the same utterance. Pre-tested in Chrome |
| Corrupted state mid-demo | `scripts/reset_demo.py` restores the DB snapshot in < 5 s |
| Everything fails | 3-minute recorded backup video |

## 3. Production deployment (target)

```
             ┌──────────── OIL data centre (no egress for project data) ────────────┐
 Users ─TLS─►│ Ingress / reverse proxy (OIDC SSO, WAF)                              │
             │   ├─ web (static SPA via CDN or nginx)                               │
             │   └─ api (FastAPI, ≥2 replicas, stateless)                           │
             │        ├─ PostgreSQL 16 + pgvector (HA, PITR backups)                │
             │        ├─ job queue → workers (extract, link, OCR, ASR, memory build)│
             │        ├─ object storage (MinIO), versioned, encrypted               │
             │        ├─ vLLM (GPU) open-weight model · embeddings service          │
             │        └─ connectors: P6 EPPM API / MS Project Online / PMIS         │
             │   observability: OpenTelemetry → Prometheus/Grafana/Loki             │
             └──────────────────────────────────────────────────────────────────────┘
```

| Concern | Plan |
|---|---|
| Sizing (start) | API 2×(2 vCPU, 4 GB). Workers 2×(4 vCPU, 8 GB). Postgres 4 vCPU/16 GB. 1× GPU (24–48 GB) for an 8B model + embeddings |
| CI/CD | GitHub Actions or OIL GitLab: lint → pytest → eval on the synthetic set (fail if auto-apply precision < 95%) → build image → deploy to pilot |
| Migrations | Alembic, run as a pre-deploy job. Backward-compatible migrations only |
| Secrets | Vault / K8s secrets. No secrets in images |
| Security | SSO + RBAC. Network policies. Encryption at rest and in transit. Audit export to SIEM |
| Rollout | Pilot in **shadow mode** (no auto-apply) → enable auto-apply per discipline once measured precision ≥ target |
| DR | Daily full + WAL archiving. RPO ≤ 15 min, RTO ≤ 4 h |
| Model updates | New model/prompt version must pass the eval gate. Versioned prompts. Canary on one project |

## 4. Release checklist (hackathon)

- [ ] `pytest` green. Eval report regenerated from the frozen test split
- [ ] Fresh clone → running in < 2 min (Docker and no-Docker paths)
- [ ] Seed data loaded. Demo DB snapshot saved
- [ ] Replay cassette recorded for every demo input
- [ ] Demo rehearsed 3× end to end. Backup video recorded
- [ ] `.env` not committed. Demo API keys rotated after the event
- [ ] README updated with run instructions and doc links
