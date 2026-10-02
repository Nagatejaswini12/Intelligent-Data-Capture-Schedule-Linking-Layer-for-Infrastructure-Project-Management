"""Silent-activity watch: expected-active activities without a recent field report, the supervisor checklist, and the
Time Agent's "what should I report today?" turn. Read-only: nothing in the schedule or the links changes."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from p2e.db.models import AuditLog, EventLink, PlanNode, ProgressEvent
from p2e.decide import apply as engine
from p2e.decide import watch
from p2e.link import service as linking
from tests.conftest import SYNTH
from tests.test_phase3 import GLOSSARY, PLAN, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase4 import REF
from tests.test_phase5 import api, linked  # noqa: F401

AS_OF = date(2026, 9, 16)


@pytest.fixture
def applied(linked):
    session, project, uploads = linked
    engine.apply(session, project, AS_OF)
    session.commit()
    return session, project, uploads


def codes(items):
    return {i["plan_node_code"] for i in items}


def test_silent_rule(applied):
    session, project, _ = applied
    items = watch.silent_activities(session, project, AS_OF, days=3)
    nodes = {n.code: n for n in session.scalars(select(PlanNode).where(PlanNode.node_type == "activity"))}
    assert items
    for i in items:
        n = nodes[i["plan_node_code"]]
        assert n.actual_finish is None and (n.actual_start is not None or n.planned_start <= AS_OF)     # expected active
        assert i["last_reported"] is None or (AS_OF - i["last_reported"]).days >= 3                  # and silent
    finished = {c for c, n in nodes.items() if n.actual_finish}
    future = {c for c, n in nodes.items() if n.planned_start > AS_OF and n.actual_start is None}
    assert not codes(items) & (finished | future)
    never = [i for i in items if i["last_reported"] is None]
    assert never and items[: len(never)] == never                          # never-reported first, then longest silence


def test_recent_report_clears_silence_and_rejected_reports_do_not_count(applied):
    session, project, _ = applied
    links = session.scalars(select(EventLink).where(EventLink.decision == "matched")).all()
    by_node = defaultdict(list)
    for l in links:
        by_node[l.plan_node_id].append(l)
    loud = next(n for n, ls in by_node.items() if max(l.event.event_date for l in ls) == AS_OF
                and session.get(PlanNode, n).actual_finish is None)
    code = session.get(PlanNode, loud).code
    assert code not in codes(watch.silent_activities(session, project, AS_OF, 3))
    for l in by_node[loud]:
        linking.reject(session, project, l, "human:planner", GLOSSARY)
    session.commit()
    assert code in codes(watch.silent_activities(session, project, AS_OF, 60))


def test_reports_after_as_of_and_window_length(applied):
    session, project, _ = applied
    early = date(2026, 9, 5)
    for i in watch.silent_activities(session, project, early, 3):
        assert i["last_reported"] is None or i["last_reported"] <= early
    assert len(watch.silent_activities(session, project, AS_OF, 1)) >= len(watch.silent_activities(session, project, AS_OF, 10))


def test_watch_finds_real_missed_reports():
    """Against the ground truth: some silent activities truly had work in the window that nobody reported."""
    truth = defaultdict(set)
    with open(SYNTH / "ground_truth" / "truth_events.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[r["activity_id"]].add(date.fromisoformat(r["event_date"]))
    import tempfile
    from pathlib import Path
    from scripts.phase3.evaluate_linking import build_db
    with tempfile.TemporaryDirectory() as tmp:
        eng, sm = build_db(SYNTH, Path(tmp))
        with sm() as session:
            from p2e.db.models import Project
            project = session.scalar(select(Project))
            linking.link_events(session, project, GLOSSARY)
            engine.apply(session, project, AS_OF)
            items = watch.silent_activities(session, project, AS_OF, 3)
            window = {AS_OF - timedelta(days=k) for k in range(3)}
            missed = [i for i in items if truth[i["plan_node_code"]] & window]
            assert len(items) > 50 and len(missed) >= 10
        eng.dispose()


def test_checklist_and_api(api):
    c, base, session, project = api
    c.post(f"{base}/apply", json={"as_of": "2026-09-16"}, headers=SUP)
    audit_before = len(session.scalars(select(AuditLog)).all())
    r = c.get(f"{base}/watch/silent?as_of=2026-09-16&days=3", headers=SUP).json()
    assert r["items"] and sum(r["counts"].values()) == len(r["items"]) and r["days"] == 3
    assert c.get(f"{base}/watch/silent?as_of=2026-09-16&discipline=piping", headers=SUP).json()["items"][0]["discipline"] == "piping"
    assert c.get(f"{base}/watch/silent?days=0", headers=SUP).status_code == 422
    assert c.get(f"{base}/watch/silent").status_code == 401
    cl = c.get(f"{base}/watch/checklist?discipline=piping&as_of=2026-09-16", headers=SUP).json()
    assert cl["items"] and all(i["discipline"] == "piping" and i["reported_today"] in (True, False) for i in cl["items"])
    assert any(i["reported_today"] for i in cl["items"])
    assert c.get(f"{base}/watch/checklist", headers=SUP).status_code == 422          # discipline required
    assert len(session.scalars(select(AuditLog)).all()) == audit_before                # read-only


def test_time_agent_checklist_turn(api):
    c, base, session, project = api
    events_before = len(session.scalars(select(ProgressEvent)).all())
    send = lambda body: c.post(f"{base}/agent/messages", json={"reference_datetime": REF.isoformat(), **body}, headers=SUP).json()  # noqa: E731
    ask = send({"message": "What should I report today?"})
    assert ask["status"] == "needs_clarification" and "discipline" in ask["question"]
    r = send({"message": "what should I report today?", "discipline": "piping"})
    assert r["status"] == "checklist" and r["checklist"] and r["event_id"] is None
    assert r["reply"].startswith(f"{len(r['checklist'])} piping activities are expected to be active today")
    assert send({"message": "checklist", "discipline": "civil"})["status"] == "checklist"
    session.expire_all()
    assert len(session.scalars(select(ProgressEvent)).all()) == events_before         # a question, not a report
