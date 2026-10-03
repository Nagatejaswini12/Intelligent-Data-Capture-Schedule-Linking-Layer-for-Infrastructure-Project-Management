# Linker confidence calibration (ECE)

**Why.** The linker reports a confidence for every decision. Planners read it as "how likely is this right". If 0.8 is right only 50 % of the time, the number misleads review priorities and threshold choices. Calibration measures — and, for reporting, corrects — that gap.

**What is measured.** `event_link.confidence` is the top candidate's score from `p2e/link/decide.py`: a fixed weighted sum of object, action, word-overlap, area and discipline evidence, clipped to [0, 1]. It is not a logit or a softmax output, so temperature scaling does not apply. An event counts as *correct* when that top candidate is its true L5/L6 activity in `labels.csv` (events with no true activity — ambiguous or new work — are never correct).

**ECE.** Expected Calibration Error: sort predictions into 10 equal-width confidence bins; in each bin take |observed accuracy − mean confidence|; average the gaps weighted by bin size. 0 = confidence equals accuracy. The report also gives MCE (largest bin gap), Brier score (mean squared error of confidence vs outcome), accuracy and mean confidence.

**How it is evaluated** (`.venv\Scripts\python -m eval.calibration`, also part of `python -m eval.run`):

1. Fresh database: Phase 1 import → Phase 2 extraction → Phase 3 linking. Every link is an automatic linker decision; there are no planner confirmations, rejections or learned MAG aliases, so planner outcomes cannot inflate the result or leak test labels. (Planner-confirmed / rejected links, if present, are excluded.)
2. **Dev split → fitting.** The method is chosen by 5-fold cross-validation inside dev (identity, Platt logistic, isotonic); the winner is fitted on all of dev.
3. **Test split → final evaluation only**, used once; never for fitting or method choice. No other split was created.
4. Method: isotonic regression (pool-adjacent-violators) — a monotonic step map, so a higher raw score never gets a lower calibrated confidence. Pure Python, deterministic, no new dependencies.

**Results** (synthetic data; numbers from `eval/calibration_report.md`):

| Split | N | Accuracy | ECE raw → calibrated | Brier raw → calibrated | Mean confidence raw → calibrated |
|---|---|---|---|---|---|
| dev (fit) | 213 | 0.695 | 0.157 → 0.000 (in-sample) | 0.112 → 0.078 | 0.713 → 0.695 |
| test (held out) | 220 | 0.795 | 0.172 → **0.058** | 0.096 → 0.068 | 0.734 → 0.738 |

Dev cross-validated ECE: identity 0.173, Platt 0.102, isotonic 0.053. The dev in-sample 0.000 is expected for isotonic and is not evidence; the test figure is the honest one. Test ECE 0.058 is just above the ≤ 0.05 target.

**Raw vs calibrated.** Raw confidence is unchanged everywhere (database, API, UI, thresholds). The calibrated confidence is an evaluation output (`eval/calibration.json` → `calibration_map`); no API field was added, so existing consumers are unaffected.

**Thresholds** (`p2e/link/rules.json`, not changed): `auto_min_score` 0.70 (calibrated ≈ 0.93), `auto_min_margin` 0.15, `alias_auto_min_confirmations` 2. Review and unmatched come from rules (object/action gates, margin, novelty, unknown tag, conflicts), not from a score threshold. On test, every auto-matched link (142) and every conflict-held link (10) is correct; raw scores in [0.60, 0.70) are right only 33 % of the time (calibrated 0.32). Recommendation only: keep 0.70; the raw score overstates certainty for review items (raw 0.43 vs calibrated 0.24) and understates it for auto links (raw 0.87 vs accuracy 1.00), so show the calibrated value when presenting the score as a probability.

**Limitations.** Small synthetic sample (433 events with a candidate); dev and test differ in base rate (accuracy 0.695 vs 0.795), which limits transfer; the map must be refitted on real labelled field data before any production use; isotonic steps are coarse where data is sparse.
