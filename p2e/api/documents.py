"""Phase 2 routes: authenticated ingestion + processing; document / event / evidence reads (any valid role)."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from p2e.api import schemas as s
from p2e.api.auth import AnyRole, Uploader
from p2e.api.routes import NOT_FOUND, SessionDep, project_or_404
from p2e.db.models import ExtractionRun, ProgressEvent, Project, SourceDocument
from p2e.ingest import service

router = APIRouter(prefix="/api/v1/projects/{project_code}", tags=["ingestion"])
P = {"model": s.ProblemOut}
AUTH = {401: P, 403: P, 503: P}


def run_out(r: ExtractionRun | None) -> s.RunOut | None:
    return s.RunOut.model_validate(r) if r else None


def doc_out(d: SourceDocument, project: Project) -> s.DocumentOut:
    return s.DocumentOut(id=d.id, project_code=project.code, kind=d.kind, format=d.format, filename=d.filename, sha256=d.sha256,
                         size_bytes=d.size_bytes, status=d.status, uploaded_by=d.uploaded_by, report_date=d.report_date,
                         discipline_group=d.discipline_group, error=d.error, created_at=d.created_at,
                         latest_run=run_out(d.runs[-1] if d.runs else None))


def event_out(e: ProgressEvent) -> s.EventOut:
    return s.EventOut(
        id=e.id, document_id=e.source_document_id, document_filename=e.document.filename, source_type=e.document.kind,
        source_ref=e.source_ref, source_text=e.source_text, report_date=e.report_date, discipline=e.discipline,
        activity_text=e.activity_text, event_type=e.event_type, event_date=e.event_date, date_text=e.date_text,
        event_time=e.event_time, reported_actual_start=e.event_date if e.event_type == "start" else None,
        reported_actual_finish=e.event_date if e.event_type == "finish" else None, quantity=e.quantity, unit=e.unit,
        area=e.area, tags=e.tags or [], delay_reason=e.delay_reason, delay_category=e.delay_category,
        extraction_method=e.extraction_method, parser_version=e.parser_version, validation_status=e.validation_status,
        validation_errors=e.validation_errors or [], created_at=e.created_at)


def ingest_error(e: service.IngestError) -> HTTPException:
    return HTTPException(e.status, {"message": e.detail, **e.extra} if e.extra else e.detail)


def document_or_404(session: Session, project: Project, document_id: int) -> SourceDocument:
    d = session.scalar(select(SourceDocument).options(selectinload(SourceDocument.runs).selectinload(ExtractionRun.issues))
                       .where(SourceDocument.id == document_id, SourceDocument.project_id == project.id))
    if d is None:
        raise HTTPException(404, f"document {document_id} not found in project {project.code}")
    return d


def event_or_404(session: Session, project: Project, event_id: int) -> ProgressEvent:
    e = session.scalar(select(ProgressEvent).options(selectinload(ProgressEvent.document))
                       .where(ProgressEvent.id == event_id, ProgressEvent.project_id == project.id))
    if e is None:
        raise HTTPException(404, f"progress event {event_id} not found in project {project.code}")
    return e


@router.post("/documents", status_code=201, response_model=s.DocumentOut,
             responses={**AUTH, **NOT_FOUND, 409: P, 413: P, 415: P, 422: P})
async def upload_document(project_code: str, file: UploadFile, request: Request, session: SessionDep, role: Uploader):
    """Store a .txt daily progress report or .xlsx discipline sheet (status `received`). Extraction is a separate call."""
    project = project_or_404(session, project_code)
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    try:
        doc = service.ingest_upload(session, project, file.filename, data, role, request.app.state.upload_dir)
    except service.IngestError as e:
        raise ingest_error(e) from None
    session.commit()
    return doc_out(document_or_404(session, project, doc.id), project)


@router.get("/documents", response_model=s.DocumentPage, responses={**AUTH, **NOT_FOUND})
def list_documents(project_code: str, session: SessionDep, _: AnyRole, kind: s.DocKind | None = None,
                   status: s.DocStatus | None = None, limit: Annotated[int, Query(ge=1, le=1000)] = 100,
                   offset: Annotated[int, Query(ge=0)] = 0):
    project = project_or_404(session, project_code)
    stmt = select(SourceDocument).where(SourceDocument.project_id == project.id)
    if kind:
        stmt = stmt.where(SourceDocument.kind == kind)
    if status:
        stmt = stmt.where(SourceDocument.status == status)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    docs = session.scalars(stmt.options(selectinload(SourceDocument.runs)).order_by(SourceDocument.id).limit(limit).offset(offset))
    return s.DocumentPage(items=[doc_out(d, project) for d in docs], total=total, limit=limit, offset=offset)


@router.get("/documents/{document_id}", response_model=s.DocumentOut, responses={**AUTH, **NOT_FOUND})
def get_document(project_code: str, document_id: int, session: SessionDep, _: AnyRole):
    project = project_or_404(session, project_code)
    return doc_out(document_or_404(session, project, document_id), project)


@router.post("/documents/{document_id}/process", response_model=s.ProcessOut, responses={**AUTH, **NOT_FOUND, 415: P})
def process_document(project_code: str, document_id: int, request: Request, session: SessionDep, _: Uploader):
    """Deterministic extraction + validation. Idempotent: the same parser version never re-creates events."""
    project = project_or_404(session, project_code)
    doc = document_or_404(session, project, document_id)
    try:
        run, outcome = service.process_document(session, doc, request.app.state.upload_dir, request.app.state.vocab)
    except service.IngestError as e:
        raise ingest_error(e) from None
    session.commit()
    return s.ProcessOut(document_id=doc.id, outcome=outcome, run=run_out(run))


@router.get("/documents/{document_id}/status", response_model=s.DocumentStatusOut, responses={**AUTH, **NOT_FOUND})
def document_status(project_code: str, document_id: int, session: SessionDep, _: AnyRole):
    project = project_or_404(session, project_code)
    doc = document_or_404(session, project, document_id)
    latest = doc.runs[-1] if doc.runs else None
    return s.DocumentStatusOut(document_id=doc.id, status=doc.status, error=doc.error, runs=len(doc.runs), latest_run=run_out(latest),
                               issues=[s.IssueOut.model_validate(i) for i in (latest.issues if latest else [])])


@router.get("/events", response_model=s.EventPage, responses={**AUTH, **NOT_FOUND})
def list_events(
    project_code: str, session: SessionDep, _: AnyRole,
    document_id: int | None = None,
    source_type: Annotated[s.DocKind | None, Query(description="dpr_text | spreadsheet")] = None,
    discipline: s.Discipline | None = None,
    event_type: s.EventType | None = None,
    validation_status: s.ValidationStatus | None = None,
    date_from: Annotated[date | None, Query(description="event_date >= (ISO date)")] = None,
    date_to: Annotated[date | None, Query(description="event_date <= (ISO date)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    project = project_or_404(session, project_code)
    stmt = select(ProgressEvent).where(ProgressEvent.project_id == project.id)
    if document_id is not None:
        stmt = stmt.where(ProgressEvent.source_document_id == document_id)
    if source_type:
        stmt = stmt.join(SourceDocument).where(SourceDocument.kind == source_type)
    for col, val in ((ProgressEvent.discipline, discipline), (ProgressEvent.event_type, event_type),
                     (ProgressEvent.validation_status, validation_status)):
        if val:
            stmt = stmt.where(col == val)
    if date_from:
        stmt = stmt.where(ProgressEvent.event_date >= date_from)
    if date_to:
        stmt = stmt.where(ProgressEvent.event_date <= date_to)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.options(selectinload(ProgressEvent.document)).order_by(ProgressEvent.id).limit(limit).offset(offset))
    return s.EventPage(items=[event_out(e) for e in rows], total=total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=s.EventOut, responses={**AUTH, **NOT_FOUND})
def get_event(project_code: str, event_id: int, session: SessionDep, _: AnyRole):
    return event_out(event_or_404(session, project_or_404(session, project_code), event_id))


@router.get("/events/{event_id}/evidence", response_model=s.EvidenceOut, responses={**AUTH, **NOT_FOUND})
def get_evidence(project_code: str, event_id: int, request: Request, session: SessionDep, _: AnyRole):
    """Re-reads the stored original file and returns the exact line/offsets or cells the event was taken from."""
    e = event_or_404(session, project_or_404(session, project_code), event_id)
    try:
        return service.evidence(e.document, e, request.app.state.upload_dir)
    except service.IngestError as err:
        raise ingest_error(err) from None
