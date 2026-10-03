r"""Confidence calibration of the Phase 3 linker (evaluation layer; production confidence is not changed).

    .venv\Scripts\python -m eval.calibration     # -> eval/calibration_report.md, eval/calibration.json, eval/reliability_diagram.svg

What is calibrated: `event_link.confidence` = the top candidate's score from p2e.link.decide.score (a fixed weighted sum of
object / action / word-overlap / area / discipline evidence, clipped to [0, 1]; not a logit or softmax output).
Outcome: 1 when that top candidate is the event's true L5/L6 activity (labels.csv true_activity_id), else 0 (ambiguous and
unmatched events have no true activity, so their top candidate is never correct).
Predictions: a fresh database (Phase 1 import -> Phase 2 extraction -> Phase 3 link_events), so every link is an automatic
linker decision; no planner confirmations, rejections or MAG aliases exist, so nothing from the test labels can leak in.
Split discipline: the calibration method is chosen by 5-fold cross-validation INSIDE dev, fitted on all of dev, and the test
split is used once, for evaluation only. Pure Python, deterministic, no extra dependencies.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import tempfile
from bisect import bisect_left
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

N_BINS = 10
FOLDS = 5
SEED = 7


# ----------------------------------------------------------------------------- metrics

def bin_index(conf: float, n_bins: int = N_BINS) -> int:
    """Equal-width bins [0, 1/n), ..., [(n-1)/n, 1]; 1.0 falls in the last bin."""
    if not 0.0 <= conf <= 1.0:
        raise ValueError(f"confidence {conf} outside [0, 1]")
    return min(int(conf * n_bins), n_bins - 1)


def reliability(pairs: list[tuple[float, int]], n_bins: int = N_BINS) -> dict:
    """pairs = [(confidence, correct 0/1)] -> bins, ECE, MCE, Brier, accuracy, mean confidence."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "accuracy": None, "mean_confidence": None, "ece": None, "mce": None, "brier": None, "bins": []}
    groups: dict[int, list[tuple[float, int]]] = {}
    for c, y in pairs:
        groups.setdefault(bin_index(c, n_bins), []).append((c, y))
    bins, ece, mce = [], 0.0, 0.0
    for b in range(n_bins):
        rs = groups.get(b, [])
        lo, hi = b / n_bins, (b + 1) / n_bins
        if not rs:
            bins.append({"range": f"[{lo:.1f}, {hi:.1f}{']' if b == n_bins - 1 else ')'}", "n": 0})
            continue
        conf = sum(c for c, _ in rs) / len(rs)
        acc = sum(y for _, y in rs) / len(rs)
        gap = abs(acc - conf)
        ece += len(rs) / n * gap
        mce = max(mce, gap)
        bins.append({"range": f"[{lo:.1f}, {hi:.1f}{']' if b == n_bins - 1 else ')'}", "n": len(rs), "mean_confidence": round(conf, 4),
                     "accuracy": round(acc, 4), "gap": round(gap, 4)})
    return {"n": n, "accuracy": round(sum(y for _, y in pairs) / n, 4), "mean_confidence": round(sum(c for c, _ in pairs) / n, 4),
            "ece": round(ece, 4), "mce": round(mce, 4), "brier": round(sum((c - y) ** 2 for c, y in pairs) / n, 4), "bins": bins}


# ----------------------------------------------------------------------------- monotonic calibrators

class Isotonic:
    """Pool-adjacent-violators: a non-decreasing step function of the raw score, fitted to 0/1 outcomes."""

    def __init__(self, pairs: list[tuple[float, int]]):
        blocks: list[list[float]] = []                      # [x_low, x_high, sum_y, count]
        for x, y in sorted(pairs):
            if blocks and blocks[-1][1] == x:               # identical raw scores share one value
                blocks[-1][2] += y
                blocks[-1][3] += 1
            else:
                blocks.append([x, x, float(y), 1.0])
            while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] >= blocks[-1][2] / blocks[-1][3]:
                lo, _, sy, cnt = blocks.pop(-2)
                blocks[-1] = [lo, blocks[-1][1], blocks[-1][2] + sy, blocks[-1][3] + cnt]
        self.upper = [b[1] for b in blocks]
        self.value = [b[2] / b[3] for b in blocks]

    def __call__(self, x: float) -> float:
        if not self.upper:
            return x
        i = bisect_left(self.upper, x)
        return round(self.value[min(i, len(self.value) - 1)], 6)

    def table(self) -> list[dict]:
        return [{"raw_up_to": round(u, 4), "calibrated": round(v, 4)} for u, v in zip(self.upper, self.value)]


class Platt:
    """Logistic map p = 1 / (1 + exp(-(a*x + b))) fitted by gradient descent; monotonic when a > 0."""

    def __init__(self, pairs: list[tuple[float, int]], steps: int = 4000, lr: float = 0.5):
        self.a, self.b = 1.0, 0.0
        n = max(len(pairs), 1)
        for _ in range(steps):
            ga = gb = 0.0
            for x, y in pairs:
                p = 1 / (1 + math.exp(-(self.a * x + self.b)))
                ga += (p - y) * x
                gb += p - y
            self.a -= lr * ga / n
            self.b -= lr * gb / n

    def __call__(self, x: float) -> float:
        return round(1 / (1 + math.exp(-(self.a * x + self.b))), 6)


class Identity:
    def __init__(self, pairs):
        pass

    def __call__(self, x: float) -> float:
        return x


METHODS = {"identity": Identity, "platt": Platt, "isotonic": Isotonic}


def cross_validate(dev: list[tuple[float, int]], folds: int = FOLDS, seed: int = SEED) -> dict[str, float]:
    """Mean held-out-fold ECE per method, using the dev split only."""
    order = list(range(len(dev)))
    random.Random(seed).shuffle(order)
    parts = [order[i::folds] for i in range(folds)]
    out = {}
    for name, cls in METHODS.items():
        scores = []
        for part in parts:
            held = set(part)
            model = cls([dev[i] for i in order if i not in held])
            scores.append(reliability([(model(dev[i][0]), dev[i][1]) for i in part])["ece"])
        out[name] = round(sum(scores) / len(scores), 4)
    return out


# ----------------------------------------------------------------------------- predictions from the real linker

def predictions(data_dir: Path) -> list[dict]:
    """One record per labelled event with a top candidate, from a fresh pipeline database (automatic decisions only)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from p2e.db.models import EventLink, LinkCandidate, ProgressEvent, Project
    from p2e.link import service
    from p2e.link.context import refresh_context
    from scripts.phase3.evaluate_linking import build_db

    with open(data_dir / "ground_truth" / "labels.csv", newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    refresh_context()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        eng, sm = build_db(data_dir, Path(tmp))
        with sm() as session:
            project = session.scalar(select(Project))
            service.link_events(session, project, data_dir / "glossary.json")
            session.commit()
            events = {(e.document.filename, e.locator_key): e.id
                      for e in session.scalars(select(ProgressEvent).options(selectinload(ProgressEvent.document)))}
            links = {l.progress_event_id: l for l in session.scalars(
                select(EventLink).options(selectinload(EventLink.candidates).selectinload(LinkCandidate.node)))}
            for lab in labels:
                link = links[events[(lab["source_path"].split("/")[-1], lab["locator"])]]
                top = link.candidates[0].node.code if link.candidates else None
                state = ("conflict_held" if link.conflict else "auto_matched" if link.decision == "matched" and link.state == "auto"
                         else "planner_confirmed" if link.state == "confirmed" else "planner_rejected" if link.state == "rejected"
                         else link.decision)
                out.append({"split": lab["split"], "item_id": lab["item_id"], "confidence": link.confidence, "top": top,
                            "true": lab["true_activity_id"] or None, "correct": int(top is not None and top == lab["true_activity_id"]),
                            "decision": link.decision, "state": state})
        eng.dispose()
    return out


def evaluate(data_dir: Path) -> dict:
    from p2e.link.context import RULES_PATH

    preds = predictions(data_dir)
    scored = [p for p in preds if p["top"] is not None]
    excluded = Counter(p["state"] for p in scored if p["state"] in ("planner_confirmed", "planner_rejected"))
    usable = [p for p in scored if p["state"] not in ("planner_confirmed", "planner_rejected")]
    dev = [(p["confidence"], p["correct"]) for p in usable if p["split"] == "dev"]
    test = [(p["confidence"], p["correct"]) for p in usable if p["split"] == "test"]
    cv = cross_validate(dev)
    method = min(cv, key=lambda k: (cv[k], k != "isotonic"))          # lowest dev-CV ECE (ties -> isotonic)
    model = METHODS[method](dev)                                       # fitted on dev only
    cal = lambda pairs: [(model(c), y) for c, y in pairs]               # noqa: E731
    thresholds = json.loads(Path(RULES_PATH).read_text(encoding="utf-8"))["thresholds"]
    t = thresholds["auto_min_score"]
    by_state = {}
    for st in sorted({p["state"] for p in usable}):
        rs = [(p["confidence"], p["correct"]) for p in usable if p["state"] == st and p["split"] == "test"]
        by_state[st] = {"raw": {k: v for k, v in reliability(rs).items() if k != "bins"}, "calibrated": {k: v for k, v in reliability(cal(rs)).items() if k != "bins"}}
    near = {}
    for lo, hi in ((t - 0.1, t), (t, t + 0.1), (t + 0.1, 1.01)):
        rs = [p for p in usable if p["split"] == "test" and lo <= p["confidence"] < hi]
        near[f"[{lo:.2f}, {min(hi, 1.0):.2f})"] = {"n": len(rs), "accuracy": round(sum(p["correct"] for p in rs) / len(rs), 4) if rs else None,
                                                    "mean_raw": round(sum(p["confidence"] for p in rs) / len(rs), 4) if rs else None,
                                                    "mean_calibrated": round(sum(model(p["confidence"]) for p in rs) / len(rs), 4) if rs else None,
                                                    "auto_matched": sum(p["state"] == "auto_matched" for p in rs)}
    return {
        "definition": "confidence = top-candidate linker score; correct = top candidate is the true L5/L6 activity",
        "fit_split": "dev", "evaluation_split": "test (used once, never for fitting or method choice)",
        "predictions": len(preds), "with_candidate": len(scored), "without_candidate": len(preds) - len(scored),
        "excluded_planner_decisions": dict(excluded), "prediction_states": dict(Counter(p["state"] for p in usable)),
        "method_selection_dev_cv_ece": cv, "method": method,
        "calibration_map": model.table() if isinstance(model, Isotonic) else ({"a": model.a, "b": model.b} if isinstance(model, Platt) else "identity"),
        "dev": {"raw": reliability(dev), "calibrated": reliability(cal(dev))},
        "test": {"raw": reliability(test), "calibrated": reliability(cal(test))},
        "test_by_prediction_state": by_state,
        "thresholds": {"configured": thresholds, "auto_min_score_raw": t, "auto_min_score_calibrated": model(t),
                       "near_auto_threshold_test": near},
        "base_rate": {"dev_accuracy": reliability(dev)["accuracy"], "test_accuracy": reliability(test)["accuracy"],
                      "dev_unmatched_or_ambiguous": sum(p["true"] is None for p in usable if p["split"] == "dev"),
                      "test_unmatched_or_ambiguous": sum(p["true"] is None for p in usable if p["split"] == "test")},
    }


# ----------------------------------------------------------------------------- outputs

def svg_diagram(rep: dict) -> str:
    """Reliability diagram (test split): observed accuracy vs mean confidence per bin, before and after, with y = x."""
    W, H, M = 420, 420, 50
    X = lambda v: M + v * (W - 2 * M)                                   # noqa: E731
    Y = lambda v: H - M - v * (H - 2 * M)                               # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="sans-serif" font-size="11">',
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
             f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="#888" stroke-dasharray="4 3"/>',
             f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(0)}" stroke="#333"/><line x1="{X(0)}" y1="{Y(0)}" x2="{X(0)}" y2="{Y(1)}" stroke="#333"/>']
    for v in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        parts.append(f'<text x="{X(v)}" y="{Y(0) + 16}" text-anchor="middle">{v:.1f}</text><text x="{X(0) - 8}" y="{Y(v) + 4}" text-anchor="end">{v:.1f}</text>')
    for key, color in (("raw", "#d9534f"), ("calibrated", "#138a8a")):
        pts = [(b["mean_confidence"], b["accuracy"], b["n"]) for b in rep["test"][key]["bins"] if b.get("n")]
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(f"{X(c):.1f},{Y(a):.1f}" for c, a, _ in pts)}"/>')
        parts += [f'<circle cx="{X(c):.1f}" cy="{Y(a):.1f}" r="{2 + math.sqrt(n)}" fill="{color}" fill-opacity="0.6"><title>{key}: conf {c} acc {a} n {n}</title></circle>' for c, a, n in pts]
    parts += [f'<text x="{W / 2}" y="{H - 12}" text-anchor="middle">Mean predicted confidence (test split)</text>',
              f'<text x="14" y="{H / 2}" text-anchor="middle" transform="rotate(-90 14 {H / 2})">Observed accuracy</text>',
              f'<text x="{X(0.02)}" y="{Y(0.97)}" fill="#d9534f">raw (ECE {rep["test"]["raw"]["ece"]})</text>',
              f'<text x="{X(0.02)}" y="{Y(0.91)}" fill="#138a8a">calibrated (ECE {rep["test"]["calibrated"]["ece"]})</text>',
              f'<text x="{X(0.62)}" y="{Y(0.55)}" fill="#888">ideal y = x</text>', "</svg>"]
    return "\n".join(parts) + "\n"


def markdown(rep: dict) -> str:
    def summary(row):
        return f"| {row['n']} | {row['accuracy']} | {row['mean_confidence']} | {row['ece']} | {row['mce']} | {row['brier']} |"
    L = ["# Linker confidence calibration", "",
         f"Definition: {rep['definition']}. Method chosen by 5-fold cross-validation on **dev** (ECE per method: {rep['method_selection_dev_cv_ece']}) → "
         f"**{rep['method']}**, fitted on **dev**; **test** used only for the final evaluation. {rep['with_candidate']} of {rep['predictions']} events have a "
         f"candidate; planner decisions excluded: {rep['excluded_planner_decisions'] or 'none (fresh database: every link is an automatic linker decision, no MAG aliases)'}.", "",
         "## Before vs after", "", "| Split | Confidence | N | Accuracy | Mean confidence | ECE | MCE | Brier |", "|---|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        for k in ("raw", "calibrated"):
            L.append(f"| {split}{' (fit)' if split == 'dev' else ' (held out)'} | {k} " + summary(rep[split][k]))
    for split in ("dev", "test"):
        L += ["", f"## Reliability bins - {split}", ""]
        for k in ("raw", "calibrated"):
            L += [f"{k} (binned by {k} confidence):", "", "| Range | N | Mean conf | Accuracy | Gap |", "|---|---|---|---|---|"]
            L += [f"| {b['range']} | {b['n']} | {b['mean_confidence']} | {b['accuracy']} | {b['gap']} |" for b in rep[split][k]["bins"] if b["n"]]
            L.append("")
    L += ["", "## By prediction state (test)", "", "| State | N | Raw accuracy | Raw mean conf | Raw ECE | Calibrated mean conf | Calibrated ECE |", "|---|---|---|---|---|---|---|"]
    for st, v in rep["test_by_prediction_state"].items():
        L.append(f"| {st} | {v['raw']['n']} | {v['raw']['accuracy']} | {v['raw']['mean_confidence']} | {v['raw']['ece']} | {v['calibrated']['mean_confidence']} | {v['calibrated']['ece']} |")
    th = rep["thresholds"]
    L += ["", "## Thresholds", "", f"Configured (raw score): {th['configured']}. The automatic-link threshold {th['auto_min_score_raw']} maps to calibrated "
          f"{th['auto_min_score_calibrated']}. Review and unmatched are decided by rules (object/action gates, margin, novelty, unknown tags, conflicts), not by a score threshold.", "",
          "| Raw score band (test) | N | Accuracy | Mean raw | Mean calibrated | Auto-matched |", "|---|---|---|---|---|---|"]
    L += [f"| {k} | {v['n']} | {v['accuracy']} | {v['mean_raw']} | {v['mean_calibrated']} | {v['auto_matched']} |" for k, v in th["near_auto_threshold_test"].items()]
    br = rep["base_rate"]
    L += ["", "## Calibration map", "", f"`{json.dumps(rep['calibration_map'])}`", "",
          "## Notes", "",
          f"- Dev and test differ in base rate (top-candidate accuracy {br['dev_accuracy']} vs {br['test_accuracy']}; events without a true activity "
          f"{br['dev_unmatched_or_ambiguous']} vs {br['test_unmatched_or_ambiguous']}), so a map fitted on dev is conservative on test.",
          "- The calibrated confidence is an evaluation output; production responses still carry the raw linker score.",
          "", "![reliability diagram](reliability_diagram.svg)"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Calibrate and evaluate linker confidence (dev fit, test evaluation).")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    args = ap.parse_args(argv)
    rep = evaluate(args.data)
    (ROOT / "eval" / "calibration.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "eval" / "calibration_report.md").write_text(markdown(rep), encoding="utf-8", newline="\n")
    (ROOT / "eval" / "reliability_diagram.svg").write_text(svg_diagram(rep), encoding="utf-8", newline="\n")
    print(f"method {rep['method']} (dev-CV ECE {rep['method_selection_dev_cv_ece']})")
    for split in ("dev", "test"):
        r, c = rep[split]["raw"], rep[split]["calibrated"]
        print(f"{split:<5} n={r['n']:<4} acc={r['accuracy']}  ECE {r['ece']} -> {c['ece']}  MCE {r['mce']} -> {c['mce']}  "
              f"Brier {r['brier']} -> {c['brier']}  mean conf {r['mean_confidence']} -> {c['mean_confidence']}")
    print(f"auto threshold {rep['thresholds']['auto_min_score_raw']} raw -> {rep['thresholds']['auto_min_score_calibrated']} calibrated")
    print("written: eval/calibration_report.md, eval/calibration.json, eval/reliability_diagram.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
