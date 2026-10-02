"""Cross-source date-conflict layer (Phase 3.1): runs after the link decisions, before an automatic match is accepted.

Two sources that both describe the same activity but date the same fact differently must not be resolved silently:
the affected automatic matches go to REVIEW, both source records stay untouched (Phase 2 rows are never modified) and the
conflict is stored machine-readably on `event_link.conflict`.

Only events linked to the same L5/L6 activity (auto-matched, planner-confirmed, or matched-then-routed here) take part.
Rules, each needing reports from DIFFERENT source documents, and ignoring reports without a date:
  milestone_date               the activity's actual start (or actual finish) is reported with different dates
  work_after_reported_finish   progress/start dated after a finish reported by another document
  work_before_reported_start   progress dated before a start reported by another document
  quantity_date_shift          two source streams (the DPR series of a discipline group; each spreadsheet) report the same
                               unit of work for the activity, both cover days d and d±N (N = conflict_date_shift_days), and
                               one has more on d while the other has more on d±N: the same work dated differently
Identical dates, missing dates and two records of the same document are never cross-source conflicts.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import EventLink, PlanNode, ProgressEvent, Project, SourceDocument

CONFLICT_TYPE = "cross_source_date_conflict"


@dataclass(frozen=True)
class Report:
    event_id: int
    document_id: int
    stream: tuple                # ("dpr_text", discipline group) | ("spreadsheet", document id)
    event_type: str | None
    day: date | None
    quantity: float | None
    unit: str | None


def find_conflicts(reports: list[Report], covers, shift_days: int) -> list[dict]:
    """Pure rule evaluation for ONE activity. covers(stream, day) -> bool says whether a stream reported on that day at all.
    -> findings [{"rule", "detail", "event_ids"}], deterministic order."""
    dated = [r for r in reports if r.day is not None]
    findings = []
    for et in ("start", "finish"):
        ms = [r for r in dated if r.event_type == et]
        if len({r.day for r in ms}) > 1 and len({r.document_id for r in ms}) > 1:
            findings.append({"rule": "milestone_date", "detail": f"actual {et} reported as {', '.join(sorted({str(r.day) for r in ms}))}",
                             "event_ids": sorted(r.event_id for r in ms)})
    for f in (r for r in dated if r.event_type == "finish"):
        late = [r for r in dated if r.event_type in ("progress", "start") and r.day > f.day and r.document_id != f.document_id]
        if late:
            findings.append({"rule": "work_after_reported_finish",
                             "detail": f"work dated {', '.join(sorted({str(r.day) for r in late}))} after finish reported for {f.day}",
                             "event_ids": sorted([f.event_id] + [r.event_id for r in late])})
    for s in (r for r in dated if r.event_type == "start"):
        early = [r for r in dated if r.event_type == "progress" and r.day < s.day and r.document_id != s.document_id]
        if early:
            findings.append({"rule": "work_before_reported_start",
                             "detail": f"work dated {', '.join(sorted({str(r.day) for r in early}))} before start reported for {s.day}",
                             "event_ids": sorted([s.event_id] + [r.event_id for r in early])})
    qty = [r for r in dated if r.event_type == "progress" and r.quantity and r.unit]
    for unit in sorted({r.unit for r in qty}):
        by_stream: dict[tuple, dict[date, list[Report]]] = defaultdict(lambda: defaultdict(list))
        for r in qty:
            if r.unit == unit:
                by_stream[r.stream][r.day].append(r)
        streams = sorted(by_stream)
        for i, a in enumerate(streams):
            for b in streams[i + 1:]:
                days = sorted(set(by_stream[a]) | set(by_stream[b]))
                total = lambda s, d: sum(r.quantity for r in by_stream[s].get(d, []))
                diff = {d: total(a, d) - total(b, d) for d in days if covers(a, d) and covers(b, d)}
                for d, x in sorted(diff.items()):
                    if x <= 0:
                        continue
                    for d2, y in sorted(diff.items()):
                        if y < 0 and 0 < abs((d2 - d).days) <= shift_days:
                            ids = [r.event_id for r in by_stream[a].get(d, [])] + [r.event_id for r in by_stream[b].get(d2, [])]
                            findings.append({"rule": "quantity_date_shift",
                                             "detail": f"{unit}: one source reports the work on {d}, the other on {d2}",
                                             "event_ids": sorted(ids)})
    return findings


def _coverage(session: Session, project: Project):
    """Which days each stream reported on: a DPR series covers its report dates; a spreadsheet covers up to its as-of date."""
    dpr_days: dict[tuple, set] = defaultdict(set)
    sheet_upto: dict[tuple, date | None] = {}
    for d in session.scalars(select(SourceDocument).where(SourceDocument.project_id == project.id, SourceDocument.status == "extracted")):
        if d.kind == "dpr_text" and d.report_date:
            dpr_days[("dpr_text", d.discipline_group or "")].add(d.report_date)   # "" = no group (e.g. Time Agent)
        elif d.kind == "spreadsheet":
            sheet_upto[("spreadsheet", d.id)] = d.report_date

    def covers(stream: tuple, day: date) -> bool:
        if stream[0] == "dpr_text":
            return day in dpr_days[stream]
        upto = sheet_upto.get(stream)
        return upto is None or day <= upto       # no as-of date: the sheet is taken to cover every day it lists
    return covers


def stream_of(ev: ProgressEvent) -> tuple:
    doc = ev.document
    return ("dpr_text", doc.discipline_group or "") if doc.kind == "dpr_text" else (doc.kind, doc.id)


def apply_conflicts(session: Session, project: Project, shift_days: int) -> dict:
    """Recompute conflicts for the whole project and route/restore links. Deterministic and idempotent.
    auto match in conflict -> REVIEW (pending), activity kept in `conflict`; conflict gone -> the automatic match is restored;
    planner-confirmed links keep their decision and only carry the current conflict information."""
    links = session.scalars(select(EventLink).options(selectinload(EventLink.event).selectinload(ProgressEvent.document))
                            .where(EventLink.project_id == project.id, EventLink.state != "rejected")
                            .order_by(EventLink.progress_event_id)).all()

    def activity(l: EventLink) -> int | None:
        if l.plan_node_id is not None:
            return l.plan_node_id
        return l.conflict["plan_node_id"] if l.conflict and l.state == "pending" else None

    groups: dict[int, list[EventLink]] = defaultdict(list)
    for l in links:
        if (node := activity(l)) is not None:
            groups[node].append(l)
    covers = _coverage(session, project)
    codes = dict(session.execute(select(PlanNode.id, PlanNode.code).where(PlanNode.id.in_(list(groups)))).all()) if groups else {}
    counts = {"activities_in_conflict": 0, "events_in_conflict": 0, "routed_to_review": 0, "restored_auto_match": 0}
    for node, group in sorted(groups.items()):
        by_event = {l.progress_event_id: l for l in group}
        reports = [Report(l.event.id, l.event.source_document_id, stream_of(l.event), l.event.event_type, l.event.event_date,
                          l.event.quantity, l.event.unit) for l in group]
        findings = find_conflicts(reports, covers, shift_days)
        counts["activities_in_conflict"] += bool(findings)
        for ev_id, l in by_event.items():
            mine = [f for f in findings if ev_id in f["event_ids"]]
            if mine:
                counts["events_in_conflict"] += 1
                record = _record(node, codes[node], mine, by_event)
                if l.state == "auto":
                    counts["routed_to_review"] += 1
                    l.decision, l.plan_node_id, l.state = "review", None, "pending"
                    l.reasons = [f"{CONFLICT_TYPE}: {f['detail']}" for f in mine] + [r for r in (l.reasons or []) if not r.startswith(CONFLICT_TYPE)]
                if l.conflict != record:
                    l.conflict = record
            elif l.conflict is not None:
                if l.state == "pending":                    # contradiction gone (e.g. other report rejected): restore
                    counts["restored_auto_match"] += 1
                    l.decision, l.plan_node_id, l.state = "matched", l.conflict["plan_node_id"], "auto"
                    l.reasons = [r for r in l.reasons if not r.startswith(CONFLICT_TYPE)]
                l.conflict = None
    session.flush()
    return counts


def _record(node: int, code: str, findings: list[dict], by_event: dict[int, EventLink]) -> dict:
    ids = sorted({e for f in findings for e in f["event_ids"]})
    events = []
    for i in ids:
        ev = by_event[i].event
        events.append({"event_id": ev.id, "document_id": ev.source_document_id, "document": ev.document.filename,
                       "source_type": ev.document.kind, "event_type": ev.event_type,
                       "event_date": ev.event_date.isoformat() if ev.event_date else None, "quantity": ev.quantity,
                       "unit": ev.unit, "source_text": ev.source_text})
    return {"type": CONFLICT_TYPE, "plan_node_id": node, "plan_node_code": code, "base_decision": "matched",
            "dates": sorted({e["event_date"] for e in events if e["event_date"]}),
            "findings": [{"rule": f["rule"], "detail": f["detail"], "event_ids": f["event_ids"]} for f in findings],
            "events": events}
