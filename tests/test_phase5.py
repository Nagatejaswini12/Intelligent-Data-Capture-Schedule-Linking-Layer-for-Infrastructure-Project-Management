"""Phase 5: decision rules, apply with append-only audit, undo, planner review actions (approve / choose another / new
activity / override), live-update stream, CSV + MSPDI export, and the plan's exit gate (upload -> auto-apply -> audit ->
undo -> state restored). Synthetic project; every test works on its own DB + upload copy."""
from __future__ import annotations

import io
import shutil
from datetime import date

import pytest
from defusedxml import ElementTree as SafeET
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from p2e.agent import time_agent
from p2e.db.models import AuditLog, EventLink, PlanNode, ProgressEvent
from p2e.db.session import init_db, make_engine, make_sessionmaker
from p2e.decide import apply as engine
from p2e.extract.pipeline import load_project_vocab
from p2e.ingest import service as ingest
from p2e.link import service as linking
from p2e.main import create_app
from p2e.plan import exporters
from p2e.plan.importers import import_schedule, read_schedule
from tests.test_phase3 import ADMIN, GLOSSARY, KEYS, PLAN, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase4 import REF

AS_OF = date(2026, 9, 16)


@pytest.fixture
def linked(db, world, tmp_path):
    session, project = db
    linking.link_events(session, project, GLOSSARY)
    session.commit()
    uploads = tmp_path / "uploads"
    shutil.copytree(world[0] / "uploads", uploads)
    return session, project, uploads


def node(session, code) -> PlanNode:
    session.expire_all()
    return session.scalar(select(PlanNode).where(PlanNode.code == code))


def actuals(session):
    session.expire_all()
    return {n.code: (n.actual_start, n.actual_finish, n.percent_complete) for n in session.scalars(select(PlanNode))}


def blocked_for(session, project, code, as_of=AS_OF):
    return next((p.blockers for p in engine.propose(session, project, as_of) if p.node.code == code), None)


def say(session, project, uploads, message, discipline):
    out = time_agent.handle(session, project, message, REF, "supervisor", uploads, GLOSSARY, discipline=discipline)
    session.commit()
    return out


# ----------------------------------------------------------------------------- apply + audit + undo

def test_linking_alone_never_changes_the_schedule(db):
    session, project = db
    before = actuals(session)
    linking.link_events(session, project, GLOSSARY)
    session.commit()
    assert actuals(session) == before and not session.scalars(select(AuditLog)).all()


def test_apply_writes_audited_changes_idempotently(linked):
    session, project, _ = linked
    before = actuals(session)
    r = engine.apply(session, project, AS_OF)
    session.commit()
    assert r["applied"] and r["blocked"]
    for e in r["applied"]:
        n = node(session, e.node.code)
        for f, (old, new) in e.changes.items():
            assert engine._iso(before[n.code][engine.FIELDS.index(f)]) == old and engine._iso(getattr(n, f)) == new
        assert e.actor == engine.AUTO_ACTOR and e.rule.endswith("_evidence") and e.evidence_event_ids and e.confidence >= 0.7
        for i in e.evidence_event_ids:                                       # traceable to the source sentences
            link = session.scalar(select(EventLink).where(EventLink.progress_event_id == i))
            assert session.get(ProgressEvent, i).source_text and link.plan_node_id == n.id and link.decision == "matched"
    again = engine.apply(session, project, AS_OF)
    assert again["applied"] == [] and len(session.scalars(select(AuditLog)).all()) == len(r["applied"])
    finished = [e for e in r["applied"] if "actual_finish" in e.changes]
    assert finished and all(node(session, e.node.code).percent_complete == 100.0 for e in finished)


def test_percent_uses_one_source_and_is_capped(linked):
    session, project, _ = linked
    r = engine.apply(session, project, AS_OF)
    partial = [e for e in r["applied"] if "percent_complete" in e.changes and "actual_finish" not in e.changes]
    assert partial and all(0 < e.changes["percent_complete"][1] <= 99.0 for e in partial)


def test_undo_restores_and_is_not_reapplied(linked):
    session, project, _ = linked
    before = actuals(session)
    entries = engine.apply(session, project, AS_OF)["applied"]
    session.commit()
    target = entries[0]
    u = engine.undo(session, project, target.id, "human:planner")
    session.commit()
    assert u.reverts_id == target.id and u.action == "undo" and actuals(session)[target.node.code] == before[target.node.code]
    with pytest.raises(engine.ApplyError) as e:
        engine.undo(session, project, target.id, "human:planner")
    assert e.value.status == 409
    again = engine.apply(session, project, AS_OF)
    assert target.node.code not in {x.node.code for x in again["applied"]}                 # planner's undo respected
    with pytest.raises(engine.ApplyError):
        engine.undo(session, project, u.id, "human:planner")                             # an undo is not undone


def test_audit_log_is_append_only(linked):
    session, project, _ = linked
    e = engine.apply(session, project, AS_OF)["applied"][0]
    session.commit()
    e.rule = "tampered"
    with pytest.raises(ValueError, match="append-only"):
        session.flush()
    session.rollback()
    session.delete(session.get(AuditLog, e.id))
    with pytest.raises(ValueError, match="append-only"):
        session.flush()
    session.rollback()


# ----------------------------------------------------------------------------- decision rules

def test_blocking_rules(linked):
    session, project, uploads = linked
    eng = engine
    # explicit start from the field on an activity without a recorded start -> applied; progress-only -> blocked
    assert any("actual start not reported" in b for p in eng.propose(session, project, AS_OF) for b in p.blockers)
    assert any("finish reported without any known actual start" in b for p in eng.propose(session, project, AS_OF) for b in p.blockers)
    # a report after the as-of date
    assert any(b.startswith("report dated after") for p in eng.propose(session, project, date(2026, 9, 5)) for b in p.blockers)
    # finish contradicting the imported actual finish (K-301 excavation finished 2026-08-07 in the schedule)
    say(session, project, uploads, "Excavation for K-301 foundation completed on 2026-09-10", "civil")
    assert any("recorded actual finish is 2026-08-07" in b for b in blocked_for(session, project, "CIV-A1-K301-EXC"))
    # two finish reports in ONE document, days apart (not a cross-source conflict, still not credible)
    dpr = ("CGS EXPANSION PROJECT - DAILY PROGRESS REPORT\nDiscipline: Instrumentation\nDate: 2026-09-14    Report No: X\n\n"
           "Work Done Today:\n1. LT-1103 loop check compl. on 10/09/2026\n2. LT-1103 loop check compl. on 13/09/2026\n")
    doc = ingest.ingest_upload(session, project, "two.txt", dpr.encode(), "supervisor", uploads)
    ingest.process_document(session, doc, uploads, load_project_vocab(GLOSSARY))
    linking.link_events(session, project, GLOSSARY)
    session.commit()
    assert any("more than 1 day apart" in b for b in blocked_for(session, project, "INS-A1-LT1103-LCK"))


def test_confirmed_report_with_open_conflict_is_not_applied(linked):
    session, project, _ = linked
    sheet = session.scalar(select(EventLink).join(ProgressEvent, EventLink.progress_event_id == ProgressEvent.id)
                           .where(ProgressEvent.source_text.startswith('16"-P-1211-A1A | 1211-SP-02')))
    linking.confirm(session, project, sheet, "PIP-A3-1211-ERC", "human:planner", GLOSSARY)
    session.commit()
    assert any("unresolved cross-source date conflict" in b for b in blocked_for(session, project, "PIP-A3-1211-ERC"))


def test_predecessor_warning_is_recorded(linked):
    session, project, _ = linked
    r = engine.apply(session, project, AS_OF)
    assert any("predecessor" in w for e in r["applied"] for w in e.warnings)


def test_override_validates_and_resolves(linked):
    session, project, _ = linked
    blocked = next(p for p in engine.propose(session, project, AS_OF) if any("actual start not reported" in b for b in p.blockers))
    n = blocked.node
    for values, msg in (({"actual_finish": date(2026, 9, 5)}, "needs an actual start"),
                        ({"actual_start": date(2026, 9, 20)}, "after 2026-09-16"),
                        ({"actual_start": date(2026, 9, 9), "actual_finish": date(2026, 9, 8)}, "before start"),
                        ({"actual_start": date(2026, 9, 9), "percent_complete": 100.0}, "needs an actual finish")):
        with pytest.raises(engine.ApplyError, match=msg):
            engine.override(session, project, n, values, "human:planner", AS_OF)
    entry = engine.override(session, project, n, {"actual_start": date(2026, 9, 3)}, "human:planner", AS_OF, blocked.evidence)
    session.commit()
    assert entry.rule == "planner_override" and node(session, n.code).actual_start == date(2026, 9, 3)
    assert not any("actual start not reported" in b for b in blocked_for(session, project, n.code) or [])


# ----------------------------------------------------------------------------- API: queue, actions, stream, export, exit gate

@pytest.fixture
def api(linked):
    session, project, uploads = linked
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=uploads)
    with TestClient(app) as c:
        yield c, f"/api/v1/projects/{project.code}", session, project
    app.state.engine.dispose()


def test_exit_gate_upload_apply_audit_undo(api):
    c, base, session, project = api
    dpr = ("CGS EXPANSION PROJECT - DAILY PROGRESS REPORT\nDiscipline: Instrumentation\nDate: 2026-09-15    Report No: Z\n\n"
           "Work Done Today:\n1. PT-1102 loop check started today\n")
    doc = c.post(f"{base}/documents", files={"file": ("z.txt", dpr.encode())}, headers=SUP).json()
    assert c.post(f"{base}/documents/{doc['id']}/process", headers=SUP).json()["outcome"] == "processed"
    c.post(f"{base}/links/run", headers=SUP)
    before = actuals(session)["INS-A1-PT1102-LCK"]
    r = c.post(f"{base}/apply", json={"as_of": "2026-09-16"}, headers=SUP).json()
    entry = next(e for e in r["applied"] if e["plan_node_code"] == "INS-A1-PT1102-LCK")
    assert entry["changes"]["actual_start"] == [None, "2026-09-15"]
    audit = c.get(f"{base}/audit?plan_node_code=INS-A1-PT1102-LCK", headers=SUP).json()
    assert audit["items"][0]["id"] == entry["id"] and audit["items"][0]["evidence_event_ids"]
    ev = c.get(f"{base}/events/{entry['evidence_event_ids'][0]}/evidence", headers=SUP).json()
    assert ev["found_in_source"] and "PT-1102 loop check started today" in ev["line_text"]   # traceable to the sentence
    assert c.post(f"{base}/audit/{entry['id']}/undo", headers=SUP).status_code == 403
    undo = c.post(f"{base}/audit/{entry['id']}/undo", headers=PLAN).json()
    assert undo["reverts_id"] == entry["id"] and actuals(session)["INS-A1-PT1102-LCK"] == before
    listed = c.get(f"{base}/audit?plan_node_code=INS-A1-PT1102-LCK", headers=SUP).json()["items"]
    assert listed[0]["undone_by"] == undo["id"] and len(listed) == 2


def test_review_queue_and_planner_actions(api):
    c, base, session, project = api
    q = c.get(f"{base}/review?as_of=2026-09-16", headers=SUP).json()
    assert q["counts"]["pending_events"] > 0 and q["counts"]["blocked_activities"] == len(q["activities"]) > 0
    assert all(len(e["candidates"]) <= 3 for e in q["events"]) and q["counts"]["pending_conflicts"] > 0
    assert all(a["blockers"] and a["evidence_event_ids"] for a in q["activities"])
    item = next(e for e in q["events"] if e["candidates"] and not e["conflict"])
    assert c.post(f"{base}/review/events/{item['event_id']}/approve", headers=SUP).status_code == 403
    choose = item["candidates"][-1]["plan_node_code"]                       # "choose another"
    r = c.post(f"{base}/review/events/{item['event_id']}/approve", json={"plan_node_code": choose, "as_of": "2026-09-16"},
               headers=PLAN).json()
    assert r["link"]["state"] == "confirmed" and r["link"]["plan_node_code"] == choose and "applied" in r["apply"]


def test_mark_new_activity(api):
    c, base, session, project = api
    links = c.get(f"{base}/links?decision=unmatched&limit=1000", headers=SUP).json()["items"]
    ev = next(i for i in links if i["activity_text"].lower().startswith("temporary drainage trench near pr-3")
              and i["event_type"] == "start")
    bad = c.post(f"{base}/review/events/{ev['event_id']}/new-activity", headers=PLAN,
                 json={"parent_code": "CGS-EXP-01.A3.CIV", "code": "CIV-A3-NW01", "name": "Temporary drainage trench near PR-3"})
    assert bad.status_code == 422                                           # L3 parent: activities live at L5/L6
    parent = node(session, "CIV-A3-PR3-PED").parent.code
    r = c.post(f"{base}/review/events/{ev['event_id']}/new-activity", headers=PLAN,
               json={"parent_code": parent, "code": "CIV-A3-NW01", "name": "Temporary drainage trench near PR-3", "as_of": "2026-09-16"})
    assert r.status_code == 200, r.text
    body = r.json()
    n = node(session, "CIV-A3-NW01")
    assert (n.level, n.node_type, n.parent.code, [t.tag for t in n.tags]) == (5, "activity", parent, ["PR-3"])
    assert body["link"]["plan_node_code"] == "CIV-A3-NW01" and body["link"]["state"] == "confirmed"
    assert n.actual_start == date.fromisoformat(ev["event_date"])
    actions = [a["action"] for a in c.get(f"{base}/audit?plan_node_code=CIV-A3-NW01", headers=SUP).json()["items"]]
    assert actions == ["create_activity", "apply"]
    dup = c.post(f"{base}/review/events/{ev['event_id']}/new-activity", headers=PLAN,
                 json={"parent_code": parent, "code": "CIV-A3-NW01", "name": "x"})
    assert dup.status_code == 409


def test_override_endpoint_only_changes_given_fields(api):
    c, base, session, project = api
    q = c.get(f"{base}/review?as_of=2026-09-16", headers=SUP).json()
    code = next(a["plan_node_code"] for a in q["activities"] if any("actual start not reported" in b for b in a["blockers"]))
    before = actuals(session)[code]
    r = c.post(f"{base}/review/activities/{code}/override", json={"actual_start": "2026-09-02", "as_of": "2026-09-16"}, headers=PLAN)
    assert r.status_code == 200 and r.json()["changes"] == {"actual_start": [None, "2026-09-02"]}
    assert actuals(session)[code][1:] == before[1:]
    bad = c.post(f"{base}/review/activities/{code}/override", json={"actual_finish": "2026-09-01", "as_of": "2026-09-16"}, headers=PLAN)
    assert bad.status_code == 422


def test_stream_sends_snapshot(api):
    c, base, session, project = api
    with c.stream("GET", f"{base}/stream?limit=1", headers=SUP) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.startswith("event: update\ndata: {") and '"pending_review"' in body
    from p2e.api.review import snapshot
    s1 = snapshot(session, project)
    engine.apply(session, project, AS_OF)
    session.commit()
    s2 = snapshot(session, project)
    assert s2["audit_last_id"] > s1["audit_last_id"] and s2["activities_with_actuals"] > s1["activities_with_actuals"]


def test_exports_round_trip_through_the_phase1_importer(api, tmp_path):
    c, base, session, project = api
    engine.apply(session, project, AS_OF)
    session.commit()
    expected = {k: v[:2] for k, v in actuals(session).items() if node(session, k).node_type == "activity"}
    csv_text = c.get(f"{base}/export/schedule.csv", headers=SUP).text
    xml = c.get(f"{base}/export/schedule.xml?status_date=2026-09-16", headers=SUP).content
    assert csv_text.splitlines()[0].endswith("actual_start,actual_finish,percent_complete")
    assert SafeET.parse(io.BytesIO(xml)).getroot().findtext("{http://schemas.microsoft.com/project}StatusDate").startswith("2026-09-16")
    for name, data in (("x.csv", csv_text.encode()), ("x.xml", xml)):
        (tmp_path / name).write_bytes(data)
        eng = make_engine(f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}")
        init_db(eng)
        with make_sessionmaker(eng).begin() as s2:
            import_schedule(s2, read_schedule(tmp_path / name), AS_OF)
        with make_sessionmaker(eng)() as s2:
            got = {n.code: (n.actual_start, n.actual_finish) for n in s2.scalars(select(PlanNode).where(PlanNode.node_type == "activity"))}
        assert got == expected, name
        eng.dispose()


def test_migration_adds_percent_complete(tmp_path):
    eng = make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    init_db(eng)
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE plan_node DROP COLUMN percent_complete"))
    init_db(eng)
    init_db(eng)
    assert "percent_complete" in {c["name"] for c in inspect(eng).get_columns("plan_node")}
    eng.dispose()


def test_apply_evaluation_gate():
    from scripts.phase5.evaluate_apply import evaluate
    from tests.conftest import SYNTH
    rep = evaluate(SYNTH)
    assert rep["applied_not_matching_truth"] == [] and rep["applied_activities"] > 50
    assert rep["exit_gate"] == {"audit_entries": rep["applied_activities"], "audit_complete": True, "undo_restored_state": True,
                                "undone_changes_reapplied": 0}
    assert rep["export_round_trip"] == {"csv": True, "xml": True}
