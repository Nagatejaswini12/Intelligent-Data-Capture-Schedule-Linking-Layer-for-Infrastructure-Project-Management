"""Institutional-memory Q&A (Phase 6): a plain-language question -> a FIXED query template over the recorded history -> an
answer whose numbers all come from cited records. No free-form SQL, no LLM (none is configured on-premise); anything the
templates do not cover falls back to retrieval over knowledge entries and field report text (the RAG step), cited too.

Templates: duration (how long did X take), delays (what delayed X), rate (X per day), late (which X started/finished
late), count (how many X are completed / in progress / not started), status (status of an activity or tag),
freshness (when did each discipline last report / what has gone silent).
Filters read from the question: discipline, area, work action (CAG action lexicon), tags (P-101A, line 1405), pipe size
(24-inch), and "as of / by <date>". An empty result says so instead of guessing.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from p2e.analytics import metrics
from p2e.db.models import ProgressEvent, Project, SourceDocument
from p2e.decide import watch
from p2e.extract.rules import extract_tags, parse_date
from p2e.link.context import AREA_RE, ProjectContext
from p2e.link.retrieve import ScheduleIndex
from p2e.memory import knowledge

DISCIPLINE_WORDS = {"civil": ["civil"], "piping": ["piping"], "electrical": ["electrical"], "instrumentation": ["instrumentation"],
                    "instrument": ["instrumentation"], "hse": ["hse"], "mechanical": ["static_eq", "rotating_eq"],
                    "static": ["static_eq"], "rotating": ["rotating_eq"]}
INTENTS = [
    ("freshness", re.compile(r"not reported|last report|silent|freshness|stopped reporting|who has(?:n't| not) reported")),
    ("delays", re.compile(r"\b(?:delay|delays|delayed|hold|holds|held|stopped|stuck|why)\b")),
    ("rate", re.compile(r"per day|a day\b|daily rate|productivity|rate of")),
    ("duration", re.compile(r"how long|duration|\btake\b|\btook\b")),
    ("late", re.compile(r"\blate\b|behind|slipp|overdue")),
    ("count", re.compile(r"how many|number of")),
    ("status", re.compile(r"\bstatus\b|how far|percent|progress of|where are we")),
]
AS_OF_RE = re.compile(r"\b(?:as of|by|on|until|till)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2}[- ][a-z]{3,4}(?:[- ]\d{2,4})?)")
SIZE_RE = re.compile(r"\b(\d{1,2})\s*(?:-?\s*inch|in\b|\")")
MAX_LIST = 20
QUESTION_WORDS = set("""what which when where who whom whose why how many much long take took did does were have has been this
that there their delay delays delayed hold holds held stopped stuck started finished completed complete late behind status
progress report reported last each discipline disciplines project site activities activity work works per day days rate
number tell about show list give since until today yesterday overall total average actually problems problem issues issue
reason reasons cause causes caused were from with into done finish start still yet happen happened most least currently
date dates""".split())


@dataclass
class Filters:
    as_of: date
    disciplines: list[str] = field(default_factory=list)
    area: str | None = None
    actions: set[str] = field(default_factory=set)
    tags: list[str] = field(default_factory=list)
    size: str | None = None

    def public(self) -> dict:
        return {"as_of": self.as_of, "disciplines": self.disciplines, "area": self.area, "actions": sorted(self.actions),
                "tags": self.tags, "size": self.size}


def parse(question: str, ctx: ProjectContext, as_of: date) -> Filters:
    low = question.lower()
    if m := AS_OF_RE.search(low):
        as_of = parse_date(m.group(1), as_of) or as_of
    discs = sorted({d for w in re.findall(r"[a-z]+", low) for d in DISCIPLINE_WORDS.get(w, [])})
    area = f"A{m.group(1)}" if (m := AREA_RE.search(low)) else None
    norm = ctx.normalize(question)
    singular = re.sub(r"\b([a-z]{4,}?)s\b", r"\1", norm)              # hydrotests -> hydrotest
    actions = set(ctx.actions_in(norm)) | set(ctx.actions_in(singular))
    tags = [t for t in extract_tags(question) if not re.fullmatch(r"LINE-\d{4}", t) or re.search(r"line|l-?\d{4}", low)]
    size = m.group(1) if (m := SIZE_RE.search(low)) else None
    return Filters(as_of, discs, area, actions, tags, size)


def _node_ok(f: Filters, row: dict, node) -> bool:
    if f.disciplines and row["discipline"] not in f.disciplines:
        return False
    if f.area and row["area"] != f.area:
        return False
    if f.size and f'{f.size}"' not in row["name"]:
        return False
    if f.tags and not set(f.tags) & set(row["_tags"]) and not set(f.tags) & set(node.tags):
        return False
    return not f.actions or bool(f.actions & node.actions)


def answer(session: Session, project: Project, question: str, ctx: ProjectContext, as_of: date) -> dict:
    f = parse(question, ctx, as_of)
    low = question.lower()
    intent = next((name for name, rx in INTENTS if rx.search(low)), "status" if f.tags else "narrative")
    index = ScheduleIndex.build(session, project, ctx)
    nodes = {n.code: n for n in index.nodes}
    rows = [r for r in metrics.dataset(session, project, f.as_of) if r["code"] in nodes]
    narrowed = bool(f.disciplines or f.area or f.actions or f.tags or f.size)
    matched = [r for r in rows if _node_ok(f, r, nodes[r["code"]])] if narrowed else rows
    unknown = [w for w in re.findall(r"[a-z]{4,}", low) if w not in QUESTION_WORDS and w not in index.idf
               and w not in DISCIPLINE_WORDS and not ctx.actions_in(w)]
    if unknown and not narrowed and intent not in ("narrative", "freshness"):
        return {"question": question, "intent": intent, "filters": f.public(), "values": {}, "citations": [],
                "answer": f"I could not find '{' '.join(unknown)}' in the schedule; name an activity, tag, line, discipline or area."}
    handler = {"duration": _duration, "delays": _delays, "rate": _rate, "late": _late, "count": _count, "status": _status,
               "freshness": _freshness, "narrative": _narrative}[intent]
    out = handler(session, project, f, matched, low, ctx, nodes)
    if not out["citations"]:
        out["answer"] = out.get("answer") or "No matching records in the project history."
    return {"question": question, "intent": intent, "filters": f.public()} | out


def _cite_rows(rows) -> list[dict]:
    return [{"kind": "activity", "id": r["code"], "text": r["name"],
             "date": f"{r['actual_start'] or '-'}..{r['actual_finish'] or '-'}"} for r in rows]


def _duration(session, project, f, rows, low, ctx, nodes):
    done = [r for r in rows if r["actual_duration_days"]]
    if not done:
        return {"answer": "No completed activity matches the question.", "values": {}, "citations": []}
    mean = round(sum(r["actual_duration_days"] for r in done) / len(done), 2)
    plan = round(sum(r["planned_duration_days"] for r in done) / len(done), 2)
    lo, hi = min(r["actual_duration_days"] for r in done), max(r["actual_duration_days"] for r in done)
    return {"answer": f"{len(done)} completed activities took {mean} days on average (range {lo}-{hi}) against {plan} days "
                      f"planned, as of {f.as_of}.",
            "values": {"n": len(done), "mean_actual_days": mean, "mean_planned_days": plan, "min_days": lo, "max_days": hi},
            "citations": _cite_rows(done)}


def _delays(session, project, f, rows, low, ctx, nodes):
    keep = {r["code"] for r in rows}
    narrowed = bool(f.disciplines or f.area or f.actions or f.tags or f.size)
    found = []
    for e, n in metrics.delay_events(session, project):
        if not e.event_date or e.event_date > f.as_of:
            continue
        if narrowed:
            if n is not None and n.code not in keep:
                continue
            if n is None:                                       # unlinked report: judge it by its own fields
                if (f.disciplines and e.discipline not in f.disciplines) or (f.area and e.area != f.area) or f.tags \
                        or (f.actions and not f.actions & set(ctx.actions_in(ctx.normalize(e.activity_text)))):
                    continue
        found.append((e, n))
    cats = Counter(e.delay_category for e, _ in found)
    reasons = {c: sorted({e.delay_reason for e, _ in found if e.delay_category == c}) for c in cats}
    text = "; ".join(f"{c} {k}x ({', '.join(reasons[c])})" for c, k in cats.most_common())
    return {"answer": f"{len(found)} hold reports: {text}." if found else "No delay was reported for this scope.",
            "values": {"holds": len(found), "by_category": dict(sorted(cats.items()))},
            "citations": [{"kind": "event", "id": e.id, "text": e.source_text, "date": str(e.event_date),
                           "activity": n.code if n else None} for e, n in found]}


def _rate(session, project, f, rows, low, ctx, nodes):
    rates = metrics.quantity_rate(session, project, [r["_id"] for r in rows], f.as_of) if rows else {}
    if not rates:
        return {"answer": "No reported quantities match the question.", "values": {}, "citations": []}
    text = "; ".join(f"{v['per_day']} {u}/day ({v['quantity']:g} {u} over {v['days']} reporting days)" for u, v in sorted(rates.items()))
    ids = sorted({i for v in rates.values() for i in v["event_ids"]})
    return {"answer": f"{text}, as of {f.as_of}.", "values": {u: {k: v[k] for k in ("quantity", "days", "per_day")} for u, v in rates.items()},
            "citations": [{"kind": "event", "id": i, "text": session.get(ProgressEvent, i).source_text,
                           "date": str(session.get(ProgressEvent, i).event_date)} for i in ids]}


def _late(session, project, f, rows, low, ctx, nodes):
    want_start = "start" in low or "finish" not in low
    want_finish = "finish" in low or "complet" in low or "start" not in low
    started = [r for r in rows if want_start and (r["start_variance_days"] or 0) > 0]
    finished = [r for r in rows if want_finish and (r["finish_variance_days"] or 0) > 0]
    cited = {r["code"]: r for r in started + finished}
    parts = ([f"{len(started)} started late"] if want_start else []) + ([f"{len(finished)} finished late"] if want_finish else [])
    worst = sorted(cited.values(), key=lambda r: -max(r["start_variance_days"] or 0, r["finish_variance_days"] or 0))[:5]
    tail = ", ".join(f"{r['code']} (+{max(r['start_variance_days'] or 0, r['finish_variance_days'] or 0)} d)" for r in worst)
    return {"answer": f"{' and '.join(parts)} as of {f.as_of}" + (f"; largest: {tail}." if tail else "."),
            "values": {"started_late": sorted(r["code"] for r in started), "finished_late": sorted(r["code"] for r in finished)},
            "citations": _cite_rows(sorted(cited.values(), key=lambda r: r["code"]))}


def _count(session, project, f, rows, low, ctx, nodes):
    counts = Counter(r["status"] for r in rows)
    want = ("not_started" if re.search(r"not (?:yet )?started|pending", low) else
            "completed" if re.search(r"complet|finish|done", low) else
            "in_progress" if re.search(r"in progress|ongoing|started|running", low) else None)
    cited = [r for r in rows if want is None or r["status"] == want]
    head = f"{counts[want]} {want.replace('_', ' ')}" if want else f"{len(rows)} activities"
    return {"answer": f"{head} as of {f.as_of} (completed {counts['completed']}, in progress {counts['in_progress']}, "
                      f"not started {counts['not_started']}).",
            "values": {"count": counts[want] if want else len(rows), "by_status": dict(counts)},
            "citations": _cite_rows(cited or rows)}        # a zero count cites the population it was counted over


def _status(session, project, f, rows, low, ctx, nodes):
    if not rows or not (f.tags or f.actions or f.disciplines or f.area):
        return {"answer": "Name an activity, tag or line to get its status.", "values": {}, "citations": []}
    shown = rows[:MAX_LIST]
    lines = [f"{r['code']}: {r['status'].replace('_', ' ')}" + (f", started {r['actual_start']}" if r["actual_start"] else "")
             + (f", finished {r['actual_finish']}" if r["actual_finish"] else "")
             + (f", {r['percent_complete']:g}%" if r["percent_complete"] is not None else "")
             + (f", last report {r['last_reported']}" if r["last_reported"] else "") for r in shown]
    more = f" (+{len(rows) - len(shown)} more)" if len(rows) > len(shown) else ""
    return {"answer": f"As of {f.as_of}: " + "; ".join(lines) + more + ".",
            "values": {r["code"]: r["status"] for r in rows}, "citations": _cite_rows(shown)}


def _freshness(session, project, f, rows, low, ctx, nodes):
    dash = metrics.dashboard(session, project, f.as_of)
    fresh = dash["freshness"]
    if f.disciplines:
        groups = {g for g in fresh if g in f.disciplines or (g == "mechanical" and {"static_eq", "rotating_eq"} & set(f.disciplines))}
        fresh = {g: v for g, v in fresh.items() if g in groups}
    silent = watch.silent_activities(session, project, f.as_of)
    docs = session.scalars(select(SourceDocument).where(SourceDocument.project_id == project.id, SourceDocument.kind == "dpr_text",
                                                        SourceDocument.discipline_group.in_(list(fresh)))).all()
    latest = {g: max((d for d in docs if d.discipline_group == g and d.report_date == v["last_report"]), key=lambda d: d.id)
              for g, v in fresh.items()}
    text = "; ".join(f"{g} last reported {v['last_report']} ({v['days_since']} d ago)" for g, v in fresh.items())
    return {"answer": f"As of {f.as_of}: {text}. {len(silent)} activities expected to be active have no report in "
                      f"{watch.WATCH_DAYS} days.",
            "values": {"last_report": {g: v["last_report"] for g, v in fresh.items()}, "silent_activities": len(silent)},
            "citations": [{"kind": "document", "id": d.id, "text": d.filename, "date": str(d.report_date)} for d in latest.values()]}


def _narrative(session, project, f, rows, low, ctx, nodes):
    """RAG fallback: rank knowledge entries + hold reports by IDF-weighted word overlap with the question."""
    corpus = [(e["text"], e["citations"][:5], e["id"]) for e in knowledge.entries(session, project, f.as_of)]
    corpus += [(e.source_text, [{"kind": "event", "id": e.id, "text": e.source_text, "date": str(e.event_date)}], f"event/{e.id}")
               for e, _ in metrics.delay_events(session, project) if e.event_date and e.event_date <= f.as_of]
    words = lambda t: set(ctx.content_words(ctx.normalize(t)))             # noqa: E731
    docs = [(words(t), t, c, i) for t, c, i in corpus]
    df = Counter(w for ws, *_ in docs for w in ws)
    q = words(low)
    scored = sorted(((sum(math.log(1 + len(docs) / df[w]) for w in q & ws), i, t, c) for ws, t, c, i in docs if q & ws), reverse=True)[:3]
    if not scored:
        return {"answer": "No matching records in the project history.", "values": {}, "citations": []}
    return {"answer": " ".join(t for _, _, t, _ in scored), "values": {"retrieved": [i for _, i, _, _ in scored]},
            "citations": [c for *_, cs in scored for c in cs]}
