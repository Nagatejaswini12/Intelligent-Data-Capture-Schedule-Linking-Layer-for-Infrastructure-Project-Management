"""Phase 6 analytics over the recorded project history (plan_node actuals from import + audited apply, accepted reports).

Everything is computed on demand from the database (no metrics tables) and is deterministic. "As of" a date, an activity is
completed when its actual finish <= as_of, in progress when its actual start <= as_of, otherwise not started.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import EventLink, PlanNode, ProgressEvent, Project, SourceDocument
from p2e.decide import apply as engine
from p2e.decide import watch
from p2e.link.conflicts import stream_of

DATASET_COLUMNS = ["code", "name", "discipline", "area", "activity_type", "level", "planned_start", "planned_finish",
                   "planned_duration_days", "actual_start", "actual_finish", "actual_duration_days", "duration_ratio",
                   "start_variance_days", "finish_variance_days", "status", "percent_complete", "planned_qty", "qty_unit",
                   "reported_qty", "reports", "sources", "last_reported", "delay_categories"]


def status(n: PlanNode, as_of: date) -> str:
    if n.actual_finish and n.actual_finish <= as_of:
        return "completed"
    if n.actual_start and n.actual_start <= as_of:
        return "in_progress"
    return "not_started"


def activities(session: Session, project: Project) -> list[PlanNode]:
    return list(session.scalars(select(PlanNode).options(selectinload(PlanNode.tags))
                                .where(PlanNode.project_id == project.id, PlanNode.node_type == "activity").order_by(PlanNode.seq)))


def delay_events(session: Session, project: Project) -> list[tuple[ProgressEvent, PlanNode | None]]:
    """Every reported hold with a categorised reason (Phase 2 taxonomy), with its linked activity when there is one."""
    links = {l.progress_event_id: l for l in session.scalars(select(EventLink).options(selectinload(EventLink.node))
                                                              .where(EventLink.project_id == project.id))}
    evs = session.scalars(select(ProgressEvent).options(selectinload(ProgressEvent.document))
                          .where(ProgressEvent.project_id == project.id, ProgressEvent.delay_category.is_not(None),
                                 ProgressEvent.validation_status == "valid").order_by(ProgressEvent.event_date, ProgressEvent.id))
    out = []
    for e in evs:
        l = links.get(e.id)
        node = l.node if l is not None and l.state != "rejected" else None
        if node is None and l is not None and l.conflict and l.state == "pending":
            node = session.get(PlanNode, l.conflict["plan_node_id"])
        out.append((e, node))
    return out


def dataset(session: Session, project: Project, as_of: date) -> list[dict]:
    """The actual-progress dataset: one row per executable activity."""
    accepted = engine.accepted_links(session, project, None)
    delays = defaultdict(Counter)
    for e, n in delay_events(session, project):
        if n is not None:
            delays[n.id][e.delay_category] += 1
    rows = []
    for n in activities(session, project):
        evs = [l.event for l in accepted.get(n.id, []) if (l.event.event_date or l.event.report_date) <= as_of]
        start = n.actual_start if n.actual_start and n.actual_start <= as_of else None
        finish = n.actual_finish if n.actual_finish and n.actual_finish <= as_of else None
        dur = (finish - start).days + 1 if start and finish else None
        per_source = defaultdict(float)
        for e in evs:
            if e.event_type == "progress" and e.unit and e.unit == n.qty_unit and e.quantity:
                per_source[stream_of(e)] += e.quantity
        rows.append({"code": n.code, "name": n.name, "discipline": n.discipline, "area": n.area, "activity_type": n.activity_type,
                     "level": n.level, "planned_start": n.planned_start, "planned_finish": n.planned_finish,
                     "planned_duration_days": n.planned_duration_days, "actual_start": start, "actual_finish": finish,
                     "actual_duration_days": dur, "duration_ratio": round(dur / n.planned_duration_days, 3) if dur else None,
                     "start_variance_days": (start - n.planned_start).days if start else None,
                     "finish_variance_days": (finish - n.planned_finish).days if finish else None,
                     "status": status(n, as_of), "percent_complete": n.percent_complete, "planned_qty": n.planned_qty,
                     "qty_unit": n.qty_unit, "reported_qty": max(per_source.values()) if per_source else None,
                     "reports": len(evs), "sources": len({e.source_document_id for e in evs}),
                     "last_reported": max((e.event_date or e.report_date for e in evs), default=None),
                     "delay_categories": ";".join(f"{k}:{v}" for k, v in sorted(delays[n.id].items())),
                     "_tags": [t.tag for t in n.tags], "_id": n.id})
    return rows


def dashboard(session: Session, project: Project, as_of: date) -> dict:
    rows = dataset(session, project, as_of)
    by = {"discipline": defaultdict(Counter), "area": defaultdict(Counter)}
    for r in rows:
        for key in by:
            c = by[key][r[key] or "-"]
            c["activities"] += 1
            c[r["status"]] += 1
            c["started_late"] += (r["start_variance_days"] or 0) > 0
            c["finished_late"] += (r["finish_variance_days"] or 0) > 0
            c["due_not_started"] += r["status"] == "not_started" and r["planned_start"] < as_of
    last_dpr = dict(session.execute(select(SourceDocument.discipline_group, func.max(SourceDocument.report_date))
                                    .where(SourceDocument.project_id == project.id, SourceDocument.kind == "dpr_text",
                                           SourceDocument.discipline_group.is_not(None), SourceDocument.report_date <= as_of)
                                    .group_by(SourceDocument.discipline_group)).all())
    silent = Counter(i["discipline"] for i in watch.silent_activities(session, project, as_of))
    backlog = Counter(session.scalars(select(EventLink.state).where(EventLink.project_id == project.id, EventLink.state == "pending")))
    conflicts = session.scalar(select(func.count()).select_from(EventLink).where(
        EventLink.project_id == project.id, EventLink.state == "pending", EventLink.conflict.is_not(None)))
    blocked = sum(1 for p in engine.propose(session, project, as_of) if p.blockers)
    return {
        "as_of": as_of,
        "by_discipline": {k: dict(v) for k, v in sorted(by["discipline"].items())},
        "by_area": {k: dict(v) for k, v in sorted(by["area"].items())},
        "freshness": {g: {"last_report": d, "days_since": (as_of - d).days} for g, d in sorted(last_dpr.items())},
        "silent_activities_by_discipline": dict(sorted(silent.items())),
        "review_backlog": {"pending_events": backlog["pending"], "pending_conflicts": conflicts, "blocked_activities": blocked},
    }


def productivity(rows: list[dict]) -> dict:
    """Duration ratio per activity type (completed activities) and reported quantity per active day per unit."""
    types = defaultdict(list)
    for r in rows:
        if r["actual_duration_days"]:
            types[r["activity_type"] or "-"].append(r)
    durations = {t: {"completed": len(rs), "mean_actual_days": round(sum(r["actual_duration_days"] for r in rs) / len(rs), 2),
                     "mean_planned_days": round(sum(r["planned_duration_days"] for r in rs) / len(rs), 2),
                     "mean_ratio": round(sum(r["duration_ratio"] for r in rs) / len(rs), 3), "activities": [r["code"] for r in rs]}
                 for t, rs in sorted(types.items())}
    return {"durations": durations}


def quantity_rate(session: Session, project: Project, node_ids: list[int], as_of: date) -> dict:
    """Per unit: quantity per day over the days with reported quantity, using the most complete single source per activity."""
    accepted = engine.accepted_links(session, project, node_ids)
    out = defaultdict(lambda: {"quantity": 0.0, "days": 0, "event_ids": []})
    for nid, links in accepted.items():
        per_source = defaultdict(lambda: defaultdict(float))
        ids = defaultdict(list)
        for l in links:
            e = l.event
            if e.event_type == "progress" and e.quantity and e.unit and e.event_date and e.event_date <= as_of:
                per_source[(stream_of(e), e.unit)][e.event_date] += e.quantity
                ids[(stream_of(e), e.unit)].append(e.id)
        best = {}
        for (src, unit), days in per_source.items():
            if unit not in best or sum(days.values()) > sum(best[unit][0].values()):
                best[unit] = (days, ids[(src, unit)])
        for unit, (days, evids) in best.items():
            out[unit]["quantity"] += sum(days.values())
            out[unit]["days"] += len(days)
            out[unit]["event_ids"] += evids
    return {u: v | {"per_day": round(v["quantity"] / v["days"], 2)} for u, v in out.items() if v["days"]}
