"""Text Time Agent (Phase 4): supervisor message -> structured progress event -> the EXISTING Phase 3 linker.

The agent only interprets text. It never chooses an activity (the linker does), never writes the schedule, and never
invents a value: every field must be literally present in the message (or in an explicit clarification answer).
Interpreters:
  rules (default, deterministic): Phase 2 glossary event verbs + date/time/tag/area parsers
  LLM (optional, the self-hosted endpoint from P2E_LLM_ENDPOINT): JSON validated against the message; rejected -> rules
Relative dates resolve against one supplied reference datetime (the API sets it once per request).
The message is stored as a text source document (line 3 = the message verbatim), so the event keeps the normal
evidence / conflict / audit trail of every other field report.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from p2e.db.models import DISCIPLINES, ExtractionRun, PlanNode, ProgressEvent, Project
from p2e.extract.model import ExtractedItem
from p2e.extract.pipeline import load_project_vocab, validate_item
from p2e.extract.rules import Vocabulary, extract_area, extract_tags, parse_date, parse_time
from p2e.ingest import service as ingest
from p2e.link import service as linking
from p2e.decide import watch
from p2e.link.context import ProjectContext, get_context

AGENT_EXTRACTOR = "time-agent"
AGENT_VERSION = "1.0.0"
MESSAGE_LINE = 3
UNITS = {"spool": "spools", "spools": "spools", "cable": "cables", "cables": "cables", "ring": "rings", "rings": "rings",
         "cum": "cum", "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m"}
DISCIPLINE_WORDS = {"civil": "civil", "piping": "piping", "electrical": "electrical", "instrumentation": "instrumentation",
                    "hse": "hse"}
RELATIVE = {"today": 0, "yesterday": 1, "yday": 1}
TIME_RES = [re.compile(r"\b(?:at|from|@)?\s*\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b"),
            re.compile(r"\b(?:at|from|@)\s*\d{1,2}[:.]\d{2}\b"), re.compile(r"\b\d{1,2}:\d{2}\b")]
DATE_RE = re.compile(r"\b(?:on\s+)?(\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?"
                     r"|\d{1,2}(?:st|nd|rd|th)?[- ][a-z]{3,4}(?:[- ]\d{2,4})?|[a-z]{3,4} \d{1,2},? \d{4})\b")
REL_RE = re.compile(r"\b(today|yesterday|yday)\b")
QTY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b")
CHECKLIST_RE = re.compile(r"^\s*(?:checklist|what (?:should|do|must) i report(?: today)?)\s*\??\s*$", re.IGNORECASE)
EDGE_WORDS = {"on", "at", "for", "of", "in", "and", "the", "is", "was", "has", "been", "from", "by"}


@dataclass
class Raw:
    """What the message literally says (before resolution)."""
    activity_text: str
    event_types: list[str]
    date_texts: list[str]
    time_text: str | None = None
    quantity: float | None = None
    unit: str | None = None
    disciplines: list[str] = field(default_factory=list)
    provider: str = "rules"
    confidence: float = 1.0
    notes: list[str] = field(default_factory=list)


@dataclass
class Interpretation:
    activity_text: str
    event_type: str | None
    event_date: date | None
    date_text: str | None
    event_time: str | None
    quantity: float | None
    unit: str | None
    discipline: str | None
    area: str | None
    tags: list[str]
    provider: str
    confidence: float
    notes: list[str]
    missing: list[str]
    question: str | None

    def public(self) -> dict:
        return {"activity_text": self.activity_text, "event_type": self.event_type,
                "actual_start": self.event_date if self.event_type == "start" else None,
                "actual_finish": self.event_date if self.event_type == "finish" else None,
                "event_date": self.event_date, "date_text": self.date_text, "event_time": self.event_time,
                "quantity": self.quantity, "unit": self.unit, "discipline": self.discipline, "area": self.area,
                "tags": self.tags, "interpreted_by": self.provider, "extraction_confidence": self.confidence,
                "notes": self.notes, "missing": self.missing}


# ----------------------------------------------------------------------------- interpreters

def interpret_rules(message: str, vocab: Vocabulary) -> Raw:
    low = message.lower()
    taken: list[tuple[int, int]] = []

    def free(a, b):
        return not any(a < y and x < b for x, y in taken)

    types = []
    for phrase in sorted(vocab.verbs, key=len, reverse=True):
        for m in re.finditer(rf"(?<![a-z]){re.escape(phrase.lower())}(?![a-z])", low):
            if free(*m.span()):
                taken.append(m.span())
                types.append(vocab.verbs[phrase])
    time_text = None
    for pat in TIME_RES:
        for m in pat.finditer(low):
            if free(*m.span()):
                taken.append(m.span())
                time_text = time_text or message[m.start():m.end()].strip()
    dates = []
    for pat in (REL_RE, DATE_RE):
        for m in pat.finditer(low):
            if free(*m.span()) and (pat is REL_RE or parse_date(m.group(1), date(2000, 1, 1))):
                taken.append(m.span())
                dates.append(message[m.start(1):m.end(1)])
    qty = unit = None
    ids = {re.sub(r"\D", "", t) for t in extract_tags(message)}          # "Line 1211 spool": 1211 is a line, not a count
    for m in QTY_RE.finditer(low):
        if free(*m.span()) and m.group(1) not in ids:
            taken.append(m.span())
            qty, unit = float(m.group(1)), UNITS[m.group(2)]
            break
    disc = sorted({DISCIPLINE_WORDS[w] for w in re.findall(r"[a-z]+", low) if w in DISCIPLINE_WORDS})
    return Raw(_activity(message, taken), sorted(set(types)), dates, time_text, qty, unit, disc)


def _activity(message: str, taken: list[tuple[int, int]]) -> str:
    """Longest stretch of the message not used by another field, trimmed: always a verbatim substring."""
    cuts = sorted(taken)
    pieces, pos = [], 0
    for a, b in cuts + [(len(message), len(message))]:
        if a > pos:
            pieces.append((pos, a))
        pos = max(pos, b)
    best = ""
    for a, b in pieces:
        s = message[a:b]
        while True:
            t = s.strip(" .,;:-–—!?\t")
            words = t.split()
            if words and words[0].lower() in EDGE_WORDS:
                t = t[len(words[0]):]
            elif words and words[-1].lower() in EDGE_WORDS:
                t = t[: len(t) - len(words[-1])]
            if t == s:
                break
            s = t
        if len(s) > len(best):
            best = s
    return best


class LlmEvent(BaseModel):
    """The only shape accepted from an LLM; every text field is checked against the message afterwards."""
    model_config = ConfigDict(extra="forbid")
    activity_text: str = Field(min_length=1, max_length=300)
    event_type: Literal["start", "finish", "progress", "hold", "resume"] | None = None
    date_text: str | None = Field(None, max_length=40)
    time_text: str | None = Field(None, max_length=20)
    quantity: float | None = Field(None, gt=0)
    unit: str | None = None
    discipline_text: str | None = None
    confidence: float = Field(ge=0, le=1)


def interpret_llm(model, ctx: ProjectContext, message: str) -> tuple[Raw | None, str | None]:
    prompt = (ctx.prompt_prefix() +
              f"\nTASK: read one site supervisor message and copy fields VERBATIM from it. Never add information.\n"
              f"MESSAGE: {message}\n"
              'Answer with JSON only: {"activity_text": "...", "event_type": "start|finish|progress|hold|resume|null", '
              '"date_text": "... or null", "time_text": "... or null", "quantity": null, "unit": null, '
              '"discipline_text": null, "confidence": 0.0}\n')
    try:
        out = model.invoke(prompt)
        text = getattr(out, "content", out)
        ev = LlmEvent.model_validate(json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0)))
    except (ValidationError, ValueError, AttributeError, TypeError) as e:
        return None, f"llm output rejected: {type(e).__name__}"
    except Exception as e:                              # model/network failure: fall back, never fail the request
        return None, f"llm unavailable: {type(e).__name__}"
    low = message.lower()
    for name, val in (("activity_text", ev.activity_text), ("date_text", ev.date_text), ("time_text", ev.time_text),
                      ("discipline_text", ev.discipline_text)):
        if val is not None and val.lower() not in low:
            return None, f"llm output rejected: {name} not in the message"
    if ev.activity_text not in message:
        return None, "llm output rejected: activity_text not verbatim"
    if ev.quantity is not None and not re.search(rf"(?<![\d.]){ev.quantity:g}(?![\d.])", message):
        return None, "llm output rejected: quantity not in the message"
    if ev.unit is not None and (ev.unit.lower() not in UNITS or ev.quantity is None):
        return None, "llm output rejected: unit"
    if ev.date_text is not None and not (ev.date_text.lower() in RELATIVE or parse_date(ev.date_text, date(2000, 1, 1))):
        return None, "llm output rejected: date_text is not a date"
    disc = [DISCIPLINE_WORDS[ev.discipline_text.lower()]] if ev.discipline_text and ev.discipline_text.lower() in DISCIPLINE_WORDS else []
    if ev.discipline_text and not disc:
        return None, "llm output rejected: discipline"
    return Raw(ev.activity_text, [ev.event_type] if ev.event_type else [], [ev.date_text] if ev.date_text else [],
               ev.time_text, ev.quantity, UNITS[ev.unit.lower()] if ev.unit else None, disc, "llm", ev.confidence), None


# ----------------------------------------------------------------------------- resolution + clarification

def resolve_date(text: str, ref: date) -> date | None:
    t = text.strip().lower()
    if t in RELATIVE:
        return ref - timedelta(days=RELATIVE[t])
    return parse_date(re.sub(r"^on\s+", "", t), ref)


def finalize(raw: Raw, ctx: ProjectContext, ref: datetime, discipline: str | None, answers: dict) -> Interpretation:
    missing, questions = [], []
    words = ctx.content_words(ctx.normalize(raw.activity_text)) if raw.activity_text else []
    tags = extract_tags(raw.activity_text) if raw.activity_text else []
    if not words and not tags:
        missing.append("activity")
        questions.append("Which activity was it? Please resend the message with the line, equipment or area "
                         "(for example 'Line 1203 erection started today').")
    event_type = raw.event_types[0] if len(raw.event_types) == 1 else ("progress" if not raw.event_types and raw.quantity else None)
    if event_type is None:
        missing.append("event_type")
        questions.append("The message reports more than one status; please send one message per status." if raw.event_types
                         else "Did the work start, finish or is it in progress? Please resend the message with that word.")
    dates = {d for d in (resolve_date(t, ref.date()) for t in raw.date_texts) if d}
    date_text = raw.date_texts[0] if len(dates) == 1 else None
    if not dates and answers.get("date"):
        d = resolve_date(answers["date"], ref.date())
        dates, date_text = ({d}, answers["date"]) if d else (set(), None)
    if len(dates) != 1:
        missing.append("date")
        verb = {"start": "started", "finish": "completed"}.get(event_type or "", "done")
        questions.append(f"The message mentions more than one date ({', '.join(raw.date_texts)}); please resend it with one date."
                         if len(dates) > 1 else f"What date was it {verb}? (for example 'today', 'yesterday' or 2026-09-24)")
    disc = raw.disciplines[0] if len(raw.disciplines) == 1 else (discipline or answers.get("discipline"))
    if len(raw.disciplines) > 1 or disc not in DISCIPLINES:
        missing.append("discipline")
        questions.append("Which discipline is this (civil, piping, electrical, instrumentation, hse)?")
    piping = disc == "piping"
    return Interpretation(
        activity_text=raw.activity_text, event_type=event_type, event_date=next(iter(dates)) if len(dates) == 1 else None,
        date_text=date_text, event_time=parse_time(re.sub(r"^(?:at|from|@)\s*", "", raw.time_text.lower())) if raw.time_text else None,
        quantity=raw.quantity, unit=raw.unit, discipline=disc if disc in DISCIPLINES else None,
        area=extract_area(raw.activity_text), tags=extract_tags(raw.activity_text, piping_context=piping) if raw.activity_text else [],
        provider=raw.provider, confidence=raw.confidence, notes=raw.notes, missing=missing,
        question=" ".join(questions) or None)


# ----------------------------------------------------------------------------- record + link

def handle(session: Session, project: Project, message: str, ref: datetime, role: str, upload_dir: Path, glossary_path: Path,
           llm=None, discipline: str | None = None, answers: dict | None = None, allowed_discipline: str | None = None) -> dict:
    """One supervisor turn. Returns {status, reply, question, interpretation, event_id, document_id, link_event_id}.
    status: needs_clarification | rejected (nothing stored) | recorded | duplicate."""
    answers = {k: v for k, v in (answers or {}).items() if v}
    if CHECKLIST_RE.match(message):                     # "what should I report today?" -> silent-activity checklist
        return checklist_reply(session, project, ref, discipline or answers.get("discipline"))
    ctx = get_context(session, project, glossary_path)
    raw, note = interpret_llm(llm, ctx, message) if llm is not None else (None, None)
    raw = raw or interpret_rules(message, load_project_vocab(glossary_path).vocab)
    if note:
        raw.notes.append(note)
    it = finalize(raw, ctx, ref, discipline, answers)
    out = {"interpretation": it.public(), "question": it.question, "event_id": None, "document_id": None}
    if it.missing:
        return out | {"status": "needs_clarification", "reply": it.question}
    if allowed_discipline and it.discipline != allowed_discipline:      # discipline-scoped supervisor key
        return out | {"status": "rejected", "reply": f"Not recorded: this key may only log {allowed_discipline} progress "
                                                     f"(the message reports {it.discipline})."}
    content = _record_text(message, ref, role, it, answers)
    lines = content.split("\n")
    item = ExtractedItem(source_ref={"line": MESSAGE_LINE, "index": 0}, source_text=message, activity_text=it.activity_text,
                         event_type=it.event_type, event_date=it.event_date, date_text=it.date_text, event_time=it.event_time,
                         quantity=it.quantity, unit=it.unit, discipline=it.discipline, area=it.area, tags=it.tags,
                         span=(0, len(message)))
    project_start = session.scalar(select(func.min(PlanNode.planned_start)).where(PlanNode.project_id == project.id))
    errors = validate_item(item, lines=lines, report_date=ref.date(), project_start=project_start)   # Phase 2 rules
    if errors:
        return out | {"status": "rejected", "reply": "Not recorded: " + "; ".join(errors) + ". Please correct and resend."}
    data = content.encode("utf-8")
    try:
        doc = ingest.ingest_upload(session, project, f"time-agent-{hashlib.sha256(data).hexdigest()[:12]}.txt", data, role, upload_dir)
    except ingest.DuplicateDocument as e:              # the same message, reference time and answers were already recorded
        ev = session.scalar(select(ProgressEvent).where(ProgressEvent.source_document_id == e.extra["existing_document_id"]))
        return out | {"status": "duplicate", "reply": "Already recorded.", "event_id": ev.id if ev else None,
                      "document_id": e.extra["existing_document_id"]}
    run = ExtractionRun(document=doc, extractor=AGENT_EXTRACTOR, parser_version=AGENT_VERSION, status="succeeded",
                        events_total=1, events_valid=1, finished_at=datetime.now().astimezone())
    ev = ProgressEvent(project_id=project.id, document=doc, extraction_run=run, locator_key=item.locator_key,
                       source_ref=item.source_ref, source_text=message, span_start=0, span_end=len(message),
                       report_date=ref.date(), discipline=it.discipline, activity_text=it.activity_text, event_type=it.event_type,
                       event_date=it.event_date, date_text=it.date_text, event_time=it.event_time, quantity=it.quantity,
                       unit=it.unit, area=it.area, tags=it.tags, extraction_method=AGENT_EXTRACTOR, parser_version=AGENT_VERSION,
                       validation_status="valid", validation_errors=[])
    session.add_all([run, ev])
    doc.status, doc.report_date = "extracted", ref.date()
    session.flush()
    linking.link_events(session, project, glossary_path, event_ids=[ev.id], llm=llm)    # the existing Phase 3 linker
    link = linking.get_link(session, project, ev.id)
    return out | {"status": "recorded", "reply": reply_for(link), "event_id": ev.id, "document_id": doc.id}


def checklist_reply(session: Session, project: Project, ref: datetime, discipline: str | None) -> dict:
    base = {"interpretation": {}, "event_id": None, "document_id": None}
    if discipline not in DISCIPLINES:
        q = "Which discipline is this (civil, piping, electrical, instrumentation, hse)?"
        return base | {"status": "needs_clarification", "reply": q, "question": q}
    items = watch.checklist(session, project, ref.date(), discipline)
    done = sum(i["reported_today"] for i in items)
    reply = (f"{len(items)} {discipline} activities are expected to be active today; {done} already reported."
             + (" Not reported yet: " + "; ".join(f"{i['plan_node_code']} {i['activity_name']}" for i in items if not i["reported_today"])[:600]
                if done < len(items) else ""))
    return base | {"status": "checklist", "reply": reply, "question": None,
                   "checklist": [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in i.items()} for i in items]}


def reply_for(link) -> str:
    if link.decision == "matched":
        return f"Recorded and linked to {link.node.code} ({link.node.name})."
    if link.decision == "review":
        return "Recorded, but planner review is required."
    return "Recorded, but it could not be safely linked to an existing activity."


def _record_text(message: str, ref: datetime, role: str, it: Interpretation, answers: dict) -> str:
    """The stored source document: line 3 is the supervisor message verbatim (the event's evidence span)."""
    meta = {"interpreted_by": it.provider, "agent_version": AGENT_VERSION, "extraction_confidence": it.confidence,
            "notes": it.notes, "answers": answers}
    return (f"P2E Time Agent message\nreceived: {ref.isoformat()} | role: {role}\n{message}\n"
            f"interpretation: {json.dumps(meta, sort_keys=True, ensure_ascii=False)}\n")
