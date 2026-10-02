# Schedule-Linking Layer (Phase 3)

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [AI approaches evaluation](AI_APPROACHES_EVALUATION.md) · [Backend](../architecture/BACKEND_API.md) · [Data](../architecture/DATA_ARCHITECTURE.md)

Input: a Phase 2 `progress_event` with `validation_status = valid`. Output: one `event_link` decision, **matched** (to one L5/L6 activity), **review** (planner decides, candidates attached) or **unmatched** (`new_activity`, `unknown_reference`, `no_candidate`). The linker never forces an uncertain event onto an activity.

## 1. Pipeline and where each technology works

```
ProgressEvent ──► normalize (CAG context: glossary, synonyms, typo vocabulary, codes cut out)
                    │
                    ▼
          stage 1: deterministic evidence      exact canonical tags (plan_tag + field tag extractor on activity names)
                   + MAG object aliases         confirmed field names for objects
                    │ any candidate sharing the reported work action?
              yes ◄─┴─► no ──► stage 2: RAG retrieval  IDF-weighted word overlap over all L5/L6 names (top-k)
                    │                              + attribute retrieval: discipline + area + work action
                    ▼
          score every candidate: object (tag / alias / unique attribute) · action · words · area · discipline
                    ▼
          gates ──► MATCHED   object AND action agree, no area/discipline conflict, margin ≥ 0.15, score ≥ 0.70,
                    │         alias evidence only if confirmed ≥ 2×
                    ├─► REVIEW    anything else with candidates ──► optional LLM tie-breaker (advisory suggestion only)
                    └─► UNMATCHED novelty wording ("extra", "temporary", "re-weld"…) · tags not in the schedule · nothing retrieved
                    ▼
          cross-source date-conflict layer (Phase 3.1) ──► contradiction: automatic match held as REVIEW (§6)
                    ▼
          planner confirm ──► MAG learns (object / action alias)      planner reject ──► nothing learned
                    ▼
          OKF v0.2 export of the stable knowledge (glossary, rules, activity families, confirmed aliases)
```

| Technology | Real role | Code | Can be switched off / evaluated separately |
|---|---|---|---|
| **RAG** | Stage-2 candidate retrieval for reports the deterministic layer cannot place (no tag, partial description, coarse scope); every candidate keeps `retrieval_methods`, `matched_terms`, `features`, `reasons`. Grounds the optional LLM: it may only choose among retrieved codes | `p2e/link/retrieve.py` | `decide(..., retrieval=False)`; ablation in the eval |
| **CAG** | One cached, versioned project context: glossary (abbreviations, Hinglish), matching rules, schedule vocabulary, project metadata. Used for normalization/scoring and rendered as the fixed LLM prompt prefix | `p2e/link/context.py`, `p2e/link/rules.json` | context with empty glossary/synonyms; ablation in the eval |
| **MAG** | Alias memory learned **only** from planner confirmations; feeds stage 1 (object aliases) and action detection (action aliases) | `p2e/memory/aliases.py`, table `alias` | learning curve in the eval; aliases revocable |
| **OKF** | Export/interoperability layer (OKF v0.2 bundle); SQLite stays the source of truth | `p2e/memory/okf.py` | CLI `--okf`, `GET …/knowledge/okf.zip` |
| **JEV** | Investigated, **not implemented** (see §7) | — | — |
| LLM | Optional tie-breaker for REVIEW with ≥ 2 candidates; off unless `P2E_LLM_ENDPOINT` is a self-hosted endpoint | `p2e/link/adjudicate.py` | env var |

Retrieval is lexical + attribute, not dense embeddings: field reports are dominated by codes and abbreviations that the tag/glossary layers handle, and an embedding model would need a local server (no confidential text may go to a public API). A local embedding stage can be added inside `retrieve.py` without changing decisions or storage.

## 2. CAG: what is cached

| Cached | Source | Changes when |
|---|---|---|
| Abbreviations + Hinglish terms (minus ambiguous short forms listed in `no_expand`) | `glossary.json` (`P2E_GLOSSARY`) | file edited |
| Work-action lexicon, equivalent actions, synonyms, novelty markers, stopwords, thresholds | `p2e/link/rules.json` (version `1`) | file edited |
| Schedule vocabulary (typo-correction targets), disciplines, areas, project code/data date | imported schedule | a schedule is (re)imported |

Version = first 12 hex of SHA-256 over {glossary SHA-256, rules SHA-256, SHA-256 of the project's schedule imports, context format}. `get_context` recomputes the fingerprint on every call (cheap) and rebuilds only on change; `POST …/context/refresh` (admin) forces a rebuild. Every `event_link` stores the `context_version` it used, and a changed version makes the next linking run re-link pending/auto decisions. **Not cached:** progress events, link decisions, aliases (all dynamic).

## 3. MAG: learning rules and safety

- Learns only in `POST …/links/{event}/confirm` (planner/admin). Linker predictions and rejections teach nothing.
- **Object alias**: the event named its object without a usable tag → normalized object words → the activity's tags (generalises to every step of that object, e.g. "fire water ring main" → `LINE-1407`), or the activity itself if it has no tags.
- **Action alias**: the event's work wording matched none of the activity's actions → words → the activity's single action.
- Refused: phrases that already name more than one object in the schedule ("foundation": 13 objects), empty/over-long phrases, a phrase already learned for a different target (never overwritten).
- **Trust ladder**: an alias confirmed once surfaces and ranks the candidate but the decision stays REVIEW; from 2 confirmations (`alias_auto_min_confirmations`) it may support an automatic match. Revoked aliases are never used. `use_count` / `last_used_at` record use in applied matches. Each decision stores the `mag_version` (fingerprint of the active aliases).

## 4. OKF v0.2 export

Spec: [knowledge-catalog/okf/SPEC.md](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), version 0.2 (checked 2026-10-02). Bundle: `index.md` (frontmatter `okf_version: "0.2"`), `log.md`, `project/{overview,glossary,matching-rules}.md`, `schedule/<activity-type>.md`, `aliases/index.md`, `aliases/<kind>-<phrase>.md`. Frontmatter uses `type` (required), `title`, `description`, `tags`, `generated {by, at}`, `sources [{id, resource, title, last_modified}]`, `status`, `stale_after`, `verified`. `verified` appears only on aliases, with the actor that actually confirmed them (`human:<api role>` via the API, `process:<id>` for automated replays). Schedule concepts carry `stale_after` = export + 7 days (producer policy). Conformance (§11) is checked by `okf.conformance_problems`.

## 5. Evaluation (`scripts/phase3/evaluate_linking.py` → `eval/phase3_linking.json`)

Fresh temporary DB per run; rules tuned on **dev** only, **test** held out. Figures include the Phase 3.1 conflict layer. Gold: labels `expected_outcome` / `true_activity_id` / `candidate_activity_ids`.

| Metric | dev | test | all |
|---|---|---|---|
| Outcome agreement (matched / review / unmatched) | 0.934 | 0.927 | 0.931 |
| Automatic matches | 119 | 142 | 261 |
| … to a **wrong** activity | **0** | **0** | **0** |
| Gold auto-apply items auto-matched correctly | 0.935 | 0.910 | 0.921 |
| Top-1 / top-3 activity (items with a true activity) | 0.897 / 0.945 | 0.921 / 0.963 | 0.910 / 0.955 |
| Unmatched recall / precision | 0.903 / 1.0 | 0.923 / 1.0 | 0.909 / 1.0 |

Layer contributions on test (outcome agreement): full **0.927**; without the conflict layer **0.918**; without stage-2 retrieval (RAG) **0.705**; without glossary/synonyms (CAG) **0.864**. MAG replay (planner confirmations of the 46 dev items not auto-matched correctly): 7 aliases learned, 27 phrases refused by the safety rules; test top-1 0.921 → 0.926, wrong automatic matches stay 0. These are results on synthetic data built for this project, not field accuracy.

Conflict-detection numbers are in §6. Some gold auto-apply items without any work verb ("Hydrants A-3") go to review, which is the safe direction.

## 6. Cross-source date conflicts (Phase 3.1)

**Why it matters.** A daily report and a tracker can both identify the activity correctly and still disagree on *when* the work happened. Picking one date silently would put an unverified actual date into the schedule. The identity of the activity is not in doubt; the fact is. So a contradiction is a **workflow condition, not a lower score**: the match is held for review even at confidence 0.95.

**Where.** `p2e/link/conflicts.py`, called at the end of every linking run and after each planner confirm/reject, i.e. after the link decisions and before an automatic match is accepted. It only reads Phase 2 events; extraction results are never modified.

**Rule** (per L5/L6 activity; takes part: auto-matched, planner-confirmed and conflict-held links; ignored: reports without a date, rejected links, two reports from the same document):

| Rule | Conflict when |
|---|---|
| `milestone_date` | two documents give different dates for the activity's actual start, or for its actual finish |
| `work_after_reported_finish` | progress/start dated after a finish reported by another document |
| `work_before_reported_start` | progress dated before a start reported by another document |
| `quantity_date_shift` | two source streams (the DPR series of one discipline group; each spreadsheet) report the same unit of work, **both cover** days *d* and *d ± N* (a DPR stream covers the days it has a report for; a sheet covers up to its "updated upto" date), and one has more work on *d* while the other has more on *d ± N*. N = `conflict_date_shift_days` = 1 in `rules.json` (CAG) |

Identical dates, missing dates and same-document records are never conflicts. A source that simply did not report a day is not a conflict (coverage check). Progress on different days is normal and only conflicts when the two sources disagree about which day.

**Review behaviour.** Every report in a finding: `decision = review`, `state = pending`, `plan_node_id` cleared (the schema allows an activity only on `matched`), first reason `cross_source_date_conflict: …`, top candidate unchanged. `event_link.conflict` (JSON) keeps the activity (`plan_node_id`, `plan_node_code`), `dates`, `findings` (`rule`, `detail`, `event_ids`) and every involved event (`event_id`, `document_id`, `document`, `source_type`, `event_type`, `event_date`, `quantity`, `unit`, `source_text`). Both sides stay inspectable through `GET …/links/{event_id}` and `GET …/events/{event_id}/evidence`; if a raw source file is missing from storage, the evidence call returns a controlled `404` (`detail.status = "source_unavailable"`) that still carries the stored evidence metadata, and the event, link and conflict record stay unchanged (Phase 3.2). When a planner rejects one side the conflict is recomputed and lifted reports return to their automatic match; a planner-confirmed link keeps its decision and keeps the conflict record (confirming the activity does not decide the date; applying actual dates is the Phase 5 apply engine). Re-running the linker is idempotent: the same database gives the same conflict records and no changes.

**Evaluation** (all 433 items): of the 11 gold `conflicting_date` items, **8 detected, all routed to review**; 3 missed because no second document contradicts them (IT-0316: its only counterpart is a row of the same spreadsheet; IT-0347: the other source reports only "started", no quantities; IT-0350: no other source mentions that day). 17 reports held: 8 gold, 6 counterparts reporting the same truth event from the other source, and 3 counted as false conflicts: IT-0082 (a DPR "erection done 09-05" contradicted by a spool dated 09-07 — a real contradiction, but a different truth event), IT-0311 and IT-0333 (a second spreadsheet row on the same day as a shifted row; day totals cannot tell which row moved). Wrong automatic links stay **0**. Test split: outcome agreement 0.927 with the layer vs 0.918 without; automatic matches 142 vs 152.

## 7. JEV (investigated 2026-10-02)

*Jev* is TypeSafe AI's "System One" model: typed questions over a structured state → structured answers with confidence, no text generation ([announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [docs](https://docs.typesafe.ai/introduction)). Verified status: early access through TypeSafe's hosted console/API; the official docs and announcement describe no self-hosted, VPC or open-weight option; benchmarks are vendor-reported (the announcement itself notes possible bias). Secondary articles give different release dates (15/18 September 2026); the official announcement is the reference.

**Decision: not implemented.** Sending project state to a hosted third-party API conflicts with the confidential/on-premise requirement, and the decision step it would replace is already deterministic, explainable and free. Re-evaluate only if an on-premise option appears, by benchmarking it on synthetic data against the gated decision layer (precision of automatic matches first).
