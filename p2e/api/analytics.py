"""Phase 6 routes: dashboard data, actual-progress dataset, productivity, delay causes, knowledge entries, memory Q&A.
Read-only; any API key."""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from p2e.analytics import metrics, qa
from p2e.api import schemas as s
from p2e.api.auth import AnyRole
from p2e.api.review import today
from p2e.api.routes import NOT_FOUND, SessionDep, project_or_404
from p2e.link.context import get_context
from p2e.memory import knowledge

router = APIRouter(prefix="/api/v1/projects/{project_code}", tags=["analytics & memory"])
P = {"model": s.ProblemOut}
AUTH = {401: P, 403: P, 503: P}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    as_of: date | None = Field(None, description="default: today in the project timezone; the question may say 'as of <date>'")


@router.get("/analytics/dashboard", responses={**AUTH, **NOT_FOUND})
def dashboard(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None) -> dict:
    """Plan vs actual by discipline and area, late starts/finishes, data freshness per discipline, silent activities,
    review backlog."""
    project = project_or_404(session, project_code)
    return metrics.dashboard(session, project, as_of or today(project))


@router.get("/analytics/dataset.csv", responses={**AUTH, **NOT_FOUND, 200: {"content": {"text/csv": {}}}})
def dataset_csv(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None):
    """Actual-progress dataset: one row per executable activity (planned vs actual, durations, variance, sources, delays)."""
    project = project_or_404(session, project_code)
    buf = io.StringIO()
    w = csv.DictWriter(buf, metrics.DATASET_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(metrics.dataset(session, project, as_of or today(project)))
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{project.code}-actual-progress.csv"'})


@router.get("/analytics/dataset", responses={**AUTH, **NOT_FOUND})
def dataset_json(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None) -> dict:
    """The actual-progress dataset as JSON (same rows as dataset.csv) for the schedule view."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    rows = [{k: r[k] for k in metrics.DATASET_COLUMNS} for r in metrics.dataset(session, project, as_of)]
    return {"as_of": as_of, "items": rows}


@router.get("/analytics/productivity", responses={**AUTH, **NOT_FOUND})
def productivity(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None) -> dict:
    """Actual / planned duration per activity type (completed activities) and reported quantity per day per type."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    rows = metrics.dataset(session, project, as_of)
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["activity_type"] or "-"].append(r["_id"])
    rates = {t: {u: {k: v[k] for k in ("quantity", "days", "per_day")} for u, v in metrics.quantity_rate(session, project, ids, as_of).items()}
             for t, ids in sorted(by_type.items())}
    return {"as_of": as_of, "durations": metrics.productivity(rows)["durations"], "rates": {t: r for t, r in rates.items() if r}}


@router.get("/analytics/delays", responses={**AUTH, **NOT_FOUND})
def delays(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None) -> dict:
    """Reported delay causes (fixed taxonomy from the glossary) by category, discipline and area; recurring causes."""
    project = project_or_404(session, project_code)
    as_of = as_of or today(project)
    items = [(e, n) for e, n in metrics.delay_events(session, project) if e.event_date and e.event_date <= as_of]
    by = {"category": Counter(), "discipline": defaultdict(Counter), "area": defaultdict(Counter)}
    for e, n in items:
        by["category"][e.delay_category] += 1
        by["discipline"][e.discipline or "-"][e.delay_category] += 1
        by["area"][(n.area if n else e.area) or "-"][e.delay_category] += 1
    recurring = [{"discipline": d, "category": c, "reports": k} for d, cs in sorted(by["discipline"].items()) for c, k in sorted(cs.items()) if k >= 2]
    return {"as_of": as_of, "by_category": dict(sorted(by["category"].items())),
            "by_discipline": {k: dict(v) for k, v in sorted(by["discipline"].items())},
            "by_area": {k: dict(v) for k, v in sorted(by["area"].items())}, "recurring": recurring,
            "reports": [{"event_id": e.id, "date": e.event_date, "discipline": e.discipline, "activity": n.code if n else None,
                         "category": e.delay_category, "reason": e.delay_reason, "source_text": e.source_text} for e, n in items]}


@router.get("/knowledge", responses={**AUTH, **NOT_FOUND})
def knowledge_entries(project_code: str, session: SessionDep, _: AnyRole, as_of: date | None = None) -> list[dict]:
    """Institutional knowledge entries (activity-type durations, delay patterns) with the records they cite."""
    project = project_or_404(session, project_code)
    return knowledge.entries(session, project, as_of or today(project))


@router.post("/memory/ask", responses={**AUTH, **NOT_FOUND, 422: P})
def ask(project_code: str, body: AskIn, request: Request, session: SessionDep, _: AnyRole) -> dict:
    """Plain-language question -> fixed query template (or cited retrieval) over the project history; every answer cites."""
    project = project_or_404(session, project_code)
    ctx = get_context(session, project, request.app.state.glossary_path)
    return qa.answer(session, project, body.question, ctx, body.as_of or today(project))
