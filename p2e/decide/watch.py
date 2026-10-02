"""Silent-activity watch: what the field did NOT report.

An L5/L6 activity is EXPECTED ACTIVE on the as-of date when it has no actual finish and has either started (actual start)
or reached its planned start. It is SILENT when no linked report (matched, planner-confirmed, or held by a cross-source
date conflict; rejected reports do not count) is dated within the last `days` days up to the as-of date, or it was never
reported at all. Silence is a prompt, not a decision: nothing in the schedule changes.
The supervisor checklist is the same expected-active list for one discipline (and area), with what was reported today.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import EventLink, PlanNode, Project

WATCH_DAYS = 3
COMPATIBLE = {"static_eq": "rotating_eq", "rotating_eq": "static_eq"}   # a "mechanical" supervisor reports both


def _last_reports(session: Session, project: Project, as_of: date) -> dict[int, date]:
    last: dict[int, date] = {}
    for l in session.scalars(select(EventLink).options(selectinload(EventLink.event))
                             .where(EventLink.project_id == project.id, EventLink.state != "rejected")):
        node = l.plan_node_id or ((l.conflict or {}).get("plan_node_id") if l.state == "pending" else None)
        day = l.event.event_date or l.event.report_date
        if node is not None and day is not None and day <= as_of and day > last.get(node, date.min):
            last[node] = day
    return last


def _expected(session: Session, project: Project, as_of: date, discipline: str | None, area: str | None) -> list[PlanNode]:
    stmt = select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.node_type == "activity",
                                  PlanNode.actual_finish.is_(None),
                                  (PlanNode.actual_start.is_not(None)) | (PlanNode.planned_start <= as_of)).order_by(PlanNode.seq)
    if discipline:
        stmt = stmt.where(PlanNode.discipline.in_([discipline] + ([COMPATIBLE[discipline]] if discipline in COMPATIBLE else [])))
    if area:
        stmt = stmt.where(PlanNode.area == area)
    return list(session.scalars(stmt))


def expectation(n: PlanNode, as_of: date) -> str:
    if n.actual_start is not None:
        return "started, no finish reported" + (" (past planned finish)" if n.planned_finish < as_of else "")
    return "past planned finish, not started" if n.planned_finish < as_of else "planned to be in progress, not started"


def silent_activities(session: Session, project: Project, as_of: date, days: int = WATCH_DAYS, discipline: str | None = None,
                      area: str | None = None) -> list[dict]:
    last = _last_reports(session, project, as_of)
    out = []
    for n in _expected(session, project, as_of, discipline, area):
        seen = last.get(n.id)
        quiet = None if seen is None else (as_of - seen).days
        if seen is None or quiet >= days:
            out.append(_item(n, as_of) | {"last_reported": seen, "days_silent": quiet})
    return sorted(out, key=lambda x: (x["days_silent"] is not None, -(x["days_silent"] or 0), x["plan_node_code"]))


def checklist(session: Session, project: Project, as_of: date, discipline: str, area: str | None = None) -> list[dict]:
    last = _last_reports(session, project, as_of)
    return [_item(n, as_of) | {"last_reported": last.get(n.id), "reported_today": last.get(n.id) == as_of}
            for n in _expected(session, project, as_of, discipline, area)]


def _item(n: PlanNode, as_of: date) -> dict:
    return {"plan_node_code": n.code, "activity_name": n.name, "discipline": n.discipline, "area": n.area,
            "planned_start": n.planned_start, "planned_finish": n.planned_finish, "actual_start": n.actual_start,
            "expectation": expectation(n, as_of)}
