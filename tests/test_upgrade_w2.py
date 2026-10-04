"""Upgrade W2: efficiency / ROI numbers are derived from real records and add up; the API validates its assumptions."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from p2e.analytics import efficiency as eff
from p2e.db.models import EventLink
from tests.test_phase3 import KEYS, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase5 import api, linked  # noqa: F401
from tests.test_watch import applied  # noqa: F401

AS_OF = date(2026, 9, 16)


def test_efficiency_adds_up(applied):
    session, project, _ = applied
    out = eff.efficiency(session, project, AS_OF)
    assert sum(out["tiers"].values()) == out["items"] > 0
    assert out["items"] == session.scalar(select(func.count()).select_from(EventLink))   # sheet rows (no report date) count too
    assert out["tiers"]["automatic"] > 0 and 0 < out["auto_link_rate"] <= 1
    assert sum(out["automatic_by_evidence"].values()) == out["tiers"]["automatic"]
    assert out["llm_calls"] == 0 and out["tokens"]["ours_estimated"] == 0          # no LLM configured: every decision is free
    assert out["tokens"]["llm_for_everything_estimated"] == out["items"] * 1500
    assert out["inr_per_1000_reports"]["ours"] == 0 < out["inr_per_1000_reports"]["llm_for_everything"]
    assert out["planner_hours_saved"] == round(out["tiers"]["automatic"] * 5 / 60, 1)
    assert out["processing_seconds_median"] is not None and out["processing_seconds_median"] >= 0


def test_assumptions_change_only_the_estimates(applied):
    session, project, _ = applied
    base = eff.efficiency(session, project, AS_OF)
    doubled = eff.efficiency(session, project, AS_OF, eff.Assumptions(manual_minutes_per_item=10, planner_inr_per_hour=1500))
    assert doubled["tiers"] == base["tiers"] and doubled["planner_inr_saved"] >= 4 * base["planner_inr_saved"] - 4


def test_efficiency_api(api):
    c, base, _, _ = api
    assert c.get(f"{base}/analytics/efficiency").status_code == 401
    r = c.get(f"{base}/analytics/efficiency", headers=SUP, params={"as_of": "2026-09-16", "planner_inr_per_hour": 1000})
    assert r.status_code == 200 and r.json()["assumptions"]["planner_inr_per_hour"] == 1000
    assert c.get(f"{base}/analytics/efficiency", headers=SUP, params={"manual_minutes_per_item": -1}).status_code == 422
