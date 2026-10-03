"""Confidence calibration (eval/calibration.py): metrics, bins, monotonic dev-only fitting; the linker itself is unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import calibration as cal
from p2e.link import decide as linker

ROOT = Path(__file__).resolve().parents[1]


def test_bin_assignment_and_boundaries():
    assert [cal.bin_index(c) for c in (0.0, 0.05, 0.1, 0.55, 0.999, 1.0)] == [0, 0, 1, 5, 9, 9]
    for bad in (-0.01, 1.01):
        with pytest.raises(ValueError):
            cal.bin_index(bad)


def test_ece_hand_computed():
    # bin 0.2: conf 0.2, acc 0.5 (gap 0.3, n=2); bin 0.9: conf 0.9, acc 1.0 (gap 0.1, n=2) -> ECE 0.2, MCE 0.3
    r = cal.reliability([(0.2, 0), (0.2, 1), (0.9, 1), (0.9, 1)])
    assert (r["n"], r["ece"], r["mce"], r["accuracy"], r["mean_confidence"]) == (4, 0.2, 0.3, 0.75, 0.55)
    assert r["brier"] == round((0.04 + 0.64 + 0.01 + 0.01) / 4, 4)
    assert [b["n"] for b in r["bins"]] == [0, 0, 2, 0, 0, 0, 0, 0, 0, 2]


def test_perfect_over_and_underconfident():
    perfect = [(0.0, 0)] * 5 + [(1.0, 1)] * 5
    assert cal.reliability(perfect)["ece"] == 0 and cal.reliability(perfect)["brier"] == 0
    over = cal.reliability([(0.9, 1), (0.9, 0)])                  # 90% said, 50% right
    under = cal.reliability([(0.3, 1), (0.3, 1)])                 # 30% said, 100% right
    assert over["ece"] == 0.4 and over["mean_confidence"] > over["accuracy"]
    assert under["ece"] == 0.7 and under["mean_confidence"] < under["accuracy"]


def test_empty_input():
    r = cal.reliability([])
    assert r["n"] == 0 and r["ece"] is None and r["bins"] == []
    assert cal.Isotonic([])(0.42) == 0.42


def test_isotonic_is_monotonic_and_deterministic():
    pairs = [(0.1, 0), (0.2, 1), (0.3, 0), (0.4, 0), (0.5, 1), (0.6, 1), (0.7, 0), (0.8, 1), (0.9, 1)]
    a, b = cal.Isotonic(pairs), cal.Isotonic(list(reversed(pairs)))
    grid = [i / 100 for i in range(101)]
    assert [a(x) for x in grid] == [b(x) for x in grid]                            # order of input does not matter
    assert all(a(x) <= a(y) for x, y in zip(grid, grid[1:]))                       # never decreasing
    assert all(0 <= a(x) <= 1 for x in grid)
    assert cal.cross_validate(pairs * 3) == cal.cross_validate(pairs * 3)          # seeded folds


def test_fit_never_sees_test_labels(monkeypatch):
    seen = []
    real = cal.Isotonic.__init__
    monkeypatch.setattr(cal.Isotonic, "__init__", lambda self, pairs: (seen.append(list(pairs)), real(self, pairs))[1])
    preds = [{"split": s, "item_id": f"{s}{i}", "confidence": c, "top": "A", "true": "A" if y else None, "correct": y,
              "decision": "review", "state": "review"} for s, rows in
             (("dev", [(0.2, 0), (0.4, 0), (0.6, 1), (0.8, 1)] * 5), ("test", [(0.11, 1), (0.33, 0), (0.77, 1)] * 5)) for i, (c, y) in enumerate(rows)]
    monkeypatch.setattr(cal, "predictions", lambda data_dir: preds)
    rep = cal.evaluate(ROOT / "data" / "synthetic")
    test_conf = {0.11, 0.33, 0.77}
    assert seen and all(not (test_conf & {c for c, _ in fit}) for fit in seen)      # CV folds and final fit: dev only
    assert rep["fit_split"] == "dev" and rep["test"]["raw"]["n"] == 15


def test_planner_decisions_excluded(monkeypatch):
    base = {"top": "A", "true": "A", "correct": 1, "decision": "matched"}
    preds = ([{"split": "dev", "item_id": f"d{i}", "confidence": 0.8, "state": "auto_matched", **base} for i in range(10)]
             + [{"split": "test", "item_id": f"t{i}", "confidence": 0.8, "state": "auto_matched", **base} for i in range(4)]
             + [{"split": "test", "item_id": "x", "confidence": 0.9, "state": "planner_confirmed", **base}])
    monkeypatch.setattr(cal, "predictions", lambda data_dir: preds)
    rep = cal.evaluate(ROOT / "data" / "synthetic")
    assert rep["excluded_planner_decisions"] == {"planner_confirmed": 1} and rep["test"]["raw"]["n"] == 4


def test_linker_confidence_logic_unchanged():
    assert linker.LINKER_VERSION == "1.1.0"
    assert linker.WEIGHTS == {"object": 0.40, "action": 0.35, "lexical": 0.15, "area_match": 0.05, "discipline_match": 0.05,
                              "area_conflict": -0.25, "discipline_conflict": -0.15}
    rules = json.loads((ROOT / "p2e" / "link" / "rules.json").read_text(encoding="utf-8"))["thresholds"]
    assert rules["auto_min_score"] == 0.7 and rules["auto_min_margin"] == 0.15
    assert "calibrat" not in Path(linker.__file__).read_text(encoding="utf-8")       # production scoring has no calibration step
