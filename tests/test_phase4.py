"""Phase 4: text Time Agent. Interpretation (deterministic + validated LLM), clarification, recording with the original
message as evidence, and hand-off to the EXISTING Phase 3 linker (match / review / unmatched)."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake import FakeListLLM
from sqlalchemy import func, select

from p2e.agent import time_agent as ta
from p2e.db.models import EventLink, ProgressEvent
from p2e.extract.pipeline import load_project_vocab
from p2e.ingest import service as ingest
from p2e.link import service as linking
from p2e.link.context import get_context
from p2e.main import create_app
from tests.test_phase3 import GLOSSARY, KEYS, SUP, db, world  # noqa: F401  (shared fixtures)

IST = timezone(timedelta(hours=5, minutes=30))
REF = datetime(2026, 9, 16, 18, 0, tzinfo=IST)
VOCAB = load_project_vocab(GLOSSARY).vocab


def interp(session, project, message, discipline="piping", answers=None, llm=None):
    ctx = get_context(session, project, GLOSSARY)
    raw, note = ta.interpret_llm(llm, ctx, message) if llm else (None, None)
    raw = raw or ta.interpret_rules(message, VOCAB)
    if note:
        raw.notes.append(note)
    return ta.finalize(raw, ctx, REF, discipline, answers or {})


# ----------------------------------------------------------------------------- interpretation (1-8)

@pytest.mark.parametrize("message,etype,day,extra", [
    ("Line 1211 hydrotest started today.", "start", date(2026, 9, 16), {}),                                    # 1, 5
    ("Line 1211 hydrotest finished yesterday at 4 pm", "finish", date(2026, 9, 15), {"event_time": "16:00"}),  # 2, 6
    ("Line 1211 erection – 2 spools erected on 14/09/2026", "progress", date(2026, 9, 14), {"quantity": 2.0, "unit": "spools"}),  # 3, 4
    ("LT-4011 loop check completed on 2026-09-12", "finish", date(2026, 9, 12), {}),                         # 4
])
def test_interpretation(db, message, etype, day, extra):
    session, project = db
    it = interp(session, project, message)
    assert it.missing == [] and it.event_type == etype and it.event_date == day and it.confidence == 1.0
    assert it.activity_text in message and it.tags                      # verbatim, never invented
    for k, v in extra.items():
        assert getattr(it, k) == v
    assert (it.public()["actual_start"], it.public()["actual_finish"]) == ((day, None) if etype == "start" else
                                                                          (None, day) if etype == "finish" else (None, None))


def test_relative_dates_use_the_supplied_reference_only(db):
    session, project = db
    ctx = get_context(session, project, GLOSSARY)
    raw = ta.interpret_rules("P-101A grouting finished yesterday", VOCAB)
    other = datetime(2026, 9, 25, 14, 30, tzinfo=IST)
    assert ta.finalize(raw, ctx, other, "rotating_eq", {}).event_date == date(2026, 9, 24)


@pytest.mark.parametrize("message,discipline,answers,missing,question", [
    ("Line 1211 reinstatement completed.", "piping", None, ["date"], "What date was it completed?"),      # 7
    ("work completed today", "piping", None, ["activity"], "Which activity"),                           # 8
    ("Line 1211 hydrotest started today", None, None, ["discipline"], "Which discipline"),
    ("Line 1211 erection started and completed today", "piping", None, ["event_type"], "more than one status"),
    ("Line 1211 spool erection today", "piping", None, ["event_type"], "start, finish or is it in progress"),
    ("Line 1211 erection done 12/09/2026 and 14/09/2026", "piping", None, ["date"], "more than one date"),
])
def test_missing_or_ambiguous_fields_ask(db, message, discipline, answers, missing, question):
    session, project = db
    it = interp(session, project, message, discipline, answers)
    assert it.missing == missing and question in it.question


def test_answer_completes_the_interpretation(db):
    session, project = db
    it = interp(session, project, "Line 1211 reinstatement completed.", answers={"date": "yesterday"})
    assert it.missing == [] and it.event_date == date(2026, 9, 15) and it.date_text == "yesterday"


# ----------------------------------------------------------------------------- LLM output validation (14)

@pytest.mark.parametrize("output,why", [
    ("not json at all", "rejected"),
    (json.dumps({"activity_text": "Erect piping line 24\"-P-1203-A1A", "event_type": "finish", "confidence": 0.9}), "not in the message"),
    (json.dumps({"activity_text": "Line 1211 hydrotest", "event_type": "finish", "date_text": "2026-09-01", "confidence": 0.9}), "not in the message"),
    (json.dumps({"activity_text": "Line 1211 hydrotest", "event_type": "done", "confidence": 0.9}), "rejected"),
    (json.dumps({"activity_text": "Line 1211 hydrotest", "plan_node_code": "PIP-A3-1211-HT", "confidence": 0.9}), "rejected"),
    (json.dumps({"activity_text": "Line 1211 hydrotest", "event_type": "finish", "quantity": 5, "unit": "m", "confidence": 0.9}), "quantity"),
])
def test_malformed_or_inventing_llm_output_is_rejected(db, output, why):
    session, project = db
    it = interp(session, project, "Line 1211 hydrotest finished yesterday", llm=FakeListLLM(responses=[output]))
    assert it.provider == "rules" and any(why in n for n in it.notes)            # fell back to the deterministic interpreter
    assert it.event_type == "finish" and it.event_date == date(2026, 9, 15)


def test_valid_llm_output_is_used(db):
    session, project = db
    out = json.dumps({"activity_text": "Line 1211 hydrotest", "event_type": "finish", "date_text": "yesterday", "confidence": 0.8})
    it = interp(session, project, "Line 1211 hydrotest finished yesterday", llm=FakeListLLM(responses=[out]))
    assert (it.provider, it.confidence, it.event_type, it.event_date) == ("llm", 0.8, "finish", date(2026, 9, 15))


# ----------------------------------------------------------------------------- API + existing linker (9-13)

@pytest.fixture
def api(db, world, tmp_path):
    session, project = db
    linking.link_events(session, project, GLOSSARY)            # the project's field reports are already linked
    session.commit()
    uploads = tmp_path / "uploads"
    shutil.copytree(world[0] / "uploads", uploads)
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=uploads)
    with TestClient(app, raise_server_exceptions=False) as c:
        def send(message, discipline="piping", **kw):
            body = {"message": message, "reference_datetime": REF.isoformat(), "discipline": discipline, **kw}
            return c.post(f"/api/v1/projects/{project.code}/agent/messages", json=body, headers=SUP)
        yield c, send, session, f"/api/v1/projects/{project.code}"
    app.state.engine.dispose()


def test_match_via_existing_linker(api, monkeypatch):
    c, send, session, base = api
    calls = []
    real = linking.link_events
    monkeypatch.setattr(linking, "link_events", lambda *a, **k: calls.append(k["event_ids"]) or real(*a, **k))
    r = send("LT-4011 loop check finished yesterday at 4 pm", discipline="instrumentation").json()
    assert r["status"] == "recorded" and calls == [[r["event_id"]]]                 # 9: handed to the Phase 3 service
    assert r["reply"] == "Recorded and linked to INS-A4-LT4011-LCK (Loop check LT-4011)."   # 10
    assert r["link"]["decision"] == "matched" and r["link"]["candidates"][0]["retrieval_methods"] == ["tag"]
    assert "schedule" not in r["reply"].lower() or "updated" not in r["reply"].lower()


def test_review_and_unmatched_responses(api):
    c, send, session, base = api
    review = send("Foundation works in Area-3 completed today", discipline="civil").json()
    assert review["status"] == "recorded" and review["reply"] == "Recorded, but planner review is required."        # 11
    assert review["link"]["decision"] == "review" and review["link"]["plan_node_code"] is None
    unmatched = send("RCC T-403 fdn completed today", discipline="civil").json()
    assert unmatched["reply"] == "Recorded, but it could not be safely linked to an existing activity."              # 12
    assert unmatched["link"]["unmatched_type"] == "unknown_reference"


def test_contradicting_report_goes_to_review_via_conflict_layer(api):
    c, send, session, base = api
    # the DPRs report line 1217 erection finished on 2026-09-05; the supervisor says the 14th
    r = send("Line 1217 erection completed on 14/09/2026").json()
    assert r["status"] == "recorded" and r["link"]["decision"] == "review"
    assert r["link"]["conflict"]["type"] == "cross_source_date_conflict" and "2026-09-14" in r["link"]["conflict"]["dates"]


def test_original_message_preserved_and_traceable(api):
    c, send, session, base = api
    msg = "LT-4011 loop check finished yesterday at 4 pm"
    r = send(msg, discipline="instrumentation").json()
    ev = c.get(f"{base}/events/{r['event_id']}", headers=SUP).json()
    assert ev["source_text"] == msg and ev["extraction_method"] == "time-agent" and ev["document_id"] == r["document_id"]   # 13
    proof = c.get(f"{base}/events/{r['event_id']}/evidence", headers=SUP).json()
    assert proof["found_in_source"] and proof["line_number"] == 3 and proof["line_text"] == msg
    assert "received: 2026-09-16T18:00:00+05:30 | role: supervisor" in proof["context"][1]["text"]
    doc = c.get(f"{base}/documents/{r['document_id']}", headers=SUP).json()
    assert doc["uploaded_by"] == "supervisor" and doc["latest_run"]["extractor"] == "time-agent"
    assert c.post(f"{base}/documents/{r['document_id']}/process", headers=SUP).json()["outcome"] == "unchanged"  # never re-parsed
    assert send(msg, discipline="instrumentation").json()["status"] == "duplicate"


def test_nothing_stored_without_a_complete_valid_event(api):
    c, send, session, base = api
    before = session.scalar(select(func.count()).select_from(ProgressEvent))
    ask = send("Line 1211 reinstatement completed.").json()
    assert ask["status"] == "needs_clarification" and ask["question"].startswith("What date") and ask["event_id"] is None
    future = send("P-101A grouting started on 2026-09-30", discipline="rotating_eq").json()
    assert future["status"] == "rejected" and "after the report date" in future["reply"]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(ProgressEvent)) == before
    done = send("Line 1211 reinstatement completed.", answers={"date": "yesterday"}).json()
    assert done["status"] == "recorded" and done["interpretation"]["event_date"] == "2026-09-15"
    assert c.post(f"/api/v1/projects/CGS-EXP-01/agent/messages", json={"message": "two\nlines"}, headers=SUP).status_code == 422
    assert c.post(f"/api/v1/projects/CGS-EXP-01/agent/messages", json={"message": "x"}).status_code == 401


def test_existing_links_untouched_by_agent_turns(api):
    c, send, session, base = api
    snap = {l.progress_event_id: (l.decision, l.state, l.plan_node_id, l.conflict) for l in session.scalars(select(EventLink))}
    send("LT-4011 loop check finished yesterday at 4 pm", discipline="instrumentation")
    session.expire_all()
    after = {l.progress_event_id: (l.decision, l.state, l.plan_node_id, l.conflict) for l in session.scalars(select(EventLink))}
    assert {k: v for k, v in after.items() if k in snap} == snap


def test_agent_document_is_skipped_by_batch_processing(db, world, tmp_path):
    session, project = db
    uploads = tmp_path / "u"
    shutil.copytree(world[0] / "uploads", uploads)
    out = ta.handle(session, project, "LT-4011 loop check finished yesterday", REF, "supervisor", uploads, GLOSSARY,
                    discipline="instrumentation")
    session.commit()
    res = ingest.process_batch(session, project, uploads, load_project_vocab(GLOSSARY), [out["document_id"]])
    assert res[0]["outcome"] == "unchanged" and session.get(ProgressEvent, out["event_id"]) is not None
