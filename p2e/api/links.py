"""Phase 3 routes: schedule linking runs, link decisions with candidates/evidence, planner confirm/reject (-> MAG),
cached project context (CAG), alias memory, OKF export. All need an API key; planner decisions need planner/admin."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from p2e.api import schemas as s
from p2e.api.auth import AnyRole, Uploader, require_role
from p2e.api.routes import NOT_FOUND, SessionDep, project_or_404
from p2e.db.models import Alias, EventLink, LinkCandidate, PlanNode, ProgressEvent
from p2e.link import service
from p2e.link.context import get_context, refresh_context
from p2e.memory import aliases as mag
from p2e.memory import okf

router = APIRouter(prefix="/api/v1/projects/{project_code}", tags=["linking"])
P = {"model": s.ProblemOut}
AUTH = {401: P, 403: P, 503: P}
Planner = Annotated[str, Depends(require_role("planner", "admin"))]
Admin = Annotated[str, Depends(require_role("admin"))]


def link_out(l: EventLink) -> s.LinkOut:
    e = l.event
    return s.LinkOut(event_id=e.id, document_id=e.source_document_id, activity_text=e.activity_text, event_type=e.event_type,
                     event_date=e.event_date, decision=l.decision, state=l.state, plan_node_code=l.node.code if l.node else None,
                     confidence=l.confidence, margin=l.margin, unmatched_type=l.unmatched_type, method=l.method,
                     retrieval_used=l.retrieval_used, reasons=l.reasons or [], llm_suggestion=l.llm_suggestion,
                     linker_version=l.linker_version, context_version=l.context_version, mag_version=l.mag_version,
                     decided_by=l.decided_by, decided_at=l.decided_at, conflict=l.conflict)


def detail_out(l: EventLink) -> s.LinkDetailOut:
    cands = [s.CandidateOut(rank=c.rank, plan_node_code=c.node.code, activity_name=c.node.name, level=c.node.level,
                            discipline=c.node.discipline, area=c.node.area, score=c.score, retrieval_methods=c.methods,
                            matched_tags=c.matched_tags, matched_terms=c.matched_terms, features=c.features, reasons=c.reasons)
             for c in l.candidates]
    return s.LinkDetailOut(**link_out(l).model_dump(), source_text=l.event.source_text, source_ref=l.event.source_ref, candidates=cands)


def alias_out(a: Alias) -> s.AliasOut:
    return s.AliasOut(id=a.id, kind=a.kind, phrase=a.phrase, target=a.target, learned_from_activity=a.node.code,
                      source_event_id=a.source_event_id, confirmed_by=a.confirmed_by, confirmations=a.confirmations,
                      use_count=a.use_count, status=a.status, mag_version=a.mag_version, created_at=a.created_at,
                      updated_at=a.updated_at, last_used_at=a.last_used_at)


def link_or_404(session, project, event_id: int) -> EventLink:
    try:
        return service.get_link(session, project, event_id)
    except service.LinkError as e:
        raise HTTPException(e.status, e.detail) from None


@router.post("/links/run", response_model=s.LinkRunOut, responses={**AUTH, **NOT_FOUND, 422: P})
def run_linking(project_code: str, request: Request, session: SessionDep, _: Uploader, body: s.LinkRunIn | None = None):
    """Link valid progress events to L5/L6 activities. Idempotent; planner decisions are never overwritten."""
    project = project_or_404(session, project_code)
    out = service.link_events(session, project, request.app.state.glossary_path, body.event_ids if body else None,
                              llm=request.app.state.tiebreak)
    session.commit()
    return s.LinkRunOut(**out, llm_tiebreaker=request.app.state.tiebreak is not None)


@router.get("/links", response_model=s.LinkPage, responses={**AUTH, **NOT_FOUND})
def list_links(
    project_code: str, session: SessionDep, _: AnyRole,
    decision: s.LinkDecision | None = None,
    state: s.LinkState | None = None,
    plan_node_code: Annotated[str | None, Query(max_length=64)] = None,
    document_id: int | None = None,
    conflict: Annotated[bool | None, Query(description="true = only links with a cross-source date conflict")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    project = project_or_404(session, project_code)
    stmt = select(EventLink).where(EventLink.project_id == project.id)
    if decision:
        stmt = stmt.where(EventLink.decision == decision)
    if state:
        stmt = stmt.where(EventLink.state == state)
    if plan_node_code:
        stmt = stmt.join(PlanNode, EventLink.plan_node_id == PlanNode.id).where(PlanNode.code == plan_node_code)
    if conflict is not None:
        stmt = stmt.where(EventLink.conflict.is_not(None) if conflict else EventLink.conflict.is_(None))
    if document_id is not None:
        stmt = stmt.join(ProgressEvent, EventLink.progress_event_id == ProgressEvent.id).where(ProgressEvent.source_document_id == document_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.options(selectinload(EventLink.event), selectinload(EventLink.node))
                           .order_by(EventLink.progress_event_id).limit(limit).offset(offset))
    return s.LinkPage(items=[link_out(l) for l in rows], total=total, limit=limit, offset=offset)


@router.get("/links/{event_id}", response_model=s.LinkDetailOut, responses={**AUTH, **NOT_FOUND})
def get_link(project_code: str, event_id: int, session: SessionDep, _: AnyRole):
    """Decision + every retrieved candidate with its score, retrieval methods and matched evidence."""
    return detail_out(link_or_404(session, project_or_404(session, project_code), event_id))


@router.post("/links/{event_id}/confirm", response_model=s.ConfirmOut, responses={**AUTH, **NOT_FOUND, 422: P})
def confirm_link(project_code: str, event_id: int, body: s.ConfirmIn, request: Request, session: SessionDep, role: Planner):
    """Planner confirms the activity (a candidate or any other L5/L6 activity). Alias memory learns from this only."""
    project = project_or_404(session, project_code)
    link = link_or_404(session, project, event_id)
    try:
        learned = service.confirm(session, project, link, body.plan_node_code, f"human:{role}", request.app.state.glossary_path)
    except service.LinkError as e:
        raise HTTPException(e.status, e.detail) from None
    session.commit()
    return s.ConfirmOut(link=detail_out(link_or_404(session, project, event_id)), **learned)


@router.post("/links/{event_id}/reject", response_model=s.LinkDetailOut, responses={**AUTH, **NOT_FOUND})
def reject_link(project_code: str, event_id: int, request: Request, session: SessionDep, role: Planner):
    """Planner decides the event matches no schedule activity (new / unplanned work). Nothing is learned."""
    project = project_or_404(session, project_code)
    link = link_or_404(session, project, event_id)
    service.reject(session, project, link, f"human:{role}", request.app.state.glossary_path)
    session.commit()
    return detail_out(link_or_404(session, project, event_id))


@router.post("/links/{event_id}/hold", response_model=s.LinkDetailOut, responses={**AUTH, **NOT_FOUND, 409: P})
def hold_link(project_code: str, event_id: int, session: SessionDep, role: Planner):
    """Send a decision back to planner review ("send to review"). The linker will not override it."""
    project = project_or_404(session, project_code)
    link = link_or_404(session, project, event_id)
    try:
        service.hold(session, link, f"human:{role}")
    except service.LinkError as e:
        raise HTTPException(e.status, e.detail) from None
    session.commit()
    return detail_out(link_or_404(session, project, event_id))


@router.get("/context", responses={**AUTH, **NOT_FOUND})
def get_project_context(project_code: str, request: Request, session: SessionDep, _: AnyRole) -> dict:
    """CAG: what the cached project context contains, its version and sources."""
    ctx = get_context(session, project_or_404(session, project_code), request.app.state.glossary_path)
    return ctx.describe()


@router.post("/context/refresh", responses={**AUTH, **NOT_FOUND})
def refresh_project_context(project_code: str, request: Request, session: SessionDep, _: Admin) -> dict:
    """Drop the cached context and rebuild it from its sources now."""
    project = project_or_404(session, project_code)
    refresh_context(project.id)
    return get_context(session, project, request.app.state.glossary_path).describe()


@router.get("/aliases", response_model=list[s.AliasOut], responses={**AUTH, **NOT_FOUND})
def list_aliases(project_code: str, session: SessionDep, _: AnyRole, status: s.Literal["active", "revoked"] | None = None):
    project = project_or_404(session, project_code)
    stmt = select(Alias).options(selectinload(Alias.node)).where(Alias.project_id == project.id)
    if status:
        stmt = stmt.where(Alias.status == status)
    return [alias_out(a) for a in session.scalars(stmt.order_by(Alias.id))]


@router.post("/aliases/{alias_id}/revoke", response_model=s.AliasOut, responses={**AUTH, **NOT_FOUND})
def revoke_alias(project_code: str, alias_id: int, session: SessionDep, _: Planner):
    """Stop using a learned alias (kept for history). Pending links are re-evaluated on the next linking run."""
    project = project_or_404(session, project_code)
    a = session.scalar(select(Alias).options(selectinload(Alias.node)).where(Alias.id == alias_id, Alias.project_id == project.id))
    if a is None:
        raise HTTPException(404, f"alias {alias_id} not found in project {project.code}")
    mag.revoke(a)
    session.commit()
    return alias_out(a)


@router.get("/knowledge/okf.zip", responses={**AUTH, **NOT_FOUND, 200: {"content": {"application/zip": {}}}})
def export_okf(project_code: str, request: Request, session: SessionDep, _: Planner):
    """OKF v0.2 knowledge bundle (glossary, matching rules, activity families, confirmed aliases). SQLite stays the source."""
    project = project_or_404(session, project_code)
    files = okf.build_bundle(session, project, get_context(session, project, request.app.state.glossary_path))
    return Response(okf.zip_bundle(files), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{project.code}-okf.zip"'})
