r"""Phase 6 exit gate: benchmark questions answered from the recorded history, with citations, checked against expected
answers computed INDEPENDENTLY from the Phase 0 ground truth files (schedule.csv, activity_truth.csv, truth_events.csv,
labels.csv, report file names) with plain csv code, never from the system's database.

    .venv\Scripts\python scripts\phase6\evaluate_qa.py       # prints, writes eval/phase6_qa.json

History = fresh temporary DB: Phase 1 import -> Phase 2 extraction -> Phase 3 linking -> Phase 5 apply (as of 2026-09-16).
A question passes when its structured values equal the expected values AND it cites the records behind them.
Expected values use only facts the history can know: actuals up to the schedule data date (2026-08-31, imported), and
field-reported holds (truth events that have at least one labelled report).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from p2e.analytics import qa  # noqa: E402
from p2e.db.models import Project  # noqa: E402
from p2e.decide import apply as engine  # noqa: E402
from p2e.link import service as linking  # noqa: E402
from p2e.link.context import get_context  # noqa: E402
from scripts.phase3.evaluate_linking import build_db  # noqa: E402

AS_OF = date(2026, 9, 16)
DATA_DATE = date(2026, 8, 31)


def load(data_dir: Path):
    read = lambda p: list(csv.DictReader(open(data_dir / p, newline="", encoding="utf-8")))   # noqa: E731
    sched = {r["node_id"]: r for r in read("schedule/schedule.csv") if r["node_type"] == "activity"}
    truth = {r["activity_id"]: r for r in read("ground_truth/activity_truth.csv")}
    reported = {r["event_key"] for r in read("ground_truth/labels.csv") if r["event_key"]}
    holds = [r for r in read("ground_truth/truth_events.csv") if r["event_type"] == "hold" and r["event_key"] in reported]
    return sched, truth, holds


def d(v: str) -> date | None:
    return date.fromisoformat(v) if v else None


def status_at(t: dict, day: date) -> str:
    if d(t["true_actual_finish"]) and d(t["true_actual_finish"]) <= day:
        return "completed"
    if d(t["true_actual_start"]) and d(t["true_actual_start"]) <= day:
        return "in_progress"
    return "not_started"


def benchmark(data_dir: Path) -> list[dict]:
    sched, truth, holds = load(data_dir)
    acts = lambda pred: [c for c, s in sched.items() if pred(s)]                              # noqa: E731
    civil = acts(lambda s: s["discipline"] == "civil")
    piping = acts(lambda s: s["discipline"] == "piping")
    backfill = acts(lambda s: s["activity_type"] == "Backfilling")
    instr = acts(lambda s: s["discipline"] == "instrumentation")
    civ_a3 = acts(lambda s: s["discipline"] == "civil" and s["area"] == "A3")
    done = lambda c: truth[c]["true_actual_finish"] and d(truth[c]["true_actual_finish"]) <= DATA_DATE   # noqa: E731
    late_start = lambda c: d(truth[c]["true_actual_start"]) and d(truth[c]["true_actual_start"]) <= DATA_DATE \
        and d(truth[c]["true_actual_start"]) > d(sched[c]["planned_start"])                              # noqa: E731
    late_finish = lambda c: done(c) and d(truth[c]["true_actual_finish"]) > d(sched[c]["planned_finish"])  # noqa: E731
    durs = [(d(truth[c]["true_actual_finish"]) - d(truth[c]["true_actual_start"])).days + 1 for c in backfill if done(c)]
    plans = [int(sched[c]["planned_duration_days"]) for c in backfill if done(c)]
    hold_cats = lambda pred: dict(sorted(Counter(h["delay_category"] for h in holds if pred(sched[h["activity_id"]])).items()))  # noqa: E731
    last = defaultdict(date.min.__class__)
    for f in (data_dir / "reports").glob("dpr_*.txt"):
        _, day, group = f.stem.split("_")
        if date.fromisoformat(day) <= date(2026, 9, 10):
            last[group] = max(last.get(group, date.min), date.fromisoformat(day))
    return [
        {"q": "How many civil activities were completed by 2026-08-31?", "check": "count",
         "expected": {"count": sum(1 for c in civil if done(c))}, "codes": sorted(c for c in civil if done(c))},
        {"q": "Which piping activities started late by 2026-08-31?", "check": "started_late",
         "expected": {"started_late": sorted(c for c in piping if late_start(c))}},
        {"q": "Which civil activities in Area 3 finished late by 2026-08-31?", "check": "finished_late",
         "expected": {"finished_late": sorted(c for c in civ_a3 if late_finish(c))}},
        {"q": "How long did backfilling take by 2026-08-31?", "check": "duration",
         "expected": {"n": len(durs), "mean_actual_days": round(sum(durs) / len(durs), 2), "mean_planned_days": round(sum(plans) / len(plans), 2)},
         "codes": sorted(c for c in backfill if done(c))},
        {"q": "How many instrumentation activities were in progress on 2026-08-31?", "check": "count",
         "expected": {"count": sum(1 for c in instr if status_at(truth[c], DATA_DATE) == "in_progress")},
         "codes": sorted(c for c in instr if status_at(truth[c], DATA_DATE) == "in_progress")},
        {"q": "What was the status of P-101A excavation on 2026-08-31?", "check": "status",
         "expected": {c: status_at(truth[c], DATA_DATE) for c in acts(lambda s: "P-101A" in s["name"] and s["activity_type"] == "Excavation")}},
        {"q": "What delayed electrical cable pulling in Area 3?", "check": "delays",
         "expected": {"by_category": hold_cats(lambda s: s["discipline"] == "electrical" and s["area"] == "A3" and s["activity_type"] == "Cable pulling")}},
        {"q": "What delayed piping work?", "check": "delays", "expected": {"by_category": hold_cats(lambda s: s["discipline"] == "piping")}},
        {"q": "Why was HT-SWBD-1 installation held up?", "check": "delays",
         "expected": {"by_category": hold_cats(lambda s: "HT-SWBD-1" in s["name"])}},
        {"q": "When did each discipline last report by 2026-09-10?", "check": "freshness",
         "expected": {"last_report": {g: v.isoformat() for g, v in sorted(last.items())}}},
    ]


def judge(item: dict, a: dict) -> tuple[bool, str]:
    v, exp, cites = a["values"], item["expected"], a["citations"]
    if not cites:
        return False, "no citations"
    if item["check"] in ("count", "duration"):
        got = {k: v.get(k) for k in exp}
        if got != exp:
            return False, f"got {got}"
        cited = sorted(c["id"] for c in cites)
        return (cited == item["codes"], "ok" if cited == item["codes"] else "citations differ from the counted activities")
    if item["check"] in ("started_late", "finished_late"):
        got = v.get(item["check"])
        return (got == exp[item["check"]] and set(got) <= {c["id"] for c in cites}, "ok" if got == exp[item["check"]] else f"got {got}")
    if item["check"] == "status":
        return (v == exp, "ok" if v == exp else f"got {v}")
    if item["check"] == "delays":
        ok = v.get("by_category") == exp["by_category"] and len(cites) == sum(exp["by_category"].values())
        return ok, "ok" if ok else f"got {v.get('by_category')} with {len(cites)} citations"
    got = {g: str(x) for g, x in v.get("last_report", {}).items()}
    return got == exp["last_report"], "ok" if got == exp["last_report"] else f"got {got}"


def evaluate(data_dir: Path) -> dict:
    items = benchmark(data_dir)
    with tempfile.TemporaryDirectory() as tmp:
        eng, sm = build_db(data_dir, Path(tmp))
        with sm() as session:
            project = session.scalar(select(Project))
            linking.link_events(session, project, data_dir / "glossary.json")
            engine.apply(session, project, AS_OF)
            session.commit()
            ctx = get_context(session, project, data_dir / "glossary.json")
            results = []
            for it in items:
                a = qa.answer(session, project, it["q"], ctx, AS_OF)
                ok, why = judge(it, a)
                results.append({"question": it["q"], "intent": a["intent"], "passed": ok, "detail": why, "answer": a["answer"],
                                "citations": len(a["citations"]), "expected": it["expected"]})
        eng.dispose()
    return {"passed": sum(r["passed"] for r in results), "total": len(results), "results": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 6 Q&A benchmark against the ground truth.")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "phase6_qa.json")
    args = ap.parse_args(argv)
    rep = evaluate(args.data)
    args.out.write_text(json.dumps(rep, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    for r in rep["results"]:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  [{r['intent']:<9}] {r['question']}  ({r['citations']} citations)"
              + ("" if r["passed"] else f"\n      {r['detail']}"))
    print(f"\n{rep['passed']}/{rep['total']} benchmark questions answered correctly with citations")
    print(f"written: {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
