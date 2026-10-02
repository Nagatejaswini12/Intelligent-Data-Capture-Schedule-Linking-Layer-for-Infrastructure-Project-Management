from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from p2e import __version__
from p2e.api import schemas as s
from p2e.db.models import PlanNode, Project
from p2e.plan import queries

health_router = APIRouter(tags=["health"])
router = APIRouter(prefix="/api/v1", tags=["schedule"])
NOT_FOUND = {404: {"model": s.ProblemOut}}


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def project_or_404(session: Session, code: str) -> Project:
    project = queries.get_project(session, code)
    if project is None:
        raise HTTPException(404, f"project {code!r} not found")
    return project


def node_out(n: PlanNode) -> s.PlanNodeOut:
    return s.PlanNodeOut(code=n.code, node_type=n.node_type, is_executable=n.is_executable, level=n.level, name=n.name,
                         wbs_code=n.wbs_code, parent_code=n.parent.code if n.parent else None, discipline=n.discipline,
                         area=n.area, activity_type=n.activity_type, planned_start=n.planned_start,
                         planned_finish=n.planned_finish, planned_duration_days=n.planned_duration_days,
                         planned_qty=n.planned_qty, qty_unit=n.qty_unit, actual_start=n.actual_start,
                         actual_finish=n.actual_finish, tags=[t.tag for t in n.tags])


def project_out(p: Project) -> s.ProjectOut:
    return s.ProjectOut(code=p.code, name=p.name, timezone=p.timezone, data_date=p.data_date, created_at=p.created_at,
                        updated_at=p.updated_at,
                        schedule_sources=[s.ScheduleSourceOut.model_validate(x) for x in p.sources if x.kind == "schedule_import"])


@health_router.get("/health", response_model=s.HealthOut)
def health(session: SessionDep):
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable") from None
    return s.HealthOut(status="ok", database="ok", version=__version__)


@router.get("/projects", response_model=list[s.ProjectOut])
def list_projects(session: SessionDep):
    return [project_out(p) for p in queries.list_projects(session)]


@router.get("/projects/{project_code}", response_model=s.ProjectOut, responses=NOT_FOUND)
def get_project(project_code: str, session: SessionDep):
    return project_out(project_or_404(session, project_code))


@router.get("/projects/{project_code}/summary", response_model=s.ScheduleSummaryOut, responses=NOT_FOUND)
def schedule_summary(project_code: str, session: SessionDep):
    p = project_or_404(session, project_code)
    return s.ScheduleSummaryOut(project_code=p.code, data_date=p.data_date, **queries.schedule_summary(session, p))


@router.get("/projects/{project_code}/plan", response_model=s.PlanNodePage, responses=NOT_FOUND)
def list_plan_nodes(
    project_code: str,
    session: SessionDep,
    node_type: s.NodeType | None = None,
    executable: Annotated[bool | None, Query(description="true = executable L5/L6 activities only")] = None,
    level: Annotated[int | None, Query(ge=1, le=6)] = None,
    discipline: s.Discipline | None = None,
    area: Annotated[str | None, Query(max_length=32)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200, description="case-insensitive literal substring of the name")] = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=64, description="exact canonical tag, e.g. P-101A, LINE-1203")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    p = project_or_404(session, project_code)
    items, total = queries.list_nodes(session, p, node_type=node_type, executable=executable, level=level,
                                      discipline=discipline, area=area, q=q, tag=tag, limit=limit, offset=offset)
    return s.PlanNodePage(items=[node_out(n) for n in items], total=total, limit=limit, offset=offset)


@router.get("/projects/{project_code}/plan/{node_code}", response_model=s.PlanNodeDetailOut, responses=NOT_FOUND)
def get_plan_node(project_code: str, node_code: str, session: SessionDep):
    p = project_or_404(session, project_code)
    n = queries.get_node(session, p, node_code)
    if n is None:
        raise HTTPException(404, f"plan node / activity {node_code!r} not found in project {project_code!r}")
    ref = lambda x: s.NodeRef(code=x.code, node_type=x.node_type, level=x.level, name=x.name)
    return s.PlanNodeDetailOut(
        **node_out(n).model_dump(),
        ancestors=[ref(a) for a in queries.ancestors(n)],
        children=[ref(c) for c in n.children],
        predecessors=[s.DependencyOut(code=d.predecessor.code, link_type=d.link_type, lag_days=d.lag_days) for d in n.predecessors],
        successors=[s.DependencyOut(code=d.successor.code, link_type=d.link_type, lag_days=d.lag_days)
                    for d in queries.successors(session, n)],
    )


@router.get("/projects/{project_code}/hierarchy", response_model=s.TreeNodeOut, responses=NOT_FOUND)
def get_hierarchy(
    project_code: str,
    session: SessionDep,
    root: Annotated[str | None, Query(max_length=64, description="start at this node code (default: project root)")] = None,
    depth: Annotated[int | None, Query(ge=0, le=6, description="levels below root to include (default: all)")] = None,
):
    p = project_or_404(session, project_code)
    tree = queries.hierarchy(session, p, root, depth)
    if tree is None:
        raise HTTPException(404, f"node {root!r} not found in project {project_code!r}")
    return tree
