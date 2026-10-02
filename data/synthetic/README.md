# SIH26122 Synthetic Dataset (Phase 0)

A synthetic infrastructure project, generated from a fixed seed, used by every later phase of **P2E Bridge** to build and **measure** capture, extraction and schedule linking. No real Oil India data is used. The project, tags, contractors and dates are all invented, modelled on common EPC (engineering, procurement and construction) site conventions.

[← Phase plan](../../docs/plan/PHASE_PLAN.md#phase-0-domain-model--synthetic-data) · [Data architecture](../../docs/architecture/DATA_ARCHITECTURE.md#7-synthetic-data-design-phase-0-implemented)

## 1. The scenario

| | |
|---|---|
| Project | `CGS-EXP-01`: Crude Oil Gathering Station Expansion (synthetic) |
| Areas | A1 Inlet Manifold & Separation · A2 Electrical Substation · A3 Process Pipe Rack & Pump House · A4 Tank Farm & Utilities |
| Disciplines | civil, piping, static_eq, rotating_eq, electrical, instrumentation, hse |
| Data date | 2026-08-31: actuals up to this date are already in the schedule (the PMIS state before capture starts) |
| Report window | 14 report days, 2026-09-01 → 2026-09-16 (Monday–Saturday; Sundays 6 and 13 Sep have no work or reports) |
| Seed | `26122` |

Hidden from all inputs, the generator keeps a **truth timeline**: the real actual start/finish of every activity, holds with reasons, and sub-item dates (spools, cables, tank shell rings). Every field report and spreadsheet row is written *from* that truth, with field vocabulary instead of plan vocabulary. Every item is then labelled back to the truth.

## 2. Layout

```
data/synthetic/
├── README.md                     this file (hand-written; not regenerated)
├── manifest.json                 seed, window, counts, intended mix, sha256 of every generated file
├── glossary.json                 abbreviations, Hinglish terms, event verbs, tag conventions, date formats
├── schedule/
│   ├── schedule.csv              baseline L1–L6 schedule (469 nodes, 317 activities)
│   └── schedule.xml              the same schedule as MS Project XML (MSPDI)
├── reports/
│   └── dpr_<YYYY-MM-DD>_<group>.txt   81 daily progress reports (6 discipline groups × 14 days − 3 missing)
├── spreadsheets/
│   ├── piping_spool_erection_tracker.xlsx
│   ├── electrical_cable_log.xlsx        (sheets: Cable Log, Summary)
│   └── instrument_installation_register.xlsx
└── ground_truth/
    ├── labels.csv                one row per reported item: mapping, matching expectation, hard cases
    ├── expected_extraction.json  per source document: what an extractor should output
    ├── truth_events.csv          what really happened in the window (activity-level events)
    ├── activity_truth.csv        per activity: canonical tags, true actual dates at window end, status
    ├── new_work.csv              unplanned work that must become new activities
    └── splits.json               dev/test split by report day
```

## 3. Inputs (what the system will see)

### `schedule/schedule.csv` and `schedule.xml`

WBS tree: **L1** project → **L2** area → **L3** discipline in area → **L4** object (a line, a piece of equipment, a cable group) → **L5** activities. Tanks T-401/T-402 and compressor K-301 have an L5 summary with **L6** activities. Only `node_type = activity` rows are linking targets.

| Column | Meaning |
|---|---|
| `node_id` | Activity ID (e.g. `PIP-A3-1203-ERC`) or WBS code (e.g. `CGS-EXP-01.A3.PIP.1203`) |
| `node_type` | `wbs`, `summary` or `activity` |
| `parent_id`, `level`, `wbs_code` | Tree structure (level = parent level + 1) |
| `name` | Plan wording, e.g. `Erect piping line 24"-P-1203-A1A`, `Hydrotest line 24"-P-1203-A1A (TP-017)` |
| `discipline`, `area`, `activity_type` | Activity-code fields as a P6 export would carry them |
| `planned_start`, `planned_finish`, `planned_duration_days` | ISO dates (calendar days) |
| `planned_qty`, `qty_unit` | Where progress is quantity-based: spools, m, cables, rings, cum |
| `predecessors` | `ACTIVITY_ID:FS+n` or `:SS+n` (lag in days), separated by `;` |
| `actual_start`, `actual_finish` | Filled only where they fall on or before the data date |

There is deliberately **no tags column**. Tags (line numbers, equipment and instrument numbers) live inside activity names, as in real exports. Extracting them is Phase 1's job, and `activity_truth.csv` holds the expected canonical tags.

`schedule.xml` carries the same nodes as MSPDI `Task`s. The activity ID, discipline and area are in extended attributes Text1/Text2/Text3. It includes predecessor links (FS/SS with lag), the status date and pre-window actuals.

### `reports/*.txt`: daily progress reports (DPRs)

One file per discipline group (`civil`, `piping`, `mechanical` = static + rotating, `electrical`, `instrumentation`, `hse`) per report day. There are two layouts:
- **structured**: header block, `Work done today` (numbered), `Hold / constraints`, `Plan for tomorrow`, safety, signature.
- **informal**: WhatsApp-style lines (`Today: a; b; c`, `Also: …`, `Hold: …`, `Tmrw: …`), sometimes all lower case.

Three reports were never submitted (`hse` 4 Sep and 12 Sep, `instrumentation` 9 Sep), so their events surface later with explicit dates. `Plan for tomorrow` / `Tmrw` lines name real activities but are **not events**, which makes them hard negatives for extraction.

### `spreadsheets/*.xlsx`

| File | Grain | Quirks |
|---|---|---|
| `piping_spool_erection_tracker.xlsx` | one row per spool erected (finer than the plan's line-level activity) | merged title row, header on row 4, line numbers in 4 notations, ✓/Done/Erected status, Excel dates mixed with text dates, 12 rows with a wrong date, 2 rows for non-existent line 1209 |
| `electrical_cable_log.xlsx` | one row per cable: pulling and optional termination | terse headers (`Frm`, `Termn`, `Len(m)`), cable numbers map to cable-group activities, second `Summary` sheet is not item data, 2 rows for non-existent MCC-3 |
| `instrument_installation_register.xlsx` | one row per instrument: mounting and tubing dates | title row, header on row 2, `FT-2031`/`FT 2031`/`FT2031`, `pending`/`N/A` tubing values, 1 row for non-existent FT-2035 |

## 4. Ground truth

### `labels.csv`: one row per reported item (433 rows)

An *item* is one reported fact: one event mentioned in a report line, or one event recorded in a spreadsheet row/field. A report line can hold several items. A cable-log row can yield two (pull, termination).

| Column | Meaning |
|---|---|
| `item_id` | `IT-0001` … |
| `split` | `dev` or `test` (see `splits.json`) |
| `source_type`, `doc_id`, `source_path` | Where the item is |
| `locator` | DPR: `line=<1-based line>;index=<position on the line>`. Spreadsheet: `sheet=<name>;row=<row>[;field=pull\|termination\|install\|tubing]` |
| `report_date` | DPR date (spreadsheets: the row's stated date) |
| `discipline` | Discipline of the true activity (or of the new work) |
| `source_span` | Verbatim text of the item (DPR), or `" | "`-joined key cells (spreadsheet) |
| `event_type` | `start`, `finish`, `progress`, `hold`, `resume` |
| `stated_date` | The date **as written** (relative dates resolved against the report date). Can differ from the truth (`conflicting_date`) |
| `event_key`, `truth_date` | The real event in `truth_events.csv` and its true date. Empty for coarse statements and unmatched items |
| `match_label` | `matched` · `ambiguous` · `unmatched` (see below) |
| `difficulty` | `easy` · `medium` · `hard` · `na` (unmatched) |
| `true_activity_id` | The activity the item really refers to (empty for coarse statements and unmatched items) |
| `candidate_activity_ids` | `;`-separated. Matched: just the true activity. Ambiguous: every plausible activity |
| `unmatched_type` | `new_activity` (real unplanned work) or `unknown_reference` (tag not in the plan: typo or stale drawing) |
| `new_work_key`, `suggested_parent_wbs` | For new work: key in `new_work.csv` and the WBS node a planner would file it under |
| `granularity` | `same`, `finer` (spool/cable/ring), `coarser` (area-level statement) |
| `expected_band` | Target confidence band: `high` / `medium` / `low` |
| `expected_outcome` | Target routing: `auto_apply` / `review` / `unmatched` |
| `hard_cases` | `;`-separated tags (table below) |

**Match labels and expected routing**

| match_label | Meaning | difficulty → band → outcome |
|---|---|---|
| matched | Text identifies exactly one activity | easy/medium → high → auto_apply. hard → medium → review |
| ambiguous | Text fits ≥ 2 activities (no tag, tag without work type, or area-level statement) | hard → medium → review |
| unmatched | No plan activity is correct | na → low → unmatched (planner review: create activity or correct the reference) |

`hard` matched items: `partial_description` with a unique description, `tag_only` (e.g. `TP-017 cleared`, `JB-302 fixing`), `wrong_area`, `conflicting_date`. `expected_band` and `expected_outcome` are *targets*. Phase 7 measures whether the system routes at least this conservatively.

**Hard-case tags** (counts in the current dataset)

| Tag | What it looks like | Count |
|---|---|---|
| `abbreviation` | `Excvn P102A fdn`, `Wldg/NDT L-1203`, `L1203` in a sheet | 85 |
| `terminology_variant` | `Spool erection line 1203` vs plan `Erect piping line 24"-P-1203-A1A` | 36 |
| `hinglish` | `P-102A fdn ki khudai shuru`, `V-101 foundation ki dhalai ho gaya` | 14 |
| `typo` | `Weldiing & NDT…`, `paanel` | 19 |
| `partial_description` | `crude transfer pump placement` (no tag) | 25 |
| `tag_only` | `TP-017 cleared`, `GD-301 done` | 10 |
| `type_ambiguous` | `P-101A work completed` (which step?) | 20 |
| `wrong_area` | `Shell crs 1-3 T401 (A3)` (tank is in A4) | 10 |
| `granularity_finer` | `L-1207 – 2 spools erected`, spool/cable rows, `T-401 shell ring 2 erected` | 150 |
| `granularity_coarser` | `Piping erection in Area-3 going on` | 34 |
| `relative_date` / `explicit_date` | `… yesterday`, `… on 12.09.26` | 14 / 18 |
| `late_report` | event reported on a later day than it happened | 30 |
| `multi_item_line` | several items on one line | 113 |
| `duplicate_cross_source` | same event in a DPR and a spreadsheet | 104 |
| `conflicting_date` | spreadsheet date differs from the truth by one report day | 11 |
| `new_activity` | `Temporary drainage trench near PR-3 …` | 25 |
| `unknown_reference` | `RCC T-403 fdn compl.`, line 1209, MCC-3 | 19 |

### `expected_extraction.json`

`{"documents": [...]}`, one entry per source file, with `doc_id`, `path`, `report_date`, `discipline_group`, plus:
- DPRs: `layout`, `header_date_text`, `non_event_lines` (`[{line, kind}]`: header, weather, manpower, plan_ahead, safety, nil, …).
- Spreadsheets: `sheet`, `header_row`, `column_mapping` (header → canonical field, or `null` to ignore).
- `items`: what an extractor should emit per item: `locator`, `source_span`, `activity_text` (the object phrase, verbatim), `event_type`, `date` (as stated, ISO), `time`, `quantity`, `unit`, `discipline`, `area` (only when the text states one), `tags` (canonical: `P-101A`, `LINE-1203`, `TP-017`, `MCC-2`), `delay_reason`, `delay_category`. Spreadsheet items also carry `cells` (header → value as written).

Every line of a DPR that is neither an item line nor listed in `non_event_lines` is blank. Anything extracted from a noise line is a false positive.

### `truth_events.csv`
`event_key, activity_id, event_type, event_date, event_time, quantity, unit, delay_category, n_items`. These are all activity-level events inside the window: start/finish/hold/resume, plus daily quantity progress for spool, cable and ring activities. `n_items = 0` means nobody reported it (299 events, 274 reported).

### `activity_truth.csv`
`activity_id, object_key, step_key, description, canonical_tags, true_actual_start, true_actual_finish, status_at_window_end`. This is the expected schedule state after all window data is applied, and the expected tag extraction for Phase 1.

### `new_work.csv`
14 unplanned-work definitions: `new_work_key, discipline, area, description, suggested_parent_wbs, tags, n_items`.

### `splits.json`
Items are split by the report-day index of their truth event date (or stated date if there is no event): even → `dev` (calibration, alias learning), odd → `test` (reported metrics only). A real event never lands in both splits through different sources.

## 5. Relationships

```
schedule.csv ──node_id──┬── labels.true_activity_id / candidate_activity_ids
                        ├── truth_events.activity_id ──event_key── labels.event_key
                        ├── activity_truth.activity_id
                        └── node_id (WBS) ── labels.suggested_parent_wbs, new_work.suggested_parent_wbs
labels.item_id ═══ expected_extraction.documents[].items[].item_id
labels.doc_id / source_path ── expected_extraction.documents[].doc_id / path ── reports/*.txt, spreadsheets/*.xlsx
labels.new_work_key ── new_work.new_work_key
```

## 6. Current numbers

| | |
|---|---|
| Schedule nodes / activities | 469 / **317** (civil 88, piping 76, instrumentation 48, electrical 34, static_eq 29, rotating_eq 29, hse 13) |
| Source documents | **81** DPRs + **3** spreadsheets |
| Labelled items | **433** (DPR 305, spreadsheet 128); dev 213 / test 220 |
| Match labels | matched **320 (73.9%)** · ambiguous **69 (15.9%)** · unmatched **44 (10.2%)**: 25 new activity, 19 unknown reference |
| Difficulty | easy 67 · medium 212 · hard 110 · na 44 |
| Expected outcome | auto_apply 279 · review 110 · unmatched 44 |
| Truth events | 299 (274 reported by at least one item) |

Intended mix (enforced by the validator): matched 60–85%, ambiguous 8–25%, unmatched 5–20%. At least 250 items, and at least 10 items for every hard-case tag.

## 7. Regenerate and validate

From the repository root, with the project venv (Python stdlib only, no extra packages):

```
.venv\Scripts\python scripts\phase0\generate_dataset.py      # rewrites schedule/, reports/, spreadsheets/, ground_truth/, glossary.json, manifest.json
.venv\Scripts\python scripts\phase0\validate_dataset.py      # 26 checks, including a byte-for-byte regeneration test
```

`--out DIR` writes elsewhere. `--skip-regen` skips the reproducibility re-run. The same seed and generator version always give identical bytes: spreadsheets are written by `scripts/phase0/xlsx_min.py` with fixed zip timestamps, and there are no clocks or unordered iteration in the generator. To change the data, edit the generator, bump `GENERATOR_VERSION`, regenerate and re-validate. Never hand-edit generated files: the manifest hash check fails.

## 8. How later phases use it

| Phase | Uses |
|---|---|
| 1 Plan import | Import `schedule.csv` / `schedule.xml`. Check tag extraction against `activity_truth.canonical_tags` |
| 2 Extraction | Run extractors on `reports/` and `spreadsheets/`. Score against `expected_extraction.json` (item recall/precision, field accuracy, header mapping, noise lines) |
| 3 Linking | Link extracted items. Score top-1/top-3 against `labels.true_activity_id` / `candidate_activity_ids`, routing against `expected_outcome`, NEW detection against `unmatched_type`. Calibrate thresholds on `dev`, report on `test` |
| 4 Time agent | Scripted supervisor dialogues are built in Phase 4 from `truth_events.csv` (not part of Phase 0) |
| 5 Apply & audit | After processing all items, compare schedule actuals with `activity_truth`. Duplicates (`duplicate_cross_source`) must merge, and conflicts (`conflicting_date`) must go to review |
| 6 Analytics & memory | Delay categories and durations from `truth_events` / `activity_truth` as the known answer for dashboard and Q&A checks |
| 7 Evaluation | All of the above, per `hard_cases` tag, on the `test` split |
| CAG prefix | `glossary.json` is the stable per-project vocabulary |

## 9. Known simplifications

- Calendar-day durations, one shared Monday–Saturday calendar. No resource loading.
- Hinglish is Roman-script and limited to common site words. No Devanagari or Assamese text.
- No scanned diaries or images (OCR is stretch scope). Free text stands in for transcribed diaries.
- Labels are generated, not human-annotated. A 10% human spot-check is recommended before quoting metrics externally.
