"""Phase 4 route: one text Time Agent turn (supervisor message -> structured event -> existing linker)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from p2e.agent import time_agent
from p2e.api import schemas as s
from p2e.api.auth import Uploader
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
    out = time_agent.handle(session, project, body.message, ref, role, request.app.state.upload_dir,
                            request.app.state.glossary_path, llm=request.app.state.llm, discipline=body.discipline,
                            answers=body.answers.model_dump() if body.answers else None)
    session.commit()
    link = detail_out(link_or_404(session, project, out["event_id"])) if out["event_id"] else None
    return s.AgentReplyOut(**out, reference_datetime=ref, link=link)
