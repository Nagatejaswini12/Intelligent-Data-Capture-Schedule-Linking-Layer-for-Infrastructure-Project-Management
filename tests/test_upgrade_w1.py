"""Upgrade W1: menu-first capture (checklist tap -> plain-name message -> the normal rules + linker path, 0 LLM tokens)
and Hinglish relative dates."""
from __future__ import annotations

from datetime import date

import pytest

from p2e.agent import time_agent as ta
from p2e.decide import watch
from tests.test_phase3 import GLOSSARY, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase4 import REF, interp

TAP = {"start": "started", "finish": "completed", "hold": "on hold"}     # what the Agent page menu sends


def menu_message(name: str, event_type: str) -> str:
    return f"{name} {TAP[event_type]} today"


def test_menu_taps_never_link_a_wrong_activity(db, tmp_path):
    """Every checklist item tapped as 'started': recorded, never linked to another activity, and almost always matched
    automatically. Near-identical plan names (tank shell courses 1–3 vs 4–6) correctly go to planner review."""
    session, project = db
    matched, review, wrong = [], [], []
    for discipline in ("civil", "piping", "electrical", "instrumentation", "static_eq"):
        for i in watch.checklist(session, project, REF.date(), discipline):
            out = ta.handle(session, project, menu_message(i["activity_name"], "start"), REF, "supervisor", tmp_path / "up",
                            GLOSSARY, discipline=discipline)
            assert out["status"] == "recorded", (i["plan_node_code"], out["reply"])
            link = ta.linking.get_link(session, project, out["event_id"])
            if link.node is None:
                review.append(i["plan_node_code"])
            elif link.node.code == i["plan_node_code"]:
                matched.append(i["plan_node_code"])
            else:
                wrong.append((i["plan_node_code"], link.node.code))
    assert not wrong, wrong
    assert len(matched) >= 0.9 * (len(matched) + len(review)), review


@pytest.mark.parametrize("message,etype,day", [
    ("Line 1211 hydrotest kal complete ho gaya", "finish", date(2026, 9, 15)),
    ("Line 1211 hydrotest aaj shuru", "start", date(2026, 9, 16)),
    ("Line 1211 hydrotest ruka hua hai aaj", "hold", date(2026, 9, 16)),
])
def test_hinglish_status_and_dates(db, message, etype, day):
    session, project = db
    it = interp(session, project, message)
    assert it.missing == [] and it.event_type == etype and it.event_date == day and it.activity_text in message


def test_supervisor_retract_sends_own_report_to_review(db, tmp_path):
    from fastapi.testclient import TestClient
    from p2e.main import create_app
    from tests.test_phase3 import KEYS, PLAN, SUP
    session, project = db
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=tmp_path / "up")
    base = f"/api/v1/projects/{project.code}"
    with TestClient(app) as c:
        r = c.post(f"{base}/agent/messages", headers=SUP, json={"message": "LT-4011 loop check finished yesterday at 4 pm",
                                                                 "discipline": "instrumentation", "reference_datetime": REF.isoformat()}).json()
        assert r["status"] == "recorded" and r["link"]["decision"] == "matched"
        assert c.post(f"{base}/agent/events/{r['event_id']}/retract").status_code == 401
        out = c.post(f"{base}/agent/events/{r['event_id']}/retract", headers=SUP)
        assert out.status_code == 200 and out.json()["decision"] == "review" and out.json()["plan_node_code"] is None
        assert c.get(f"{base}/events/{r['event_id']}/evidence", headers=SUP).status_code == 200      # evidence kept
        assert c.post(f"{base}/links/run", headers=PLAN, json={}).status_code == 200
        dpr_event = c.get(f"{base}/links?decision=matched&limit=1", headers=PLAN).json()["items"][0]["event_id"]
        assert c.post(f"{base}/agent/events/{dpr_event}/retract", headers=SUP).status_code == 409     # only Time Agent reports
    app.state.engine.dispose()
