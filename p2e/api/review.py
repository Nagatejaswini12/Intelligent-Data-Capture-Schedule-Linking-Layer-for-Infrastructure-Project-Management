"""Phase 5 routes: apply actuals, review queue + planner actions, audit + undo, live updates (SSE), schedule export.
Reads need any API key; changing the schedule by hand (approve, new activity, override, undo) needs planner/admin."""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from p2e.api import schemas as s
from p2e.api.auth import AnyRole, Uploader
from p2e.api.links import Planner, detail_out, link_or_404
from p2e.api.routes import NOT_FOUND, SessionDep, project_or_404
from p2e.db.models import AuditLog, EventLink, LinkCandidate, PlanNode, Project
from p2e.decide import apply as engine
from p2e.decide import watch
from p2e.link import service as linking
from p2e.plan import exporters

router = APIRouter(prefix="/api/v1/projects/{project_code}", tags=["review & apply"])
P = {"model": s.ProblemOut}
AUTH = {401: P, 403: P, 503: P}
TOP_CANDIDATES = 3


def today(project: Project) -> date:
    return datetime.now(ZoneInfo(project.timezone)).date()


def proposal_out(p: engine.Proposal) -> s.ProposalOut:
    return s.ProposalOut(plan_node_code=p.node.code, activity_name=p.node.name, proposed=p.proposed, changes=p.changes,
                         evidence_event_ids=p.evidence, confidence=p.confidence, basis=p.basis, blockers=p.blockers, warnings=p.warnings)


def audit_out(e: AuditLog, undone_by: int | None = None) -> s.AuditOut:
    return s.AuditOut(id=e.id, plan_node_code=e.node.code, action=e.action, changes=e.changes, actor=e.actor, rule=e.rule,
                      confidence=e.confidence, evidence_event_ids=e.evidence_event_ids or [], warnings=e.warnings or [],
                      reverts_id=e.reverts_id, undone_by=undone_by, created_at=e.created_at)


def apply_out(r: dict) -> s.ApplyOut:
    return s.ApplyOut(as_of=r["as_of"], dry_run=r["dry_run"],
                      applied=[] if r["dry_run"] else [audit_out(e) for e in r["applied"]],
                      would_apply=[proposal_out(p) for p in r["applied"]] if r["dry_run"] else [],
                      blocked=[proposal_out(p) for p in r["blocked"]], unchanged=r["unchanged"])


def engine_error(e: engine.ApplyError | linking.LinkError) -> HTTPException:
    return HTTPException(e.status, e.detail)


@router.post("/apply", response_model=s.ApplyOut, responses={**AUTH, **NOT_FOUND, 422: P})
def apply_actuals(project_code: str, session: SessionDep, _: Uploader, body: s.ApplyIn | None = None):
    """Write actual start/finish/percent from accepted links (auto-matched or planner-confirmed) where every rule passes;
    each change gets an audit entry. Blocked activities are returned (and listed in the review queue). Idempotent."""
    project = project_or_404(session, project_code)
    body = body or s.ApplyIn()
    r = engine.apply(session, project, body.as_of or today(project), engine.AUTO_ACTOR, dry_run=body.dry_run)
    out = apply_out(r)
    session.commit() if not body.dry_run else session.rollback()
    return out


@router.get("/review", response_model=s.ReviewQueueOut, responses={**AUTH, **NOT_FOUND})
def review_queue(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None,
                 limit: Annotated[int, Query(ge=1, le=1000)] = 100):
    """Planner work list: pending link decisions (with evidence, conflict and the top-3 candidates) and activities whose
    reported actuals are blocked by a rule."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    pending = session.scalars(select(EventLink).options(selectinload(EventLink.event), selectinload(EventLink.node),
                                                        selectinload(EventLink.candidates).selectinload(LinkCandidate.node))
                              .where(EventLink.project_id == project.id, EventLink.state == "pending")
                              .order_by(EventLink.progress_event_id).limit(limit)).all()
    events = []
    for l in pending:
        d = detail_out(l)
        events.append(d.model_copy(update={"candidates": d.candidates[:TOP_CANDIDATES]}))
    blocked = [p for p in engine.propose(session, project, as_of) if p.blockers]
    total_pending = session.scalar(select(func.count()).select_from(EventLink).where(EventLink.project_id == project.id,
                                                                                    EventLink.state == "pending"))
    conflicts = session.scalar(select(func.count()).select_from(EventLink).where(EventLink.project_id == project.id,
                                                                                EventLink.state == "pending", EventLink.conflict.is_not(None)))
    return s.ReviewQueueOut(as_of=as_of, events=events, activities=[proposal_out(p) for p in blocked],
                            counts={"pending_events": total_pending, "pending_conflicts": conflicts, "blocked_activities": len(blocked)})


@router.post("/review/events/{event_id}/approve", response_model=s.ApproveOut, responses={**AUTH, **NOT_FOUND, 422: P})
def approve(project_code: str, event_id: int, request: Request, session: SessionDep, role: Planner, body: s.ApproveIn | None = None):
    """Approve the top candidate, or choose another activity; alias memory learns (Phase 3) and the activity's actuals are
    applied where the rules allow."""
    project = project_or_404(session, project_code)
    body = body or s.ApproveIn()
    link = link_or_404(session, project, event_id)
    code = body.plan_node_code or (link.conflict or {}).get("plan_node_code") or (link.candidates[0].node.code if link.candidates else None)
    if code is None:
        raise HTTPException(422, "no candidate activity; give plan_node_code or mark the report as a new activity")
    try:
        learned = linking.confirm(session, project, link, code, f"human:{role}", request.app.state.glossary_path)
    except linking.LinkError as e:
        raise engine_error(e) from None
    r = engine.apply(session, project, body.as_of or today(project), f"human:{role}", node_ids=[link.plan_node_id])
    out = apply_out(r)
    session.commit()
    return s.ApproveOut(link=detail_out(link_or_404(session, project, event_id)), apply=out, **learned)


@router.post("/review/events/{event_id}/new-activity", response_model=s.ApproveOut, responses={**AUTH, **NOT_FOUND, 409: P, 422: P})
def mark_new(project_code: str, event_id: int, body: s.NewActivityIn, request: Request, session: SessionDep, role: Planner):
    """Mark the report as NEW work: create the activity under the given WBS parent, link the report to it, apply actuals."""
    project = project_or_404(session, project_code)
    link = link_or_404(session, project, event_id)
    ev = link.event
    start = body.planned_start or ev.event_date or ev.report_date
    finish = body.planned_finish or start
    actor = f"human:{role}"
    try:
        node = engine.create_activity(session, project, body.parent_code, body.code, body.name, start, finish, ev, actor)
        learned = linking.confirm(session, project, link, node.code, actor, request.app.state.glossary_path)
    except (engine.ApplyError, linking.LinkError) as e:
        session.rollback()
        raise engine_error(e) from None
    r = engine.apply(session, project, body.as_of or today(project), actor, node_ids=[node.id])
    out = apply_out(r)
    session.commit()
    return s.ApproveOut(link=detail_out(link_or_404(session, project, event_id)), apply=out, **learned)


@router.post("/review/activities/{node_code}/override", response_model=s.AuditOut, responses={**AUTH, **NOT_FOUND, 409: P, 422: P})
def override_actuals(project_code: str, node_code: str, body: s.OverrideIn, session: SessionDep, role: Planner):
    """Planner sets actuals explicitly (e.g. picks the date of a contradicted report). Only the fields sent are changed."""
    project = project_or_404(session, project_code)
    node = session.scalar(select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.code == node_code))
    if node is None:
        raise HTTPException(404, f"activity {node_code!r} not found in project {project.code}")
    values = {f: getattr(body, f) for f in engine.FIELDS if f in body.model_fields_set}
    try:
        entry = engine.override(session, project, node, values, f"human:{role}", body.as_of or today(project), body.evidence_event_ids)
    except engine.ApplyError as e:
        session.rollback()
        raise engine_error(e) from None
    session.commit()
    return audit_out(entry)


@router.get("/audit", response_model=s.AuditPage, responses={**AUTH, **NOT_FOUND})
def list_audit(project_code: str, session: SessionDep, _: AnyRole, plan_node_code: Annotated[str | None, Query(max_length=64)] = None,
               action: s.Literal["apply", "override", "undo", "create_activity"] | None = None,
               limit: Annotated[int, Query(ge=1, le=1000)] = 100, offset: Annotated[int, Query(ge=0)] = 0):
    project = project_or_404(session, project_code)
    stmt = select(AuditLog).where(AuditLog.project_id == project.id)
    if plan_node_code:
        stmt = stmt.join(PlanNode, AuditLog.plan_node_id == PlanNode.id).where(PlanNode.code == plan_node_code)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.options(selectinload(AuditLog.node)).order_by(AuditLog.id).limit(limit).offset(offset)).all()
    undone = dict(session.execute(select(AuditLog.reverts_id, AuditLog.id).where(AuditLog.reverts_id.in_([e.id for e in rows]))).all())
    return s.AuditPage(items=[audit_out(e, undone.get(e.id)) for e in rows], total=total, limit=limit, offset=offset)


@router.post("/audit/{entry_id}/undo", response_model=s.AuditOut, responses={**AUTH, **NOT_FOUND, 409: P})
def undo_entry(project_code: str, entry_id: int, session: SessionDep, role: Planner):
    """Revert an apply/override with a compensating audit entry (the original stays). Refused if the values changed since."""
    project = project_or_404(session, project_code)
    try:
        entry = engine.undo(session, project, entry_id, f"human:{role}")
    except engine.ApplyError as e:
        session.rollback()
        raise engine_error(e) from None
    session.commit()
    return audit_out(entry)


def snapshot(session, project: Project) -> dict:
    """Small state summary for live views; changes whenever an actual is applied/undone or a decision changes."""
    decisions = dict(session.execute(select(EventLink.decision, func.count()).where(EventLink.project_id == project.id)
                                     .group_by(EventLink.decision)).all())
    return {"audit_last_id": session.scalar(select(func.max(AuditLog.id)).where(AuditLog.project_id == project.id)) or 0,
            "pending_review": session.scalar(select(func.count()).select_from(EventLink).where(
                EventLink.project_id == project.id, EventLink.state == "pending")),
            "decisions": decisions,
            "activities_with_actuals": session.scalar(select(func.count()).select_from(PlanNode).where(
                PlanNode.project_id == project.id, PlanNode.node_type == "activity", PlanNode.actual_start.is_not(None)))}


@router.get("/stream", responses={**AUTH, **NOT_FOUND, 200: {"content": {"text/event-stream": {}}}})
def stream(project_code: str, request: Request, session: SessionDep, _: AnyRole,
           limit: Annotated[int | None, Query(ge=1, le=10000, description="stop after this many updates")] = None,
           interval: Annotated[float, Query(ge=0.2, le=60)] = 1.0):
    """Server-sent events: one `update` message with the current snapshot, then one whenever it changes (polled)."""
    project = project_or_404(session, project_code)
    sm = request.app.state.sessionmaker

    def events():
        last, sent, idle = None, 0, 0.0
        while limit is None or sent < limit:
            with sm() as s2:
                snap = snapshot(s2, s2.get(Project, project.id))
            if snap != last:
                last, sent, idle = snap, sent + 1, 0.0
                yield f"event: update\ndata: {json.dumps(snap, sort_keys=True)}\n\n"
                continue
            time.sleep(interval)
            idle += interval
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def watch_out(as_of: date, days: int | None, items: list[dict]) -> s.WatchOut:
    counts: dict[str, int] = {}
    for i in items:
        counts[i["expectation"]] = counts.get(i["expectation"], 0) + 1
    return s.WatchOut(as_of=as_of, days=days, counts=counts, items=[s.WatchItemOut(**i) for i in items])


@router.get("/watch/silent", response_model=s.WatchOut, responses={**AUTH, **NOT_FOUND})
def silent_activities(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None,
                      days: Annotated[int, Query(ge=1, le=60)] = watch.WATCH_DAYS, discipline: s.Discipline | None = None,
                      area: Annotated[str | None, Query(max_length=32)] = None):
    """Activities the plan expects to be active that no field report mentioned in the last `days` days (or ever)."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    return watch_out(as_of, days, watch.silent_activities(session, project, as_of, days, discipline, area))


@router.get("/watch/checklist", response_model=s.WatchOut, responses={**AUTH, **NOT_FOUND})
def report_checklist(project_code: str, discipline: s.Discipline, session: SessionDep, _: AnyRole, as_of: date | None = None,
                     area: Annotated[str | None, Query(max_length=32)] = None):
    """A supervisor's daily list: expected-active activities of one discipline (and area) and whether reported today."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    return watch_out(as_of, None, watch.checklist(session, project, as_of, discipline, area))


@router.get("/export/schedule.csv", responses={**AUTH, **NOT_FOUND, 200: {"content": {"text/csv": {}}}})
def export_csv(project_code: str, session: SessionDep, _: AnyRole):
    project = project_or_404(session, project_code)
    return Response(exporters.to_csv(exporters.rows(session, project)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{project.code}-actuals.csv"'})


@router.get("/export/schedule.xml", responses={**AUTH, **NOT_FOUND, 200: {"content": {"application/xml": {}}}})
def export_mspdi(project_code: str, session: SessionDep, _: AnyRole, status_date: date | None = None):
    project = project_or_404(session, project_code)
    data = exporters.to_mspdi(project, exporters.rows(session, project), status_date or today(project))
    return Response(data, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{project.code}-actuals.xml"'})
