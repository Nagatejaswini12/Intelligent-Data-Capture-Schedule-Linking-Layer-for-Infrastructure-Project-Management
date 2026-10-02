# Future Scope

[← Master plan](../PROJECT_MASTER_PLAN.md)

From hackathon prototype to an OIL production system, in increasing order of effort.

## 1. Roadmap

| Horizon | Theme | Items |
|---|---|---|
| **H1: Pilot (0–3 months)** | Trust on real data | Shadow mode on one live project. OIL's real DPR/WBS templates. Per-discipline thresholds. Postgres + pgvector. SSO/RBAC. On-prem vLLM. P6 XER import. Planner feedback loop metrics |
| **H2: Integration (3–6 months)** | Close the loop | P6 EPPM API / MS Project Online write-back (with planner approval policy). PMIS integration. Mobile PWA with offline capture and later sync. Hindi/Assamese voice via on-prem Whisper. OCR for scanned diaries (vision LLM / PaddleOCR) |
| **H3: Intelligence (6–12 months)** | Use the clean data | Delay/risk pattern discovery. Duration forecasting from actual productivity. Early-warning alerts (an activity "should have started" but no reports). Learned ranker replacing the logistic scorer. Photo evidence linking (geo-tagged site photos → activity) |
| **H4: Institutional memory (12+ months)** | Learn across projects | Org-wide alias and knowledge base (promoted from projects). OKF knowledge bundles per closed project. Planning assistant that suggests realistic durations for new schedules from history. Contractor/discipline benchmarking |

## 2. Specific extensions

| Extension | Value | Prerequisite |
|---|---|---|
| Re-evaluate **Jev** (or similar System-One decision models) as a `DecisionScorer` | Faster/cheaper routine decisions | A second scorer actually needed. An on-prem deployment option or a synthetic-only benchmark. Independent verification |
| Multi-agent recovery planner | Suggests resequencing when delays cluster | Reliable actuals + CPM integration |
| Quantity-based progress from IoT / drones | Objective progress evidence | Site data feeds |
| WhatsApp/SMS capture channel | Reach supervisors where they already are | Approved enterprise messaging gateway |
| Earned value integration | Cost + schedule performance | Cost-loaded schedules |
| Active learning | Review queue prioritizes the items that most improve the model | Enough labels |
| Federated / multi-site deployment | Several OIL projects, one memory | Governance on data sharing |

## 3. Scalability path

| Dimension | Hackathon | Scale step |
|---|---|---|
| Activities per project | 350 | 50k+ → pgvector HNSW index, per-discipline partitions |
| Concurrent users | 5 | 500+ → stateless API replicas, queue workers |
| Reports per day | 20 | 2,000+ → batching, LLM prefix caching (CAG), smaller distilled extractor |
| Projects | 1 | Many → tenant column + row-level security in Postgres |
| Model | One 8B | Router: rules → small model → larger model only for hard cases |

## 4. Deliberately not planned

- Replacing P6/MSP scheduling (CPM stays in the scheduling tool).
- Fully autonomous schedule changes without human approval policies.
- Sending OIL project data to external AI services.
