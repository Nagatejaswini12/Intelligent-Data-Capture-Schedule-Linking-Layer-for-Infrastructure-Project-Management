"""Scoped multilingual assistant (chat + voice front-ends share it). Deterministic: no LLM, 0 tokens.

question -> language (script, else the caller's choice) -> topic:
  project  this project's records, via the existing cited Q&A (p2e.analytics.qa); Tamil / Hindi question words are mapped
           to the English intents and the answer is rebuilt in the user's language from the computed values
  app      how to use P2E Bridge, from the user guide (data/help/guide.json)
  company  Oil India Limited facts, each with its public source and as-of date (data/company/oil_india.json)
  greeting / anything else -> a short greeting, or a polite refusal: the assistant never answers outside these topics.
"""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from p2e.analytics import qa
from p2e.db.models import Project
from p2e.extract.rules import extract_tags
from p2e.i18n import detect, lang_of, tr, word
from p2e.link.context import ProjectContext

DATA = Path(__file__).resolve().parents[1] / "data"
INDIC = "ऀ-ॿ஀-௿"

GREETINGS = ["hi", "hello", "hey", "good morning", "good evening", "vanakkam", "namaste", "வணக்கம்", "नमस्ते", "नमस्कार"]
# "how" alone is not a topic ("how is the weather?" must be declined), so only app-specific words count
APP_WORDS = ["upload", "login", "log in", "sign in", "access key",
             "review queue", "approve", "undo", "shadow mode", "roi", "export", "import", "voice", "mic", "microphone", "language",
             "help", "guide", "p2e", "the app", "this app", "application", "feature", "terms", "privacy", "dashboard", "time agent",
             "assistant", "pm report", "weekly report", "daily report",
             "பதிவேற்ற", "உள்நுழை", "செயலி", "உதவி", "வழிகாட்டி", "அம்சம்", "மொழி", "குரல்", "விதிமுறை",
             "अपलोड", "लॉगिन", "ऐप", "मदद", "गाइड", "सुविधा", "भाषा", "आवाज़", "शर्तें"]
COMPANY_NAME = {"oil india", "oil india limited", "oil", "company", "ஆயில் இந்தியா", "நிறுவனம்", "ऑयल इंडिया", "कंपनी"}
PROJECT_WORDS = ["activity", "activities", "schedule", "delay", "delays", "delayed", "late", "behind", "status", "progress",
                 "how many", "how long", "line", "pump", "tank", "area", "discipline", "piping", "civil", "electrical",
                 "instrumentation", "mechanical", "hydrotest", "erection", "welding", "foundation", "started", "finished",
                 "completed", "hold", "held", "duration", "productivity", "per day", "not reported", "last report", "silent",
                 "project", "site"]
# Tamil / Hindi project words -> the English words the Q&A intents understand
PROJECT_MAP = {
    "தாமதம்": "delay", "தாமதமானது": "delay", "தாமதமாக": "late", "ஏன்": "why", "நிலை": "status", "நிலவரம்": "status",
    "எத்தனை": "how many", "எவ்வளவு நாள்": "how long", "காலம்": "how long", "நிறுத்தம்": "hold", "பதிவாகவில்லை": "not reported",
    "குழாய்": "piping", "மின்": "electrical", "மின்சார": "electrical", "சிவில்": "civil", "கட்டுமான": "civil", "கருவி": "instrumentation",
    "வேலை": "activity", "வேலைகள்": "activities", "திட்ட": "project", "முன்னேற்றம்": "progress", "பகுதி": "area",
    "देरी": "delay", "क्यों": "why", "स्थिति": "status", "कितने": "how many", "कितनी": "how many", "कितना समय": "how long",
    "कितने दिन": "how long", "पीछे": "behind", "लेट": "late", "रुका": "hold", "रिपोर्ट नहीं": "not reported",
    "पाइपिंग": "piping", "इलेक्ट्रिकल": "electrical", "बिजली": "electrical", "सिविल": "civil", "इंस्ट्रुमेंटेशन": "instrumentation",
    "काम": "activity", "प्रोजेक्ट": "project", "प्रगति": "progress", "क्षेत्र": "area",
}


@lru_cache(maxsize=1)
def company() -> dict:
    return json.loads((DATA / "company" / "oil_india.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def guide() -> dict:
    return json.loads((DATA / "help" / "guide.json").read_text(encoding="utf-8"))


def _has(low: str, phrase: str) -> bool:
    """Whole-word match; Tamil / Hindi words may carry suffixes (பதிவேற்றுவது, எப்படிப்), so only their start is anchored."""
    end = "" if re.search(f"[{INDIC}]", phrase) else rf"(?![a-z0-9{INDIC}])"
    return re.search(rf"(?<![a-z0-9{INDIC}]){re.escape(phrase.lower())}{end}", low) is not None


def _hits(low: str, words) -> int:
    return sum(_has(low, w) for w in words)


def company_words() -> set[str]:
    return COMPANY_NAME | {k for e in company()["entries"] for k in e["keywords"]}


def classify(question: str) -> str | None:
    low = question.lower().strip()
    scores = {"project": _hits(low, PROJECT_WORDS) + _hits(low, PROJECT_MAP) + 2 * bool(extract_tags(question)),
              "app": _hits(low, APP_WORDS), "company": _hits(low, company_words())}
    best = max(scores.values())
    if best == 0:
        return "greeting" if any(_has(low, g) for g in GREETINGS) else None
    return next(t for t in ("project", "app", "company") if scores[t] == best)


def _company_answer(low: str, lang: str) -> dict:
    kb = company()
    # the company's name says nothing about WHICH fact is wanted: rank on the specific words, fall back to the overview
    ranked = sorted(((sum(_has(low, k) for k in e["keywords"] if k not in COMPANY_NAME), i, e) for i, e in enumerate(kb["entries"])),
                    key=lambda x: (-x[0], x[1]))
    if ranked[0][0] == 0 and _hits(low, COMPANY_NAME):
        ranked = [(1, 0, next(e for e in kb["entries"] if e["id"] == "overview"))]
    if ranked[0][0] == 0:
        topics = ", ".join(e["topic"] for e in kb["entries"])
        return {"answer": tr(lang, "company_none", topics=topics), "sources": [], "citations": []}
    picked = [e for s, _, e in ranked[:2] if s > 0 and s >= ranked[0][0] - 1]
    return {"answer": " ".join(e["text"][lang] for e in picked),
            "sources": [s | {"as_of": e["as_of"]} for e in picked for s in e["sources"]],
            "citations": [{"kind": "company", "id": e["id"], "text": e["topic"], "date": e["as_of"]} for e in picked]}


def _app_answer(low: str, lang: str) -> dict:
    sections = guide()["sections"]
    ranked = sorted(((sum(_has(low, k) for k in s["keywords"]), i, s) for i, s in enumerate(sections)), key=lambda x: (-x[0], x[1]))
    s = ranked[0][2] if ranked[0][0] > 0 else next(x for x in sections if x["id"] == "start")
    return {"answer": f"{s['title'][lang]}: " + " ".join(s["steps"][lang]), "sources": [],
            "citations": [{"kind": "guide", "id": s["id"], "text": s["title"][lang]}]}


def _english_question(question: str) -> str:
    low = question.lower()
    return " ".join([question] + [en for k, en in PROJECT_MAP.items() if _has(low, k)])


def _localize(out: dict, lang: str) -> str:
    """Rebuild a project answer in Tamil / Hindi from the values the Q&A computed (English: the Q&A's own sentence)."""
    if lang == "en":
        return out["answer"]
    v, intent, as_of = out.get("values") or {}, out["intent"], out["filters"]["as_of"]
    if not v:
        return tr(lang, "no_records")
    if intent == "duration":
        return tr(lang, "p_duration", n=v["n"], mean=v["mean_actual_days"], lo=v["min_days"], hi=v["max_days"],
                  plan=v["mean_planned_days"], as_of=as_of)
    if intent == "delays":
        if not v["holds"]:
            return tr(lang, "no_records")
        cats = ", ".join(f"{word(lang, 'cat', c)} {k}" for c, k in sorted(v["by_category"].items(), key=lambda x: -x[1]))
        return tr(lang, "p_delays", holds=v["holds"], cats=cats)
    if intent == "rate":
        items = "; ".join(tr(lang, "p_rate_item", unit=u, per_day=x["per_day"]) for u, x in v.items())
        return tr(lang, "p_rate", items=items, as_of=as_of)
    if intent == "late":
        s, f = v["started_late"], v["finished_late"]
        return tr(lang, "p_late", s=len(s), sl=", ".join(s[:5]) or "-", f=len(f), fl=", ".join(f[:5]) or "-")
    if intent == "count":
        by = ", ".join(f"{word(lang, 'st', k)} {n}" for k, n in v["by_status"].items())
        return tr(lang, "p_count", count=v["count"], by_status=by)
    if intent == "status":
        return tr(lang, "p_status", items="; ".join(f"{c}: {word(lang, 'st', st)}" for c, st in list(v.items())[:10]))
    if intent == "freshness":
        last = ", ".join(f"{g} {d}" for g, d in v["last_report"].items())
        return tr(lang, "p_fresh", silent=v["silent_activities"], last=last)
    return tr(lang, "in_english") + out["answer"]           # narrative retrieval: cited source text stays as written


def ask(session: Session, project: Project, question: str, ctx: ProjectContext, as_of: date, lang: str | None = None) -> dict:
    lang = detect(question) or lang_of(lang)
    topic = classify(question)
    low = question.lower()
    if topic == "company":
        body = _company_answer(low, lang)
    elif topic == "app":
        body = _app_answer(low, lang)
    elif topic == "project":
        out = qa.answer(session, project, _english_question(question), ctx, as_of)
        body = {"answer": _localize(out, lang), "sources": [], "citations": out["citations"][:20], "intent": out["intent"]}
    elif topic == "greeting":
        body = {"answer": tr(lang, "greet"), "sources": [], "citations": []}
    else:
        body = {"answer": tr(lang, "refuse"), "sources": [], "citations": []}
    return {"question": question, "lang": lang, "topic": topic or "out_of_scope", **body}
