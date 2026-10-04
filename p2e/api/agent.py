"""Phase 4 route: one text Time Agent turn (supervisor message -> structured event -> existing linker)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from p2e import i18n
from p2e.agent import time_agent
from p2e.api import schemas as s
from p2e.db.models import ProgressEvent
from p2e.link import service as linking
from p2e.api.auth import Uploader, discipline_scope
from p2e.api.links import detail_out, link_or_404
from p2e.api.routes import NOT_FOUND, SessionDep, project_or_404

router = APIRouter(prefix="/api/v1/projects/{project_code}", tags=["time agent"])
P = {"model": s.ProblemOut}


@router.post("/agent/messages", response_model=s.AgentReplyOut, responses={401: P, 403: P, 503: P, **NOT_FOUND, 422: P})
def agent_message(project_code: str, body: s.AgentMessageIn, request: Request, session: SessionDep, role: Uploader):
    """Interpret a supervisor's progress message. Asks a question when a required field is missing; otherwise records the
    event (the message is kept verbatim as its source) and links it with the existing Phase 3 linker. The schedule is not
    updated (Phase 5)."""
    project = project_or_404(session, project_code)
    ref = body.reference_datetime or datetime.now(ZoneInfo(project.timezone))     # the only clock read for this turn
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=ZoneInfo(project.timezone))
    scope = discipline_scope(role)
    if scope and body.discipline and body.discipline != scope:
        raise HTTPException(403, f"this key may only log {scope} progress")
    out = time_agent.handle(session, project, body.message, ref, role, request.app.state.upload_dir,
                            request.app.state.glossary_path, llm=request.app.state.llm, discipline=body.discipline or scope,
                            answers=body.answers.model_dump() if body.answers else None, allowed_discipline=scope,
                            lang=body.lang or i18n.detect(body.message) or "en")
    session.commit()
    link = detail_out(link_or_404(session, project, out["event_id"])) if out["event_id"] else None
    return s.AgentReplyOut(**out, reference_datetime=ref, link=link)


@router.post("/agent/events/{event_id}/retract", response_model=s.LinkDetailOut, responses={401: P, 403: P, 409: P, **NOT_FOUND})
def retract_event(project_code: str, event_id: int, session: SessionDep, role: Uploader):
    """Supervisor "undo": send their own Time Agent report back to planner review so nothing is applied from it.
    The report and its evidence are kept; only a planner can reject or confirm it."""
    project = project_or_404(session, project_code)
    link = link_or_404(session, project, event_id)
    ev = session.get(ProgressEvent, event_id)
    if ev.extraction_method != time_agent.AGENT_EXTRACTOR:
        raise HTTPException(409, "only Time Agent reports can be retracted here; use the review queue")
    scope = discipline_scope(role)
    if scope and ev.discipline != scope:
        raise HTTPException(403, f"this key may only retract {scope} reports")
    try:
        linking.hold(session, link, f"supervisor-retract:{role}")
    except linking.LinkError as e:
        raise HTTPException(e.status, e.detail) from None
    session.commit()
    return detail_out(link_or_404(session, project, event_id))
