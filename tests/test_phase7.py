"""Phase 7 backend additions for the web UI: JSON dataset, planner "send to review" (hold), serving the built frontend, and a
contract test that every API route the frontend calls (web/src/api/p2e.ts) exists in the FastAPI app."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from p2e.db.models import EventLink, ProgressEvent
from p2e.link import service as linking
from p2e.main import create_app
from tests.test_phase3 import ADMIN, GLOSSARY, KEYS, PLAN, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase5 import api, linked  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_dataset_json_matches_csv(api):
    c, base, session, project = api
    c.post(f"{base}/apply", json={"as_of": "2026-09-16"}, headers=SUP)
    j = c.get(f"{base}/analytics/dataset?as_of=2026-09-16", headers=SUP).json()
    rows = list(csv.DictReader(io.StringIO(c.get(f"{base}/analytics/dataset.csv?as_of=2026-09-16", headers=SUP).text)))
    assert j["as_of"] == "2026-09-16" and len(j["items"]) == len(rows) > 300
    assert list(j["items"][0]) == list(rows[0]) and not any(k.startswith("_") for k in j["items"][0])
    by = {r["code"]: r for r in rows}
    for item in j["items"]:
        assert str(item["status"]) == by[item["code"]]["status"] and (item["actual_start"] or "") == by[item["code"]]["actual_start"]
    assert c.get(f"{base}/analytics/dataset").status_code == 401


def test_hold_sends_a_decision_back_to_review(api):
    c, base, session, project = api
    auto = c.get(f"{base}/links?decision=matched&state=auto&limit=1", headers=SUP).json()["items"][0]
    eid = auto["event_id"]
    assert c.post(f"{base}/links/{eid}/hold", headers=SUP).status_code == 403
    held = c.post(f"{base}/links/{eid}/hold", headers=PLAN).json()
    assert (held["decision"], held["state"], held["plan_node_code"], held["decided_by"]) == ("review", "pending", None, "human:planner")
    assert held["reasons"][0] == linking.HELD_REASON and held["candidates"]               # candidates kept for the planner
    run = c.post(f"{base}/links/run", headers=SUP).json()
    assert run["counts"].get("kept_planner_decision", 0) >= 1
    assert c.get(f"{base}/links/{eid}", headers=SUP).json()["state"] == "pending"           # linker does not override
    q = c.get(f"{base}/review?as_of=2026-09-16&limit=1000", headers=SUP).json()
    assert eid in {e["event_id"] for e in q["events"]}
    ok = c.post(f"{base}/review/events/{eid}/approve", json={"as_of": "2026-09-16"}, headers=PLAN).json()
    assert ok["link"]["state"] == "confirmed" and ok["link"]["plan_node_code"] == auto["plan_node_code"]
    assert c.post(f"{base}/links/{eid}/hold", headers=PLAN).status_code == 409             # planner decision stands


def test_held_conflict_report_is_not_auto_restored(linked):
    session, project, _ = linked
    sheet = session.scalar(select(EventLink).join(ProgressEvent, EventLink.progress_event_id == ProgressEvent.id)
                           .where(ProgressEvent.source_text.startswith('16"-P-1211-A1A | 1211-SP-02')))
    dpr = session.scalar(select(EventLink).join(ProgressEvent, EventLink.progress_event_id == ProgressEvent.id)
                         .where(ProgressEvent.source_text.startswith("Spool erection 16 inch line 1211")))
    assert sheet.conflict and dpr.conflict
    linking.hold(session, sheet, "human:planner")
    linking.reject(session, project, dpr, "human:planner", GLOSSARY)       # lifts the conflict
    session.commit()
    assert (sheet.state, sheet.decision) == ("pending", "review")           # still the planner's hold, not restored


def test_built_frontend_is_served_without_shadowing_the_api(db, tmp_path):
    session, project = db
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>P2E Bridge</title>", encoding="utf-8")
    url = session.get_bind().url.render_as_string()
    app = create_app(url, api_keys=dict(KEYS), web_dist=dist)
    with TestClient(app) as c:
        assert "P2E Bridge" in c.get("/").text
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/api/v1/projects").json()[0]["code"] == project.code
        assert c.get("/docs").status_code == 200
    app.state.engine.dispose()
    bare = create_app(url, api_keys=dict(KEYS), web_dist=tmp_path / "missing")
    with TestClient(bare) as c:
        assert c.get("/").status_code == 404                               # no build -> API only, as before
    bare.state.engine.dispose()


def frontend_routes() -> set[tuple[str, str]]:
    """(METHOD, path template) for every call in web/src/api/p2e.ts."""
    src = (ROOT / "web" / "src" / "api" / "p2e.ts").read_text(encoding="utf-8")
    out = set()
    for line in src.splitlines():
        for m in re.finditer(r"(?:api<.+?>|request|download)\(\s*[`\"]([^`\"]+)[`\"]", line):
            path = m.group(1).replace("${P(c)}", "/api/v1/projects/{project_code}")
            path = re.sub(r"\$\{[^}]+\}", "{x}", path)
            method = re.search(r"method:\s*\"(\w+)\"", line)
            out.add((method.group(1) if method else "GET", path))
    return out


def test_every_frontend_call_exists_in_the_api(db):
    session, _ = db
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS))
    norm = lambda p: re.sub(r"\{[^}]+\}", "{x}", p)                         # noqa: E731
    routes = {(m.upper(), norm(path)) for path, ops in app.openapi()["paths"].items() for m in ops}
    calls = frontend_routes()
    assert len(calls) >= 35                                                 # every distinct route the UI uses
    missing = [(m, p) for m, p in calls if (m, norm(p)) not in routes]
    assert missing == []
    app.state.engine.dispose()
