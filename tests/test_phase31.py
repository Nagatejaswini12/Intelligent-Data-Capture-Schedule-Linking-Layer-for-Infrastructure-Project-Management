"""Phase 3.1: cross-source date-conflict detection. Explicit small fixtures for the rules (A-E), then the real synthetic
project for routing to review, evidence, restore, idempotency, API and the additive migration (F, G, J)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from p2e.db.models import EventLink, ProgressEvent, Project
from p2e.db.session import init_db, make_engine
from p2e.ingest.service import evidence
from p2e.link import service
from p2e.link.conflicts import CONFLICT_TYPE, Report, find_conflicts
from p2e.main import create_app
from tests.test_phase3 import GLOSSARY, KEYS, PLAN, SUP, db, world  # noqa: F401  (shared fixtures)

DPR, SHEET = ("dpr_text", "piping"), ("spreadsheet", 99)
ALL_DAYS = lambda stream, day: True                       # noqa: E731


def rep(i, doc, et, day, qty=None, unit=None, stream=None):
    return Report(i, doc, stream or (DPR if doc < 50 else SHEET), et, day, qty, unit)


def rules(findings):
    return sorted(f["rule"] for f in findings)


# ----------------------------------------------------------------------------- the rules (explicit fixtures)

def test_A_same_date_different_sources_is_not_a_conflict():
    rs = [rep(1, 1, "finish", date(2026, 8, 10)), rep(2, 99, "finish", date(2026, 8, 10)),
          rep(3, 1, "progress", date(2026, 8, 9), 1, "spools"), rep(4, 99, "progress", date(2026, 8, 9), 1, "spools")]
    assert find_conflicts(rs, ALL_DAYS, 1) == []


def test_B_different_dates_different_sources_is_a_conflict():
    finish = find_conflicts([rep(1, 1, "finish", date(2026, 8, 10)), rep(2, 99, "finish", date(2026, 8, 12))], ALL_DAYS, 1)
    assert rules(finish) == ["milestone_date"] and finish[0]["event_ids"] == [1, 2]
    shift = find_conflicts([rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 3), 1, "spools")],
                           ALL_DAYS, 1)
    assert rules(shift) == ["quantity_date_shift"] and shift[0]["event_ids"] == [1, 2]
    after = find_conflicts([rep(1, 1, "finish", date(2026, 9, 5)), rep(2, 99, "progress", date(2026, 9, 7), 1, "spools")], ALL_DAYS, 1)
    assert rules(after) == ["work_after_reported_finish"]
    before = find_conflicts([rep(1, 1, "start", date(2026, 9, 5)), rep(2, 99, "progress", date(2026, 9, 3), 1, "spools")], ALL_DAYS, 1)
    assert rules(before) == ["work_before_reported_start"]


def test_C_missing_date_is_not_a_conflict():
    rs = [rep(1, 1, "finish", None), rep(2, 99, "finish", date(2026, 8, 12)),
          rep(3, 1, "progress", None, 1, "spools"), rep(4, 99, "progress", date(2026, 8, 13), 1, "spools")]
    assert find_conflicts(rs, ALL_DAYS, 1) == []


def test_D_progress_on_different_days_is_not_a_conflict():
    # normal progress: both sources agree day by day, or a source simply did not report on a day it does not cover
    agree = [rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 2), 1, "spools"),
             rep(3, 2, "progress", date(2026, 9, 3), 1, "spools"), rep(4, 99, "progress", date(2026, 9, 3), 1, "spools")]
    assert find_conflicts(agree, ALL_DAYS, 1) == []
    omitted = [rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 3), 1, "spools")]
    dpr_only_on_2nd = lambda stream, day: stream != DPR or day == date(2026, 9, 2)   # noqa: E731  (no DPR on the 3rd)
    assert find_conflicts(omitted, dpr_only_on_2nd, 1) == []
    far = [rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 6), 1, "spools")]
    assert find_conflicts(far, ALL_DAYS, 1) == []                         # beyond the shift window: separate work
    other_unit = [rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 3), 30, "m")]
    assert find_conflicts(other_unit, ALL_DAYS, 1) == []


def test_E_same_document_is_not_cross_source():
    one_doc = [rep(1, 1, "finish", date(2026, 8, 10)), rep(2, 1, "finish", date(2026, 8, 12)),
               rep(3, 1, "progress", date(2026, 8, 14), 1, "spools")]
    assert find_conflicts(one_doc, ALL_DAYS, 1) == []
    same_sheet = [rep(1, 99, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 3), 1, "spools")]
    assert find_conflicts(same_sheet, ALL_DAYS, 1) == []


# ----------------------------------------------------------------------------- the real synthetic project

def linked(session, project):
    out = service.link_events(session, project, GLOSSARY)
    session.commit()
    return out


def link_of(session, text_start):
    return session.scalar(select(EventLink).join(ProgressEvent, EventLink.progress_event_id == ProgressEvent.id)
                          .where(ProgressEvent.source_text.startswith(text_start)))


def test_F_conflict_routes_to_review_and_never_auto_links(db):
    session, project = db
    out = linked(session, project)
    assert out["conflicts"]["routed_to_review"] == out["conflicts"]["events_in_conflict"] > 0
    flagged = session.scalars(select(EventLink).where(EventLink.conflict.is_not(None))).all()
    assert flagged and all(l.decision == "review" and l.plan_node_id is None and l.state == "pending" for l in flagged)
    sheet = link_of(session, '16"-P-1211-A1A | 1211-SP-02')
    c = sheet.conflict
    assert c["type"] == CONFLICT_TYPE and c["plan_node_code"] == "PIP-A3-1211-ERC" and c["dates"] == ["2026-09-02", "2026-09-03"]
    assert {e["source_type"] for e in c["events"]} == {"dpr_text", "spreadsheet"} and len({e["document_id"] for e in c["events"]}) == 2
    assert sheet.reasons[0].startswith(CONFLICT_TYPE) and sheet.candidates[0].node.code == "PIP-A3-1211-ERC"   # candidate kept


def test_G_both_evidence_records_stay_intact_and_accessible(db, world):
    session, project = db
    before = {e.id: (e.source_document_id, e.source_text, e.event_date, e.event_type, e.quantity, e.validation_status)
              for e in session.scalars(select(ProgressEvent))}
    linked(session, project)
    after = {e.id: (e.source_document_id, e.source_text, e.event_date, e.event_type, e.quantity, e.validation_status)
             for e in session.scalars(select(ProgressEvent))}
    assert before == after                                                   # Phase 2 truth untouched
    sheet = link_of(session, '16"-P-1211-A1A | 1211-SP-02')
    for e in sheet.conflict["events"]:
        ev = session.get(ProgressEvent, e["event_id"])
        proof = evidence(ev.document, ev, world[0] / "uploads")
        assert proof["found_in_source"] and proof["source_text"] == e["source_text"]


def test_restore_after_reject_and_confirm_keeps_record(db):
    session, project = db
    linked(session, project)
    sheet, dpr = link_of(session, '16"-P-1211-A1A | 1211-SP-02'), link_of(session, "Spool erection 16 inch line 1211")
    assert dpr.conflict and sheet.conflict
    service.reject(session, project, dpr, "human:planner", GLOSSARY)            # planner discards the DPR report
    session.commit()
    assert (sheet.decision, sheet.state, sheet.conflict) == ("matched", "auto", None)
    assert sheet.node.code == "PIP-A3-1211-ERC" and not any(r.startswith(CONFLICT_TYPE) for r in sheet.reasons)
    other = link_of(session, '8"-P-1217-A1A | 1217-SP-06')
    service.confirm(session, project, other, "PIP-A3-1217-ERC", "human:planner", GLOSSARY)
    session.commit()
    assert other.state == "confirmed" and other.conflict is not None              # identity confirmed; contradiction still recorded


def test_J_relinking_is_idempotent_and_deterministic(db):
    session, project = db
    first = linked(session, project)
    snapshot = {l.progress_event_id: (l.decision, l.state, l.conflict) for l in session.scalars(select(EventLink))}
    second = linked(session, project)
    assert second["counts"] == {"unchanged": sum(first["counts"].values())}
    assert second["conflicts"]["routed_to_review"] == 0 and second["conflicts"]["restored_auto_match"] == 0
    assert {k: v for k, v in second["conflicts"].items() if k not in ("routed_to_review",)} == \
           {k: v for k, v in first["conflicts"].items() if k not in ("routed_to_review",)}
    assert snapshot == {l.progress_event_id: (l.decision, l.state, l.conflict) for l in session.scalars(select(EventLink))}


def test_api_exposes_conflicts(db, world):
    session, project = db
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=world[0] / "uploads")
    with TestClient(app) as c:
        base = f"/api/v1/projects/{project.code}"
        run = c.post(f"{base}/links/run", headers=SUP).json()
        assert run["conflicts"]["events_in_conflict"] > 0
        page = c.get(f"{base}/links?conflict=true&limit=1000", headers=SUP).json()
        assert page["total"] == run["conflicts"]["events_in_conflict"]
        assert all(i["decision"] == "review" and i["state"] == "pending" and i["conflict"]["type"] == CONFLICT_TYPE for i in page["items"])
        detail = c.get(f"{base}/links/{page['items'][0]['event_id']}", headers=SUP).json()
        conflict = detail["conflict"]
        assert conflict["plan_node_code"] and len(conflict["dates"]) >= 2 and conflict["findings"][0]["rule"]
        for e in conflict["events"]:                                          # both sides' evidence via the Phase 2 endpoint
            proof = c.get(f"{base}/events/{e['event_id']}/evidence", headers=SUP).json()
            assert proof["found_in_source"] and proof["document_id"] == e["document_id"]
        clean = c.get(f"{base}/links?conflict=false&decision=matched&limit=1", headers=SUP).json()
        assert clean["items"][0]["conflict"] is None
        eid = page["items"][0]["event_id"]
        assert c.post(f"{base}/links/{eid}/confirm", json={"plan_node_code": conflict["plan_node_code"]}, headers=PLAN).json()["link"]["conflict"]
    app.state.engine.dispose()


def test_migration_adds_conflict_column_to_a_phase3_database(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE event_link DROP COLUMN conflict"))    # what a Phase 3 database looks like
    assert "conflict" not in {c["name"] for c in inspect(engine).get_columns("event_link")}
    init_db(engine)
    init_db(engine)                                                           # idempotent
    assert "conflict" in {c["name"] for c in inspect(engine).get_columns("event_link")}
    engine.dispose()


@pytest.mark.parametrize("shift_days,expect_more", [(0, False), (2, True)])
def test_shift_window_is_a_cag_threshold(shift_days, expect_more):
    rs = [rep(1, 1, "progress", date(2026, 9, 2), 1, "spools"), rep(2, 99, "progress", date(2026, 9, 4), 1, "spools")]
    assert bool(find_conflicts(rs, ALL_DAYS, shift_days)) is expect_more
