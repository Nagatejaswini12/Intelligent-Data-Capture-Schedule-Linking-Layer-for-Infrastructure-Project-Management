"""Upgrade L1–L4: Tamil / Hindi understanding, replies in the user's language, the scoped multilingual assistant, and the
public guide / terms documents."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from p2e import assistant
from p2e.i18n import LANGS, MESSAGES
from p2e.link.context import get_context
from p2e.main import create_app
from tests.test_phase3 import GLOSSARY, KEYS, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase4 import interp
from tests.test_phase5 import api, linked  # noqa: F401

AS_OF = date(2026, 9, 16)


# ----------------------------------------------------------------------------- L1: Tamil / Hindi in the Time Agent

@pytest.mark.parametrize("message,etype,day", [
    ("LT-4011 loop check நேற்று முடிந்தது", "finish", date(2026, 9, 15)),            # Tamil script
    ("Line 1211 hydrotest inniku start panniten", "start", date(2026, 9, 16)),       # Tanglish
    ("P-101A grouting nethu mudinjidhu", "finish", date(2026, 9, 15)),
    ("Line 1211 hydrotest இன்று நிறுத்தப்பட்டது", "hold", date(2026, 9, 16)),
    ("Line 1211 hydrotest மீண்டும் தொடங்கியது இன்று", "resume", date(2026, 9, 16)),  # longest phrase wins over "தொடங்கியது"
    ("Line 1211 hydrotest आज शुरू हुआ", "start", date(2026, 9, 16)),                 # Hindi script
    ("Line 1211 erection कल पूरा हो गया", "finish", date(2026, 9, 15)),
])
def test_tamil_and_hindi_messages(db, message, etype, day):
    session, project = db
    it = interp(session, project, message)
    assert it.missing == [] and it.event_type == etype and it.event_date == day
    assert it.activity_text in message and it.tags                                   # still verbatim, still tagged


def test_every_message_has_all_languages():
    assert all(set(v) == set(LANGS) and all(v[k] or k == "en" for k in v) for v in MESSAGES.values())


def test_agent_replies_in_the_users_language(db, tmp_path):
    session, project = db
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=tmp_path / "up")
    base, ref = f"/api/v1/projects/{project.code}", "2026-09-16T18:00:00+05:30"
    with TestClient(app) as c:
        ta = c.post(f"{base}/agent/messages", headers=SUP, json={"message": "LT-4011 loop check நேற்று முடிந்தது",
                                                                   "discipline": "instrumentation", "reference_datetime": ref}).json()
        assert ta["status"] == "recorded" and ta["reply"].startswith("பதிவு செய்யப்பட்டு")          # script -> Tamil reply
        hi = c.post(f"{base}/agent/messages", headers=SUP, json={"message": "Line 1211 reinstatement completed.", "lang": "hi",
                                                                   "discipline": "piping", "reference_datetime": ref}).json()
        assert hi["status"] == "needs_clarification" and "तारीख़" in hi["reply"]                    # chosen language
        en = c.post(f"{base}/agent/messages", headers=SUP, json={"message": "Line 1211 reinstatement completed.",
                                                                   "discipline": "piping", "reference_datetime": ref}).json()
        assert en["reply"].startswith("What date was it completed?")                                 # English unchanged
    app.state.engine.dispose()


# ----------------------------------------------------------------------------- L3: scoped multilingual assistant

@pytest.fixture
def applied_db(linked):
    from p2e.decide import apply as engine
    session, project, _ = linked
    engine.apply(session, project, AS_OF)
    return session, project, get_context(session, project, GLOSSARY)


@pytest.mark.parametrize("question,lang,topic,want_lang,expect", [
    ("What delayed piping work?", "en", "project", "en", "hold reports"),
    ("குழாய் வேலை ஏன் தாமதம்?", None, "project", "ta", "நிறுத்த அறிக்கைகள்"),
    ("पाइपिंग काम में देरी क्यों हुई?", None, "project", "hi", "रुकावट"),
    ("What is Oil India's net zero target?", "en", "company", "en", "2040"),
    ("ஆயில் இந்தியாவின் லாபம் என்ன?", None, "company", "ta", "₹7,039.63"),
    ("Oil India का शेयर कितना है?", "hi", "company", "hi", "शेयर"),
    ("Oil India employee reviews", "ta", "company", "ta", "அதிகாரப்பூர்வ"),      # official sources only
    ("How do I upload a report?", "en", "app", "en", "Field Reports"),
    ("அறிக்கையை எப்படிப் பதிவேற்றுவது?", None, "app", "ta", "Field Reports"),
    ("रिपोर्ट कैसे अपलोड करें?", None, "app", "hi", "Field Reports"),
    ("வணக்கம்", None, "greeting", "ta", "வணக்கம்"),
])
def test_assistant_answers_in_scope(applied_db, question, lang, topic, want_lang, expect):
    session, project, ctx = applied_db
    r = assistant.ask(session, project, question, ctx, AS_OF, lang)
    assert (r["topic"], r["lang"]) == (topic, want_lang) and expect in r["answer"], r
    if topic == "company":
        assert r["sources"] and all(s["url"].startswith("https://") and s["as_of"] for s in r["sources"])
    if topic == "project":
        assert r["citations"]


@pytest.mark.parametrize("question,lang", [
    ("Who won the cricket match yesterday?", "en"), ("இன்று வானிலை எப்படி?", None), ("How do I cook rice?", "en"),
    ("Write me a poem", "en"), ("Bitcoin price", "hi"), ("मुझे एक चुटकुला सुनाओ", None),
])
def test_assistant_declines_everything_else(applied_db, question, lang):
    session, project, ctx = applied_db
    r = assistant.ask(session, project, question, ctx, AS_OF, lang)
    assert r["topic"] == "out_of_scope" and r["answer"] == MESSAGES["refuse"][r["lang"]] and not r["sources"]


def test_assistant_api(api):
    c, base, _, _ = api
    assert c.post(f"{base}/assistant/ask", json={"question": "hi"}).status_code == 401
    r = c.post(f"{base}/assistant/ask", headers=SUP, json={"question": "What is Oil India's net zero target?", "lang": "ta"}).json()
    assert r["topic"] == "company" and r["lang"] == "ta" and "2040" in r["answer"]
    assert c.post(f"{base}/assistant/ask", headers=SUP, json={"question": "x", "lang": "fr"}).status_code == 422


# ----------------------------------------------------------------------------- L4: guide and terms

def test_help_documents_are_public_and_complete(api):
    c, _, _, _ = api
    guide, terms = c.get("/api/v1/help/guide").json(), c.get("/api/v1/help/terms").json()
    assert all(set(s["title"]) == set(LANGS) and all(len(s["steps"][l]) == len(s["steps"]["en"]) for l in LANGS)
               for s in guide["sections"])
    assert set(terms["title"]) == set(LANGS) and all(set(s["text"]) == set(LANGS) for s in terms["sections"])
    assert c.get("/api/v1/help/secrets").status_code == 422


def test_company_facts_cite_sources():
    kb = assistant.company()
    assert all(e["sources"] and e["as_of"] and set(e["text"]) == set(LANGS) for e in kb["entries"])
    assert Path(assistant.DATA / "company" / "oil_india.json").exists()
