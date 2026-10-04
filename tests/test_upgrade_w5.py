"""Upgrade W5: shadow mode (pilot without writing actuals) and the blind-set evaluation script."""
from __future__ import annotations

import csv
import importlib.util
import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from p2e.analytics import efficiency as eff
from p2e.db.models import AuditLog, PlanNode
from p2e.decide import apply as engine
from tests.test_phase3 import KEYS, PLAN, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase5 import api, linked  # noqa: F401

AS_OF = date(2026, 9, 16)
ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "data" / "synthetic"


def actuals(session):
    return session.execute(select(PlanNode.code, PlanNode.actual_start, PlanNode.actual_finish, PlanNode.percent_complete)
                           .order_by(PlanNode.code)).all()


def test_shadow_mode_proposes_but_writes_nothing(linked):
    session, project, _ = linked
    project.shadow_mode = True
    before, audits = actuals(session), session.scalar(select(func.count()).select_from(AuditLog))
    r = engine.apply(session, project, AS_OF)
    assert r["shadow"] and r["dry_run"] and r["applied"]                     # it would update activities ...
    assert actuals(session) == before                                           # ... but wrote nothing
    assert session.scalar(select(func.count()).select_from(AuditLog)) == audits
    shadow = eff.efficiency(session, project, AS_OF)["shadow"]
    assert shadow["enabled"] and shadow["would_update"] == len(r["applied"])
    project.shadow_mode = False
    live = engine.apply(session, project, AS_OF)
    assert not live["shadow"] and len(live["applied"]) == len(r["applied"]) and actuals(session) != before


def test_planner_actions_still_write_in_shadow_mode(linked):
    session, project, _ = linked
    project.shadow_mode = True
    r = engine.apply(session, project, AS_OF, actor="human:planner")
    assert not r["shadow"] and not r["dry_run"]


def test_shadow_mode_api(api):
    c, base, _, _ = api
    assert c.put(f"{base}/shadow-mode", json={"enabled": True}, headers=SUP).status_code == 403   # planner decision
    assert c.put(f"{base}/shadow-mode", json={"enabled": True}, headers=PLAN).json()["shadow_mode"] is True
    assert c.get(base, headers=SUP).json()["shadow_mode"] is True
    out = c.post(f"{base}/apply", json={"as_of": "2026-09-16"}, headers=PLAN).json()
    assert out["shadow"] and out["applied"] == [] and out["would_apply"]
    assert c.put(f"{base}/shadow-mode", json={"enabled": False}, headers=PLAN).json()["shadow_mode"] is False


def test_blind_set_script(tmp_path):
    spec = importlib.util.spec_from_file_location("blind", ROOT / "scripts" / "phase8" / "evaluate_blind.py")
    blind = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(blind)
    docs = ["dpr_2026-09-14_piping.txt", "dpr_2026-09-15_civil.txt", "dpr_2026-09-16_electrical.txt"]
    for d in docs:
        shutil.copy(SYNTH / "reports" / d, tmp_path / d)
    with (SYNTH / "ground_truth" / "labels.csv").open(encoding="utf-8") as fh, \
            (tmp_path / "labels.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["file", "activity_code", "event_type", "event_date"])
        for r in csv.DictReader(fh):
            name = Path(r["source_path"]).name
            code = r["true_activity_id"] or ("NEW" if r["unmatched_type"] == "new_activity" else "")
            if name in docs and code:
                w.writerow([name, code, r["event_type"], r["stated_date"]])
    r = blind.evaluate(tmp_path, SYNTH)
    assert r["labels"] > 10 and r["files"] == 3
    assert r["wrong_automatic_links"] == 0 and r["extraction_recall"] == 1.0 and r["auto_coverage"] > 0.5
    assert blind.main(["--blind", str(tmp_path), "--out", str(tmp_path / "report.json")]) == 0
