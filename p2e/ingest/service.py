"""Ingestion (upload checks, content-addressed raw store, duplicate detection) and persisted extraction runs."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from p2e.db.models import ExtractionIssue, ExtractionRun, PlanNode, ProgressEvent, Project, SourceDocument
from p2e.extract import dpr, formats, xlsx
from p2e.extract.pipeline import ProjectVocab, extract_bytes, validate_item

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_XLSX_ENTRIES = 1000
KINDS = {".txt": ("dpr_text", "txt", dpr), ".xlsx": ("spreadsheet", "xlsx", xlsx),
         ".docx": ("dpr_text", "docx", dpr), ".csv": ("spreadsheet", "csv", xlsx)}     # docx / csv: upgrade W4
ACCEPTED = ".txt or .docx daily progress reports, .xlsx or .csv sheets"


class IngestError(Exception):
    status = 422

    def __init__(self, detail: str, **extra):
        super().__init__(detail)
        self.detail, self.extra = detail, extra


class UnsupportedFile(IngestError):
    status = 415


class FileTooLarge(IngestError):
    status = 413


class MalformedFile(IngestError):
    status = 422


class DuplicateDocument(IngestError):
    status = 409


class StoredFileMismatch(IngestError):
    status = 500


class SourceUnavailable(IngestError):
    """The stored raw file is missing/unreadable. The database records (document, events, links) are untouched; callers get
    a controlled 404 that carries what the database still knows. Never includes filesystem paths or OS error text."""
    status = 404

    def __init__(self, doc: SourceDocument, reason: str):
        super().__init__(f"raw source file for document {doc.id} is unavailable; the stored evidence metadata is still available",
                         status="source_unavailable", reason=reason, document_id=doc.id)


def safe_filename(name: str | None) -> str:
    """Original name for display only (never used as a path): last path component, printable, <= 255 chars."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:255] or "upload"


def check_content(filename: str, data: bytes) -> tuple[str, str]:
    """-> (kind, format). Extension decides the parser; content must agree with it."""
    suffix = Path(filename).suffix.lower()
    if suffix not in KINDS:
        raise UnsupportedFile(f"unsupported file type {suffix or '(none)'!r}; accepted: {ACCEPTED}")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileTooLarge(f"file is larger than {MAX_UPLOAD_BYTES} bytes")
    if not data:
        raise MalformedFile("file is empty")
    what = {".txt": "text report", ".csv": "CSV sheet", ".xlsx": "workbook", ".docx": "Word report"}[suffix]
    if suffix in (".txt", ".csv"):
        if b"\x00" in data:
            raise MalformedFile(f"{what} contains binary data")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise MalformedFile(f"{what} is not UTF-8: {e}") from None
        if suffix == ".csv":
            try:
                if not any(any(c.strip() for c in row) for row in csv.reader(io.StringIO(text))):
                    raise MalformedFile("CSV sheet has no values")
            except csv.Error as e:
                raise MalformedFile(f"CSV sheet cannot be read: {e}") from None
        return KINDS[suffix][0], KINDS[suffix][1]
    main_part = "xl/workbook.xml" if suffix == ".xlsx" else "word/document.xml"
    if not data.startswith(b"PK\x03\x04"):
        raise MalformedFile(f"not a {suffix} {what} (not a zip container)")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
            if len(infos) > MAX_XLSX_ENTRIES or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
                raise MalformedFile(f"{what} expands beyond the allowed size")
            if main_part not in names or "[Content_Types].xml" not in names:
                raise MalformedFile(f"not a {suffix} {what} ({main_part} missing)")
            if any(n.lower().endswith("vbaproject.bin") for n in names) or b"macroEnabled" in z.read("[Content_Types].xml"):
                raise UnsupportedFile("macro-enabled files are not accepted")
        if suffix == ".xlsx":
            load_workbook(io.BytesIO(data), read_only=True, data_only=True).close()
        else:
            formats.docx_text(data)
    except zipfile.BadZipFile as e:
        raise MalformedFile(f"corrupt {what}: {e}") from None
    except IngestError:
        raise
    except Exception as e:      # openpyxl / XML parsers raise many types on malformed parts
        raise MalformedFile(f"{what} cannot be read: {type(e).__name__}: {e}") from None
    return KINDS[suffix][0], KINDS[suffix][1]


def _blob_path(upload_dir: Path, storage_uri: str) -> Path:
    return Path(upload_dir) / storage_uri


def _vercel_blob(method: str, name: str, data: bytes | None = None) -> bytes:
    """Vercel Blob (private store), used when BLOB_READ_WRITE_TOKEN is set (Vercel functions have no writable disk)."""
    token = os.environ["BLOB_READ_WRITE_TOKEN"]
    store = token.split("_")[3]                                    # vercel_blob_rw_<storeId>_<secret>
    headers = {"authorization": f"Bearer {token}"}
    if method == "PUT":
        url = "https://vercel.com/api/blob/?" + urllib.parse.urlencode({"pathname": f"uploads/{name}"})
        headers |= {"x-api-version": "12", "x-vercel-blob-store-id": store, "x-vercel-blob-access": "private",
                    "x-add-random-suffix": "0", "x-allow-overwrite": "1", "x-content-type": "application/octet-stream"}
    else:
        url = f"https://{store}.private.blob.vercel-storage.com/uploads/{name}"
    with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=30) as r:
        return r.read()


def store_blob(upload_dir: Path, sha256: str, fmt: str, data: bytes) -> str:
    """Content-addressed write (<sha256>.<fmt>); an existing blob is never overwritten."""
    name = f"{sha256}.{fmt}"
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        _vercel_blob("PUT", name, data)                            # same name = same bytes, so overwrite is harmless
        return name
    path = _blob_path(upload_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return name


def read_blob(upload_dir: Path, doc: SourceDocument) -> bytes:
    try:
        if os.environ.get("BLOB_READ_WRITE_TOKEN"):
            try:
                data = _vercel_blob("GET", doc.storage_uri)
            except urllib.error.HTTPError as e:
                raise (FileNotFoundError() if e.code == 404 else OSError()) from None
        else:
            data = _blob_path(upload_dir, doc.storage_uri).read_bytes()
    except FileNotFoundError:
        raise SourceUnavailable(doc, "raw_source_file_missing") from None
    except OSError:                                  # permissions, a directory in its place, I/O error
        raise SourceUnavailable(doc, "raw_source_file_unreadable") from None
    if hashlib.sha256(data).hexdigest() != doc.sha256:
        raise StoredFileMismatch(f"stored file for document {doc.id} does not match its recorded hash")
    return data


def ingest_upload(session: Session, project: Project, filename: str | None, data: bytes, uploaded_by: str,
                  upload_dir: Path) -> SourceDocument:
    name = safe_filename(filename)
    kind, fmt = check_content(name, data)
    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(SourceDocument).where(SourceDocument.project_id == project.id, SourceDocument.sha256 == sha))
    if existing is not None:
        raise DuplicateDocument(f"identical content was already ingested as document {existing.id} ({existing.filename})",
                                existing_document_id=existing.id)
    doc = SourceDocument(project_id=project.id, kind=kind, format=fmt, filename=name, sha256=sha, size_bytes=len(data),
                         status="received", uploaded_by=uploaded_by, storage_uri=store_blob(upload_dir, sha, fmt, data))
    session.add(doc)
    session.flush()
    return doc


def parser_for(doc: SourceDocument):
    return {"dpr_text": dpr, "spreadsheet": xlsx}[doc.kind]


def process_document(session: Session, doc: SourceDocument, upload_dir: Path, pv: ProjectVocab) -> tuple[ExtractionRun, str]:
    """Extract + validate + persist. Same parser version already succeeded -> 'unchanged' (no new rows)."""
    if doc.kind not in ("dpr_text", "spreadsheet"):
        raise UnsupportedFile(f"document {doc.id} is a {doc.kind}; only uploaded reports and sheets are extracted")
    module = parser_for(doc)
    latest = doc.runs[-1] if doc.runs else None
    if latest and latest.status == "succeeded" and latest.parser_version == module.PARSER_VERSION:
        return latest, "unchanged"
    if latest and latest.status == "succeeded" and latest.extractor != module.EXTRACTOR:
        return latest, "unchanged"      # produced by another component (e.g. the Time Agent): never re-parsed here
    # document=doc (not just the id) keeps doc.runs current in this session, so a repeat call sees this run
    run = ExtractionRun(document=doc, extractor=module.EXTRACTOR, parser_version=module.PARSER_VERSION, status="failed")
    session.add(run)
    try:
        data, fmt = formats.normalize(read_blob(upload_dir, doc), doc.format)
        result = extract_bytes(data, "." + fmt, pv)
    except Exception as e:
        run.error = doc.error = f"{type(e).__name__}: {e}"
        run.finished_at = datetime.now(timezone.utc)
        doc.status = "failed"
        session.flush()
        return run, "failed"
    lines = dpr.text_lines(data.decode("utf-8")) if fmt == "txt" else None
    project_start = session.scalar(select(func.min(PlanNode.planned_start)).where(PlanNode.project_id == doc.project_id))
    session.execute(delete(ProgressEvent).where(ProgressEvent.source_document_id == doc.id))   # replace older-version events
    session.flush()
    valid = invalid = 0
    for it in result.items:
        errors = validate_item(it, lines=lines, report_date=result.report_date, project_start=project_start)
        valid, invalid = valid + (not errors), invalid + bool(errors)
        session.add(ProgressEvent(
            project_id=doc.project_id, source_document_id=doc.id, extraction_run=run, locator_key=it.locator_key,
            source_ref=it.source_ref, source_text=it.source_text, span_start=it.span[0] if it.span else None,
            span_end=it.span[1] if it.span else None, source_cells=it.source_cells, report_date=result.report_date,
            discipline=it.discipline, activity_text=it.activity_text, event_type=it.event_type, event_date=it.event_date,
            date_text=it.date_text, event_time=it.event_time, quantity=it.quantity, unit=it.unit, area=it.area, tags=it.tags,
            delay_reason=it.delay_reason, delay_category=it.delay_category, extraction_method=result.extractor,
            parser_version=result.parser_version, validation_status="invalid" if errors else "valid", validation_errors=errors))
    run.issues = [ExtractionIssue(source_ref=i.source_ref, source_text=i.source_text, message=i.message) for i in result.issues]
    run.status, run.events_total, run.events_valid, run.events_invalid = "succeeded", len(result.items), valid, invalid
    run.issues_count, run.non_event_lines, run.finished_at = len(result.issues), result.non_event_lines, datetime.now(timezone.utc)
    doc.status, doc.error = "extracted", None
    doc.report_date, doc.discipline_group = result.report_date, result.discipline_group
    session.flush()
    return run, "processed"


def process_batch(session: Session, project: Project, upload_dir: Path, pv: ProjectVocab,
                  document_ids: list[int] | None = None) -> list[dict]:
    """Process many documents, committing after each so one failure never rolls back the others.
    No ids -> every uploaded report/sheet of the project (already-processed ones come back 'unchanged')."""
    if document_ids is None:
        document_ids = list(session.scalars(select(SourceDocument.id).where(
            SourceDocument.project_id == project.id, SourceDocument.kind.in_(("dpr_text", "spreadsheet"))).order_by(SourceDocument.id)))
    out = []
    for doc_id in dict.fromkeys(document_ids):    # de-duplicated, order kept
        doc = session.scalar(select(SourceDocument).where(SourceDocument.id == doc_id, SourceDocument.project_id == project.id))
        if doc is None:
            out.append({"document_id": doc_id, "outcome": "not_found", "run": None, "error": f"document {doc_id} not in project"})
            continue
        try:
            run, outcome = process_document(session, doc, upload_dir, pv)
            session.commit()
            out.append({"document_id": doc_id, "outcome": outcome, "run": run, "error": run.error})
        except IngestError as e:
            session.rollback()
            out.append({"document_id": doc_id, "outcome": "rejected", "run": None, "error": e.detail})
        except Exception as e:     # e.g. a database error: report it for this document, keep the rest of the batch
            session.rollback()
            out.append({"document_id": doc_id, "outcome": "failed", "run": None, "error": f"{type(e).__name__}: {e}"})
    return out


def evidence_metadata(doc: SourceDocument, ev: ProgressEvent) -> dict:
    """What the database holds about an event's evidence (no raw file needed)."""
    return {"event_id": ev.id, "document_id": doc.id, "filename": doc.filename, "kind": doc.kind, "sha256": doc.sha256,
            "source_ref": ev.source_ref, "source_text": ev.source_text, "span_start": ev.span_start, "span_end": ev.span_end,
            "source_cells": ev.source_cells}


def evidence(doc: SourceDocument, ev: ProgressEvent, upload_dir: Path, context: int = 2) -> dict:
    """Re-read the stored original and show exactly where the event came from.
    Raw file gone -> SourceUnavailable carrying the database-side evidence metadata (nothing is modified)."""
    try:
        data = read_blob(upload_dir, doc)
    except SourceUnavailable as e:
        e.extra["evidence"] = evidence_metadata(doc, ev)
        raise
    data, fmt = formats.normalize(data, doc.format)
    out = {"document_id": doc.id, "filename": doc.filename, "kind": doc.kind, "sha256": doc.sha256,
           "source_ref": ev.source_ref, "source_text": ev.source_text}
    if fmt == "txt":
        lines = dpr.text_lines(data.decode("utf-8"))
        ln = ev.source_ref["line"]
        line = lines[ln - 1] if 1 <= ln <= len(lines) else ""
        out |= {"line_number": ln, "line_text": line, "span_start": ev.span_start, "span_end": ev.span_end,
                "found_in_source": line[ev.span_start:ev.span_end] == ev.source_text,
                "context": [{"line": i + 1, "text": lines[i]} for i in range(max(0, ln - 1 - context), min(len(lines), ln + context))]}
    else:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb[ev.source_ref["sheet"]]
        cells = []
        for c in ev.source_cells or []:
            v = ws[c["cell"]].value
            v = v.date().isoformat() if isinstance(v, datetime) else v
            cells.append({**c, "value_in_file": v, "matches": v == c["value"]})
        wb.close()
        out |= {"sheet": ev.source_ref["sheet"], "row": ev.source_ref["row"], "cells": cells,
                "found_in_source": all(c["matches"] for c in cells)}
    return out
