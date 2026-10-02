# Data & Database Architecture

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [System architecture](SYSTEM_ARCHITECTURE.md) · [Backend](BACKEND_API.md)

## 1. Storage choices

| Store | Hackathon | Production | Holds |
|---|---|---|---|
| Relational DB | SQLite (single file, WAL mode) | PostgreSQL 16+ | Everything structured |
| Vectors | NumPy matrix in memory, rebuilt from DB on start (≤ 10k nodes) | `pgvector` columns | Plan-node and knowledge embeddings |
| Raw evidence | `data/uploads/<sha256>` on disk | Object storage (MinIO/S3), versioned | Original files, exactly as received |
| Agent sessions | LangGraph SQLite checkpointer | LangGraph Postgres checkpointer | Conversation state |
| Knowledge export | `exports/okf/<project>/` Markdown | Git repo / object storage | OKF bundle |

One SQLAlchemy model set works on both SQLite and Postgres. Portable types only (no SQLite-only tricks). Migrations via Alembic from Phase 5 onward. Before that, `create_all` is enough.

## 2. Entity-relationship overview

```
project 1─* plan_node (self-ref parent_id: L1…L6 tree)
project 1─* source_document 1─* progress_event *─1 plan_node (linked_node_id, nullable)
progress_event 1─* link_candidate *─1 plan_node
plan_node 1─* actual_change (via audit_log)
project 1─* alias *─1 plan_node
project 1─* knowledge_entry
user *─* project (role, discipline, areas)
audit_log (append-only, references any entity)
sheet_template (header-set hash → mapping)
```

## 3. Tables

### 3.0 Implemented in Phase 1 (`p2e/db/models.py`)

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `project` | One per schedule root (L1) | `code` unique, `name`, `timezone` (Asia/Kolkata), `data_date` (status date; from MSPDI `StatusDate` or the Phase 0 manifest), timestamps |
| `source_document` | Provenance of each imported file | `kind='schedule_import'`, `format` csv\|mspdi, `filename`, `sha256` (unique per project → idempotent re-import), `size_bytes`, node/activity counts, `created_at` |
| `plan_node` | The whole L1–L6 tree in one table | `code` (activity ID or WBS code, unique per project), `node_type` wbs\|summary\|activity, `parent_id` (self FK), `level` 1–6, `seq` (source order), `name`, `wbs_code`, `discipline`, `area`, `activity_type`, planned start/finish/duration, `planned_qty`/`qty_unit`, imported `actual_start`/`actual_finish`, `source_document_id`, timestamps |
| `plan_tag` | Canonical tags per activity (exact-lookup index for linking) | PK (`node_id`, `tag`), index on `tag` |
| `plan_dependency` | Schedule logic | PK (`successor_id`, `predecessor_id`), `link_type` FS\|SS\|FF\|SF, `lag_days` |

Database constraints mirror importer validation: level 1–6; `activity` only at level 5/6; discipline enum; `planned_start <= planned_finish`; actual finish needs an earlier actual start; no self-links. SQLite enforces foreign keys (`PRAGMA foreign_keys=ON` per connection).

**Hierarchy vs executable work.** L1–L4 are `wbs` nodes. Executable work is `node_type='activity'` at L5 (302) or L6 (15). The three L5 `summary` nodes (T-401, T-402, K-301) group L6 activities. Nothing is flattened: every node keeps its parent.

**Schedule import** (`p2e/plan/importers.py`): read the file (≤ 10 MB; CSV must be UTF-8 with all 17 Phase 0 columns; XML parsed with `defusedxml`, so DTD entities and external references are rejected) → validate the *whole* schedule (unique IDs, one L1 root, parents exist and are not activities, level = parent + 1, activities at L5/L6 only, summary nodes have children, discipline enum, ISO dates, start ≤ finish, duration consistency, actual-date sanity, quantities, predecessor references and link types) → insert everything in one transaction (nothing is written if any check fails) → extract tags → `verify_import` re-checks the stored tree.

**Differences from the design below (decided 2026-10-02, see D30):** integer surrogate primary keys instead of UUIDs; the business key is (`project_id`, `code`). `tags` is a side table rather than a JSON column. `name_norm`, `status`, `percent_complete`, `is_new` and `embedding` are not created yet; they arrive with the phases that compute them.

The design below is the full target schema.


### `project`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| code, name | text | e.g. `CGS-EXP-01` |
| timezone | text | default `Asia/Kolkata` |
| data_date | date | Schedule status date |
| thresholds | json | `{t_auto, t_review}` calibrated values |

### `plan_node`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| project_id | fk | |
| activity_code | text, unique per project | ID from P6/MSP |
| parent_id | fk self, nullable | WBS tree |
| level | smallint 1–6 | |
| name | text | As in plan |
| name_norm | text | Glossary-normalized (indexed) |
| wbs_path | text | `Area3/Piping/Line 1203` |
| discipline | enum | civil, piping, static_eq, rotating_eq, electrical, instrumentation, hse, other |
| area | text | |
| tags | json array + `plan_tag` side table (tag, node_id) for indexed lookup | |
| planned_start, planned_finish | date | |
| planned_qty, qty_unit | numeric, text | Enables granularity aggregation |
| actual_start, actual_finish | timestamptz, nullable | **Written only by the apply engine** |
| percent_complete | numeric | |
| status | enum | not_started, in_progress, completed, on_hold |
| is_new | bool | Created from an unmatched field report |
| embedding | vector / blob | |

### `source_document`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| project_id | fk | |
| kind | enum | dpr_text, spreadsheet, diary_scan, time_agent, schedule_import |
| filename, mime, size_bytes | | Validated at upload |
| sha256 | text unique per project | Dedupe |
| report_date | date | Anchor for relative dates |
| discipline, submitted_by | | |
| storage_uri | text | Raw file location |
| status | enum | received, extracting, extracted, failed |
| error | text | |

### `progress_event` (the central fact table)
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| project_id, source_document_id | fk | |
| activity_text | text | As written in the field |
| event_type | enum | start, finish, progress, hold, resume |
| event_at | timestamptz | Resolved |
| quantity, unit | | |
| discipline, area | | Extracted |
| tags | json | |
| delay_reason, delay_category | text, enum | material, manpower, weather, permit, design, equipment, other |
| source_span | text | Verbatim evidence |
| source_locator | json | `{line: 14}` or `{sheet: "Piping", row: 23}` |
| extraction_confidence | real | |
| linked_node_id | fk plan_node, nullable | |
| link_confidence | real | Calibrated |
| link_method | enum | tag, alias, fuzzy, semantic, llm, manual |
| granularity | enum | same, finer, coarser |
| state | enum | extracted → linked → **applied / in_review / unmatched / rejected / superseded** |
| fingerprint | text | hash(project, node/text, type, date) for duplicate detection |
| created_at, decided_at, decided_by | | |

### `link_candidate`
`(event_id, node_id, rank, score, features json, reason text)`. Kept for explainability in the review UI and for evaluation.

### `alias` (MAG)
| Column | Notes |
|---|---|
| project_id, phrase_norm, node_id | Unique together |
| discipline | |
| confirmations | int |
| confirmed_by_planner | bool |
| scope | project / org |
| last_used_at | |

### `audit_log` (append-only)
| Column | Notes |
|---|---|
| id | bigint, monotonic |
| at | timestamptz |
| actor | user id or `system:auto_apply` |
| action | apply_actual, undo, approve, reject, create_node, alias_add, alias_delete, threshold_change, import |
| entity, entity_id | |
| before, after | json |
| event_ids | json (evidence) |
| confidence, rule | Why this happened |
| prev_hash, hash | Hash chain makes tampering detectable |

Append-only is enforced in code (no update/delete paths) and in production by DB permissions (INSERT-only role) plus a trigger. Undo is a new compensating entry, never a deletion.

### Others
- `sheet_template(header_hash, mapping json, discipline)`
- `knowledge_entry(id, project_id, category, title, body_md, confidence, sources json, embedding)`
- `user(id, name, role, discipline, areas json, api_key_hash)`

## 4. Event state machine

```
             ┌──────────── rejected
             │
extracted ─► linked ─┬─► applied ─► superseded (by later/better evidence or undo)
                     ├─► in_review ─► applied | rejected | unmatched
                     └─► unmatched ─► applied (planner picks node) | new node created → applied | rejected
```

## 5. Applying actuals (rules)

- **Actual start** = earliest credible `start` (or first `progress`/sub-progress) event.
- **Actual finish** = `finish` event for the whole activity, or quantity reaching the planned quantity.
- A later event never silently moves an existing actual. A conflicting date creates a review item with both evidences.
- Every change to `actual_*` runs in the same transaction as its `audit_log` row.

## 6. Derived datasets (Phase 6)

| View / export | Grain | Fields |
|---|---|---|
| `v_actual_progress` | activity | code, discipline, area, planned S/F, actual S/F, planned/actual duration, slip days, n_sources, delay categories |
| `v_discipline_daily` | discipline × day | events reported, activities started/finished, review backlog, reporting freshness |
| `v_productivity` | activity type × discipline | qty/day, duration ratio stats |
| Export | | CSV and Parquet (Parquet only if `pyarrow` is added later; CSV is enough for the hackathon) |

## 7. Synthetic data design (Phase 0, implemented)

Full contract: [`data/synthetic/README.md`](../../data/synthetic/README.md).

| File | Content | Hard cases embedded |
|---|---|---|
| `schedule/schedule.csv` / `schedule.xml` | 469 nodes, 317 L5/L6 activities, 7 disciplines, 4 areas, predecessors, actuals to the data date (31 Aug) | Similar names across areas, tags only inside names, L6 detail under tank/compressor summaries |
| `reports/dpr_<date>_<group>.txt` | 81 DPRs: 6 discipline groups × 14 report days, 3 deliberately missing | Abbreviations, typos, Hinglish, relative/explicit dates, multi-item lines, coarse statements, new work, unknown tags, plan-ahead negatives |
| `spreadsheets/piping_spool_erection_tracker.xlsx` | Spool-level rows | Finer granularity, 4 line-number notations, wrong dates, title rows |
| `spreadsheets/electrical_cable_log.xlsx` | Cable pull + termination rows, Summary sheet | Terse headers, cable-number → group mapping, ✓ marks |
| `spreadsheets/instrument_installation_register.xlsx` | Instrument mounting + tubing dates | Tag notation variants, `pending`/`N/A` values |
| `ground_truth/labels.csv` | 433 items: true activity, candidates, match label, difficulty, expected band/outcome, hard-case tags | dev/test split by report day, not by row |
| `ground_truth/expected_extraction.json` | Per document: expected items, header mappings, noise lines | — |
| `ground_truth/truth_events.csv`, `activity_truth.csv`, `new_work.csv` | Real events, expected end-of-window actuals and tags, unplanned work | — |
| `glossary.json` | Abbreviations, Hinglish, verbs, tag conventions, date formats | — |

Generator: per-section seeded RNGs (seed 26122). Output is byte-identical on every run (checked by the validator). Time-agent dialogue scripts were moved to Phase 4, where they are built from `truth_events.csv`.

## 8. Data governance

- Synthetic data only in the hackathon. Real data stays on-prem in production.
- PII: supervisor names are pseudonymized in exports and the knowledge base.
- Retention: raw evidence is kept for the project's life plus the contractual period. Audit is never deleted.
- Backups: production uses daily Postgres PITR and versioned object storage.
