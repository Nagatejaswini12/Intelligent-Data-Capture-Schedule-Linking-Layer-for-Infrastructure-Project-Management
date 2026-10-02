r"""Phase 5 evaluation: applied actuals vs data/synthetic/ground_truth/activity_truth.csv, plus the exit gate.

    .venv\Scripts\python scripts\phase5\evaluate_apply.py      # prints, writes eval/phase5_apply.json

Fresh temporary DB: Phase 1 import -> Phase 2 extraction -> Phase 3 linking -> Phase 5 apply (as of the last report day).
Measures every applied actual start / finish against the truth (exact, off by 1 day, wrong), the truth actuals inside the
report window that were not applied, blocked activities by rule, the exit gate (apply -> audit present -> undo all ->
state restored -> undone changes not re-applied), and the CSV / MSPDI export re-imported through the Phase 1 importer.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from p2e.db.models import AuditLog, PlanNode, Project  # noqa: E402
from p2e.db.session import init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.decide import apply as engine  # noqa: E402
from p2e.link import service as linking  # noqa: E402
from p2e.plan import exporters  # noqa: E402
from p2e.plan.importers import import_schedule, read_schedule  # noqa: E402
from scripts.phase3.evaluate_linking import build_db  # noqa: E402

WINDOW = (date(2026, 9, 1), date(2026, 9, 16))


def state(session, project) -> dict:
    return {n.code: (n.actual_start, n.actual_finish, n.percent_complete)
            for n in session.scalars(select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.node_type == "activity"))}


def evaluate(data_dir: Path) -> dict:
    with open(data_dir / "ground_truth" / "activity_truth.csv", newline="", encoding="utf-8") as f:
        truth = {r["activity_id"]: r for r in csv.DictReader(f)}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        eng, sm = build_db(data_dir, tmp)
        with sm() as session:
            project = session.scalar(select(Project))
            linking.link_events(session, project, data_dir / "glossary.json")
            session.commit()
            before = state(session, project)
            r = engine.apply(session, project, WINDOW[1])
            session.commit()
            after = state(session, project)
            fields = {"actual_start": Counter(), "actual_finish": Counter()}
            wrong = []
            for e in r["applied"]:
                t = truth.get(e.node.code, {})
                for f, col in (("actual_start", "true_actual_start"), ("actual_finish", "true_actual_finish")):
                    if f in e.changes:
                        got, exp = date.fromisoformat(e.changes[f][1]), t.get(col)
                        if not exp:
                            fields[f]["no_truth_value"] += 1
                            wrong.append({"activity": e.node.code, "field": f, "applied": str(got), "truth": None})
                            continue
                        gap = abs((got - date.fromisoformat(exp)).days)
                        fields[f]["exact" if gap == 0 else "off_by_1_day" if gap == 1 else "wrong"] += 1
                        if gap > 1:
                            wrong.append({"activity": e.node.code, "field": f, "applied": str(got), "truth": exp})
            missed = {"actual_start": 0, "actual_finish": 0}
            for code, t in truth.items():
                for f, col, i in (("actual_start", "true_actual_start", 0), ("actual_finish", "true_actual_finish", 1)):
                    v = t[col] and date.fromisoformat(t[col])
                    if v and WINDOW[0] <= v <= WINDOW[1] and code in after and after[code][i] is None:
                        missed[f] += 1
            entries = session.scalars(select(AuditLog).where(AuditLog.action == "apply")).all()
            audit_ok = len(entries) == len(r["applied"]) and all(e.evidence_event_ids and e.actor == engine.AUTO_ACTOR for e in entries)
            export_ok = round_trip(session, project, tmp, after)
            for e in sorted(entries, key=lambda e: -e.id):          # exit gate: undo everything, newest first
                engine.undo(session, project, e.id, "process:evaluation")
            session.commit()
            restored = state(session, project) == before
            reapply = engine.apply(session, project, WINDOW[1])
            session.rollback()
            report = {
                "as_of": str(WINDOW[1]),
                "applied_activities": len(r["applied"]),
                "applied_fields": dict(Counter(f for e in r["applied"] for f in e.changes)),
                "blocked_activities": len(r["blocked"]),
                "blocked_by_rule": dict(Counter(re.split(r"[:(]| \d", b)[0].strip() for p in r["blocked"] for b in p.blockers)),
                "unchanged": r["unchanged"],
                "applied_vs_truth": {f: dict(c) for f, c in fields.items()},
                "applied_not_matching_truth": wrong,
                "truth_actuals_in_window_not_applied": missed,
                "warnings": dict(Counter(w.split(" (")[0].split(" ")[0] for e in entries for w in e.warnings)),
                "exit_gate": {"audit_entries": len(entries), "audit_complete": audit_ok, "undo_restored_state": restored,
                              "undone_changes_reapplied": len(reapply["applied"])},
                "export_round_trip": export_ok,
            }
        eng.dispose()
    return report


def round_trip(session, project, tmp: Path, expected: dict) -> dict:
    data = exporters.rows(session, project)
    (tmp / "x.csv").write_text(exporters.to_csv(data), encoding="utf-8", newline="")
    (tmp / "x.xml").write_bytes(exporters.to_mspdi(project, data, WINDOW[1]))
    out = {}
    for name in ("x.csv", "x.xml"):
        eng = make_engine(f"sqlite:///{(tmp / (name + '.db')).as_posix()}")
        init_db(eng)
        with make_sessionmaker(eng).begin() as s2:
            import_schedule(s2, read_schedule(tmp / name), WINDOW[1])
        with make_sessionmaker(eng)() as s2:
            got = {c: (a, b) for c, (a, b, _) in state(s2, s2.scalar(select(Project))).items()}
        out[name.split(".")[1]] = got == {c: (a, b) for c, (a, b, _) in expected.items()}
        eng.dispose()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate Phase 5 apply against the ground truth.")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "phase5_apply.json")
    args = ap.parse_args(argv)
    rep = evaluate(args.data)
    args.out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8", newline="\n")
    for k, v in rep.items():
        if k != "applied_not_matching_truth":
            print(f"{k:<38} {v}")
    print(f"{'applied_not_matching_truth':<38} {len(rep['applied_not_matching_truth'])}")
    print(f"\nwritten: {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
