"""Phase 3.2: the evidence endpoint stays controlled when a stored raw source file is missing or unreadable.
Every test works on a per-test copy of the upload store and database; the real synthetic dataset is never touched."""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from p2e.db.models import EventLink, ProgressEvent, Project, SourceDocument
from p2e.ingest import service
from p2e.link import service as linking
from p2e.main import create_app
from tests.conftest import SYNTH, load, new_db
from tests.test_phase3 import GLOSSARY, KEYS, SUP, db, world  # noqa: F401  (shared fixtures)

EVIDENCE_KEYS = {"document_id", "filename", "kind", "sha256", "source_ref", "source_text", "found_in_source", "line_number",
                 "line_text", "span_start", "span_end", "context", "sheet", "row", "cells"}


@pytest.fixture
def api(db, world, tmp_path):
    """Linked project + its own copy of the raw upload store."""
    session, project = db
    linking.link_events(session, project, GLOSSARY)
    session.commit()
    uploads = tmp_path / "uploads"
    shutil.copytree(world[0] / "uploads", uploads)
    app = create_app(session.get_bind().url.render_as_string(), api_keys=dict(KEYS), upload_dir=uploads)
    with TestClient(app, raise_server_exceptions=False) as c:      # a crash would show up as a 500, not an exception
        yield c, f"/api/v1/projects/{project.code}", session, uploads
    app.state.engine.dispose()


def event_by_text(session, start: str) -> ProgressEvent:
    return session.scalar(select(ProgressEvent).where(ProgressEvent.source_text.startswith(start)))


def snapshot(session, ev: ProgressEvent) -> tuple:
    session.expire_all()
    e = session.get(ProgressEvent, ev.id)
    d = session.get(SourceDocument, e.source_document_id)
    l = session.scalar(select(EventLink).where(EventLink.progress_event_id == e.id))
    return ((e.source_document_id, e.source_text, e.source_ref, e.span_start, e.span_end, e.source_cells, e.event_date,
             e.event_type, e.quantity, e.validation_status),
            (d.status, d.sha256, d.storage_uri, d.error),
            (l.decision, l.state, l.plan_node_id, l.confidence, l.conflict, l.reasons))


def test_A_F_existing_file_unchanged_behaviour(api):
    c, base, session, _ = api
    for ev in (event_by_text(session, "Spool erection 16 inch line 1211"), event_by_text(session, '16"-P-1211-A1A | 1211-SP-02')):
        r = c.get(f"{base}/events/{ev.id}/evidence", headers=SUP)
        assert r.status_code == 200 and set(r.json()) == EVIDENCE_KEYS and r.json()["found_in_source"] is True
        assert r.json()["source_text"] == ev.source_text and r.json()["document_id"] == ev.source_document_id


@pytest.mark.parametrize("kind", ["txt", "xlsx"])
def test_B_C_D_E_G_missing_file_is_controlled(api, kind):
    c, base, session, uploads = api
    ev = event_by_text(session, "Spool erection 16 inch line 1211" if kind == "txt" else '16"-P-1211-A1A | 1211-SP-02')
    before = snapshot(session, ev)
    (uploads / ev.document.storage_uri).unlink()                       # raw file removed after ingestion
    r = c.get(f"{base}/events/{ev.id}/evidence", headers=SUP)
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    detail = r.json()["detail"]
    assert detail["status"] == "source_unavailable" and detail["reason"] == "raw_source_file_missing"
    assert detail["document_id"] == ev.source_document_id
    meta = detail["evidence"]                                          # E: database-side evidence still served
    assert meta["event_id"] == ev.id and meta["source_text"] == ev.source_text and meta["source_ref"] == ev.source_ref
    assert meta["sha256"] == ev.document.sha256 and meta["filename"] == ev.document.filename
    assert (meta["span_start"], meta["span_end"], meta["source_cells"]) == (ev.span_start, ev.span_end, ev.source_cells)
    for leak in (str(uploads), uploads.as_posix(), ev.document.storage_uri, "Traceback", "FileNotFoundError", "Errno"):
        assert leak not in r.text                                      # no paths / internals
    assert c.get(f"{base}/events/{ev.id}/evidence", headers=SUP).json() == r.json()       # G: deterministic
    assert snapshot(session, ev) == before                                                 # D: nothing changed
    assert c.get(f"{base}/events/{ev.id}", headers=SUP).status_code == 200                # event still served
    assert c.get(f"{base}/links/{ev.id}", headers=SUP).status_code == 200
    assert c.get(f"{base}/events/999999/evidence", headers=SUP).json()["detail"] == "progress event 999999 not found in project CGS-EXP-01"


def test_unreadable_file_is_controlled(api):
    c, base, session, uploads = api
    ev = event_by_text(session, "Spool erection 16 inch line 1211")
    blob = uploads / ev.document.storage_uri
    blob.unlink()
    blob.mkdir()                                                       # something unreadable in the file's place
    r = c.get(f"{base}/events/{ev.id}/evidence", headers=SUP)
    assert r.status_code == 404 and r.json()["detail"]["reason"] == "raw_source_file_unreadable"
    assert str(uploads) not in r.text and "Errno" not in r.text


def test_H_conflict_evidence_stays_inspectable(api):
    c, base, session, uploads = api
    sheet = event_by_text(session, '16"-P-1211-A1A | 1211-SP-02')
    link_before = c.get(f"{base}/links/{sheet.id}", headers=SUP).json()
    conflict = link_before["conflict"]
    assert conflict and len(conflict["events"]) == 2
    (uploads / sheet.document.storage_uri).unlink()                    # the spreadsheet side is gone
    for e in conflict["events"]:
        r = c.get(f"{base}/events/{e['event_id']}/evidence", headers=SUP)
        if e["source_type"] == "spreadsheet":
            assert r.status_code == 404 and r.json()["detail"]["evidence"]["source_text"] == e["source_text"]
        else:
            assert r.status_code == 200 and r.json()["found_in_source"] is True
    assert c.get(f"{base}/links/{sheet.id}", headers=SUP).json() == link_before            # conflict record unchanged
    assert c.post(f"{base}/links/run", headers=SUP).json()["conflicts"]["routed_to_review"] == 0


def test_processing_a_missing_file_fails_cleanly_without_paths(tmp_path):
    engine, sm = new_db(tmp_path / "p.db")
    load(sm)
    uploads = tmp_path / "uploads"
    with sm() as session:
        doc = service.ingest_upload(session, session.scalar(select(Project)), "r.txt",
                                    (SYNTH / "reports" / "dpr_2026-09-01_civil.txt").read_bytes(), "supervisor", uploads)
        (uploads / doc.storage_uri).unlink()
        run, outcome = service.process_document(session, doc, uploads, linking_vocab())
        assert (outcome, run.status, doc.status) == ("failed", "failed", "failed")
        assert "SourceUnavailable" in run.error and str(uploads) not in run.error and str(tmp_path) not in doc.error
    engine.dispose()


def linking_vocab():
    from p2e.extract.pipeline import load_project_vocab
    return load_project_vocab(SYNTH / "glossary.json")
