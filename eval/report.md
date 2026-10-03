# P2E Bridge — evaluation report

Generated 2026-10-03T20:41:15 by `python -m eval.run --split test` on the synthetic project (rules tuned on **dev**; headline numbers on **test**). Deterministic parser/linker metrics on synthetic data, not field accuracy.

## Targets

| Metric | Target | Value | Met |
|---|---|---|---|
| Dataset checks | all pass | 26/26 | yes |
| Extraction item recall | >= 0.92 | 1.0 | yes |
| Extraction item precision | >= 0.90 | 1.0 | yes |
| Extraction field accuracy (type, date, qty; excl. ground-truth gaps) | >= 0.90 each | 1.0 | yes |
| Linking top-1 (items with a true activity) | >= 0.85 | 0.9211 | yes |
| Linking top-3 recall | >= 0.95 | 0.9632 | yes |
| Auto-apply precision | >= 0.95 | 1.0 | yes |
| Auto-apply coverage (all events) | report (aim >= 0.60) | 0.6455 | — |
| NEW detection recall (all splits) | >= 0.90 | 1.0 | yes |
| Unmatched never auto-applied to a wrong node | 100% | True | yes |
| Calibration ECE (top-candidate score) | <= 0.05 | 0.144 | **no** |
| Calibrated confidence ECE (isotonic fitted on dev, evaluated on test) | <= 0.05 | 0.172 -> 0.0575 | **no** |
| LLM call ratio | <= 0.30 | 0.0 | yes |
| Alias learning curve (test top-1) | uplift | 0.9211 -> 0.9263 | yes |
| Time Agent task success (20 dialogues) | >= 0.90 | 1.0 | yes |
| Time Agent mean turns to log | <= 3 | 1.17 | yes |
| Time Agent wrong-activity logs | 0 | 0 | yes |
| Memory Q&A benchmark (correct + cited) | >= 8/10 | 10/10 | yes |
| Applied actuals with audit + source evidence | 100% | True | yes |
| Applied dates equal ground truth | report | 0 mismatches | — |
| Report -> schedule actual (single DPR) | <= 10 s | 0.74 | yes |

## Extraction (Phase 2)

| Split | Expected | Predicted | P | R | F1 |
|---|---|---|---|---|---|
| dev | 213 | 213 | 1.0 | 1.0 | 1.0 |
| test | 220 | 220 | 1.0 | 1.0 | 1.0 |
| all | 433 | 433 | 1.0 | 1.0 | 1.0 |

Ground-truth gaps (independently confirmed, not extractor errors): 36.

## Linking (Phase 3 / 3.1)

| Split | Matched | Review | Unmatched | Outcome agreement | Wrong auto | Top-1 | Top-3 | Unmatched recall |
|---|---|---|---|---|---|---|---|---|
| dev | 119 | 63 | 31 | 0.9484 | 0 | 0.897 | 0.9455 | 1.0 |
| test | 142 | 65 | 13 | 0.9318 | 0 | 0.9211 | 0.9632 | 1.0 |
| all | 261 | 128 | 44 | 0.94 | 0 | 0.9099 | 0.9549 | 1.0 |

### Ablations (test)

| Variant | Outcome agreement | Auto | Wrong auto | Top-3 |
|---|---|---|---|---|
| full | 0.9318 | 142 | 0 | 0.9632 |
| without_conflict_layer | 0.9227 | 152 | 0 | 0.9632 |
| without_stage2_retrieval_RAG | 0.7091 | 133 | 0 | 0.7947 |
| without_glossary_and_synonyms_CAG | 0.8636 | 140 | 0 | 0.9474 |
| without_tags | 0.3182 | 21 | 1 | 0.3737 |

Without aliases (MAG) = the full system before any confirmation; alias learning curve after replaying 46 dev confirmations: 7 aliases, test top-1 0.9211 → 0.9263, wrong auto 0. Without embeddings / LLM adjudication: not applicable (no embeddings; LLM disabled).

### Threshold calibration

T_auto = lowest auto_min_score with dev auto-link precision >= 0.95 (other gates unchanged). Calibrated T_auto = 0.3; configured = 0.7. Thresholds giving identical dev decisions to the configured one: [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7] (the other gates bind, not the score). Test at calibrated: {'auto': 152, 'coverage': 0.6909, 'precision': 1.0, 'wrong': 0}; at configured: {'auto': 152, 'coverage': 0.6909, 'precision': 1.0, 'wrong': 0}.

| Threshold | Dev auto | Dev coverage | Dev precision | Test auto | Test coverage | Test precision |
|---|---|---|---|---|---|---|
| 0.3 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.4 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.5 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.55 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.6 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.65 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.7 | 126 | 0.5915 | 1.0 | 152 | 0.6909 | 1.0 |
| 0.75 | 125 | 0.5869 | 1.0 | 151 | 0.6864 | 1.0 |
| 0.8 | 115 | 0.5399 | 1.0 | 141 | 0.6409 | 1.0 |
| 0.85 | 89 | 0.4178 | 1.0 | 104 | 0.4727 | 1.0 |
| 0.9 | 51 | 0.2394 | 1.0 | 54 | 0.2455 | 1.0 |
| 0.95 | 45 | 0.2113 | 1.0 | 49 | 0.2227 | 1.0 |

### Reliability (test) — ECE 0.144

| Bucket | Items | Mean confidence | Top-1 accuracy |
|---|---|---|---|
| [0.0, 0.2) | 6 | 0.133 | 0.0 |
| [0.2, 0.4) | 14 | 0.261 | 0.643 |
| [0.4, 0.6) | 35 | 0.488 | 0.257 |
| [0.6, 0.8) | 24 | 0.674 | 0.667 |
| [0.8, 1.0) | 141 | 0.877 | 1.0 |

confidence = linker score of the top candidate (a fixed weighting, not a fitted probability). Calibrated (isotonic map fitted on dev, 10 bins, items with a candidate): test ECE 0.172 -> 0.0575, Brier 0.0963 -> 0.068; details in eval/calibration_report.md (evaluation only; API returns the raw score).

### Cross-source conflicts

Gold 11, detected 8 (all routed to review), missed ['IT-0316', 'IT-0347', 'IT-0350'], same-fact counterparts 6, false conflicts ['IT-0082', 'IT-0311', 'IT-0333'].

### Per hard case (all items)

| Hard case | Items | Outcome agreement | Wrong auto |
|---|---|---|---|
| (none) | 19 | 0.9474 | 0 |
| abbreviation | 85 | 0.8471 | 0 |
| conflicting_date | 11 | 0.7273 | 0 |
| duplicate_cross_source | 104 | 0.9327 | 0 |
| explicit_date | 18 | 0.8889 | 0 |
| granularity_coarser | 34 | 1.0 | 0 |
| granularity_finer | 150 | 0.9333 | 0 |
| hinglish | 14 | 0.9286 | 0 |
| late_report | 30 | 0.9 | 0 |
| multi_item_line | 113 | 0.9381 | 0 |
| new_activity | 25 | 1.0 | 0 |
| partial_description | 25 | 1.0 | 0 |
| relative_date | 14 | 0.9286 | 0 |
| tag_only | 10 | 1.0 | 0 |
| terminology_variant | 36 | 0.8611 | 0 |
| type_ambiguous | 20 | 0.95 | 0 |
| typo | 19 | 1.0 | 0 |
| unknown_reference | 19 | 1.0 | 0 |
| wrong_area | 10 | 1.0 | 0 |

## Schedule application (Phase 5)

Applied activities 63, fields {'actual_start': 48, 'actual_finish': 31, 'percent_complete': 45}, blocked 23 {'finish reported without any known actual start': 13, 'actual start not reported': 11}. Applied vs truth {'actual_start': {'exact': 48}, 'actual_finish': {'exact': 31}}. Exit gate {'audit_entries': 63, 'audit_complete': True, 'undo_restored_state': True, 'undone_changes_reapplied': 0}. Export round trip {'csv': True, 'xml': True}.

## Time Agent (Phase 4)

20/20 scripted dialogues as expected, mean turns to log 1.17, wrong-activity logs 0.

| Dialogue | Turns | Expected | Got | Pass |
|---|---|---|---|---|
| D01 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-PT1102-TUB'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-PT1102-TUB'} | yes |
| D02 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-LT1103-LCK'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-LT1103-LCK'} | yes |
| D03 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-JB101-INS'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-JB101-INS'} | yes |
| D04 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A3-P101A-GRT'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A3-P101A-GRT'} | yes |
| D05 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A1-K301-ALN'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A1-K301-ALN'} | yes |
| D06 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ELE-A2-TR1-PLC'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ELE-A2-TR1-PLC'} | yes |
| D07 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'HSE-A1-GD101-INS'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'HSE-A1-GD101-INS'} | yes |
| D08 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'PIP-A1-1101-WLD'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'PIP-A1-1101-WLD'} | yes |
| D09 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'SEQ-A1-V102-GRT'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'SEQ-A1-V102-GRT'} | yes |
| D10 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'CIV-A1-V101-BKF'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'CIV-A1-V101-BKF'} | yes |
| D11 | 1 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'PIP-A1-1102-ERC'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'PIP-A1-1102-ERC'} | yes |
| D12 | 1 | {'status': 'rejected'} | {'status': 'rejected', 'decision': None, 'plan_node_code': None} | yes |
| D13 | 2 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-PT1104-LCK'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'INS-A1-PT1104-LCK'} | yes |
| D14 | 2 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ELE-A2-CHTTR2-TRM'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ELE-A2-CHTTR2-TRM'} | yes |
| D15 | 2 | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A3-P101A-SOL'} | {'status': 'recorded', 'decision': 'matched', 'plan_node_code': 'ROT-A3-P101A-SOL'} | yes |
| D16 | 1 | {'status': 'recorded', 'decision': 'review'} | {'status': 'recorded', 'decision': 'review', 'plan_node_code': None} | yes |
| D17 | 1 | {'status': 'recorded', 'decision': 'review'} | {'status': 'recorded', 'decision': 'review', 'plan_node_code': None} | yes |
| D18 | 1 | {'status': 'recorded', 'decision': 'unmatched'} | {'status': 'recorded', 'decision': 'unmatched', 'plan_node_code': None} | yes |
| D19 | 1 | {'status': 'recorded', 'decision': 'unmatched'} | {'status': 'recorded', 'decision': 'unmatched', 'plan_node_code': None} | yes |
| D20 | 1 | {'status': 'checklist'} | {'status': 'checklist', 'decision': None, 'plan_node_code': None} | yes |

## Silent activity watch

As of 2026-09-16 (3-day window): 99 silent; 13 truly worked but unreported; 86 idle/slipping; deterministic True.

## Memory Q&A (Phase 6)

10/10 benchmark questions correct with citations.

| Question | Intent | Citations | Pass |
|---|---|---|---|
| How many civil activities were completed by 2026-08-31? | count | 68 | yes |
| Which piping activities started late by 2026-08-31? | late | 9 | yes |
| Which civil activities in Area 3 finished late by 2026-08-31? | late | 26 | yes |
| How long did backfilling take by 2026-08-31? | duration | 8 | yes |
| How many instrumentation activities were in progress on 2026-08-31? | count | 3 | yes |
| What was the status of P-101A excavation on 2026-08-31? | status | 1 | yes |
| What delayed electrical cable pulling in Area 3? | delays | 1 | yes |
| What delayed piping work? | delays | 3 | yes |
| Why was HT-SWBD-1 installation held up? | delays | 1 | yes |
| When did each discipline last report by 2026-09-10? | freshness | 6 | yes |

## Latency and LLM use

Extraction 1.6 ms/document; linking 4.35 ms/event; single DPR upload → applied actual 0.74 s. LLM call ratio 0.0 (disabled (no on-premise model configured)).
