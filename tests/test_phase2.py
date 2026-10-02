"""Phase 2: ingestion checks, DPR + XLSX extraction, normalization, validation, persistence, traceability, idempotency,
batch processing, the authenticated API and the evaluation harness. Everything runs on the Phase 0 synthetic data."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from p2e.api.auth import parse_api_keys
from p2e.db.models import ExtractionRun, ProgressEvent, Project, SourceDocument
from p2e.extract import dpr
from p2e.extract.model import ExtractedItem
from p2e.extract.pipeline import extract_bytes, load_project_vocab, validate_item
from p2e.extract.rules import extract_tags, parse_date, parse_time
from p2e.ingest import service
from p2e.main import create_app
from tests.conftest import SYNTH, load, new_db

PV = load_project_vocab(SYNTH / "glossary.json")
REPORTS = sorted((SYNTH / "reports").glob("*.txt"))
SHEETS = sorted((SYNTH / "spreadsheets").glob("*.xlsx"))
KEY = "supervisor-key-0123456789"
H = {"X-API-Key": KEY}

DPR_TEXT = """CGS EXPANSION PROJECT - DAILY PROGRESS REPORT
Discipline: Piping
Date: 2026-09-10    Report No: PIP/DPR/010
Weather: Clear

Work Done Today:
1. Line 1203 hydrotest started at 10:00 today
2. Spool erection 1205 – 3 spools erected
3. Rebar & shutt. for P-101A fdn compl. yesterday; L-1207 fit-up started
4. something nobody can parse
- Nil

Hold / Constraints:
- Line 1209 erection on hold – welders shortage

Plan for Tomorrow:
1. Line 1210 erection started
"""


def xlsx_bytes(rows: list[list], title: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


# ----------------------------------------------------------------------------- normalization

@pytest.mark.parametrize("text,ref,expected", [
    ("14/09/2026", None, date(2026, 9, 14)), ("14.09.26", None, date(2026, 9, 14)), ("14-Sep-26", None, date(2026, 9, 14)),
    ("14-Sep", date(2026, 1, 1), date(2026, 9, 14)), ("Sep 14, 2026", None, date(2026, 9, 14)), ("2026-09-14", None, date(2026, 9, 14)),
    ("14th Sept 2026", None, date(2026, 9, 14)), ("14/9", date(2026, 1, 1), date(2026, 9, 14)),
    ("14/9", None, None), ("31/02/2026", None, None), ("pending", None, None), ("N/A", None, None),
])
def test_parse_date(text, ref, expected):
    assert parse_date(text, ref) == expected


@pytest.mark.parametrize("text,expected", [("10:00", "10:00"), ("2 pm", "14:00"), ("9.30am", "09:30"), ("12 pm", "12:00"),
                                           ("25:00", None), ("soon", None)])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text,expected", [
    ('24"-P-1203-A1A spool', ["LINE-1203"]), ("P101 A pump", ["P-101A"]), ("flow transmitter 2031", ["FT-2031"]),
    ("north cable trench", ["CT-N"]), ("MCC-2 and DCS panel", ["DCS", "MCC-2"]), ("excavation for road", []),
])
def test_extract_tags(text, expected):
    assert extract_tags(text) == expected


# ----------------------------------------------------------------------------- DPR parsing

def test_dpr_grammar_items_and_fields():
    res = dpr.extract_dpr(DPR_TEXT, PV.vocab)
    assert (res.report_date, res.discipline_group, res.meta["layout"]) == (date(2026, 9, 10), "piping", "structured")
    by = {(i.source_ref["line"], i.source_ref["index"]): i for i in res.items}
    hydro = by[(7, 0)]
    assert (hydro.event_type, hydro.event_date, hydro.event_time, hydro.tags) == ("start", date(2026, 9, 10), "10:00", ["LINE-1203"])
    spools = by[(8, 0)]
    assert (spools.event_type, spools.quantity, spools.unit) == ("progress", 3.0, "spools")
    # "&" inside an activity is not a separator; "; " between two complete items is
    assert by[(9, 0)].activity_text == "Rebar & shutt. for P-101A fdn"
    assert (by[(9, 0)].event_type, by[(9, 0)].event_date) == ("finish", date(2026, 9, 9))
    assert by[(9, 1)].tags == ["LINE-1207"] and by[(9, 1)].event_type == "start"
    hold = by[(14, 0)]
    assert (hold.event_type, hold.delay_reason, hold.delay_category) == ("hold", "welders shortage", "manpower")
    assert (16 in {i.source_ref["line"] for i in res.items}) is False        # "Plan for tomorrow" is not progress
    assert [i.source_ref for i in res.issues] == [{"line": 10}]              # unparseable item line kept as an issue
    lines = DPR_TEXT.split("\n")
    for it in res.items:                                                     # span is verbatim on the referenced line
        a, b = it.span
        assert lines[it.source_ref["line"] - 1][a:b] == it.source_text


def test_dpr_without_report_date_never_guesses():
    res = dpr.extract_dpr("Discipline: Civil\n\nWork Done Today:\n1. PCC for T-403 fdn compl. today\n", PV.vocab)
    assert res.report_date is None
    it = res.items[0]
    assert it.event_date is None and it.problems == ["report date unknown, cannot resolve event date"]
    assert validate_item(it, lines=None, report_date=None, project_start=None)   # -> invalid, kept with reason


def test_all_synthetic_dprs_parse():
    assert len(REPORTS) == 81
    gt = {Path(d["path"]).name: len(d["items"]) for d in json.loads(
        (SYNTH / "ground_truth" / "expected_extraction.json").read_text(encoding="utf-8"))["documents"]}
    for path in REPORTS:
        m = re.match(r"dpr_(\d{4}-\d{2}-\d{2})_(\w+)\.txt", path.name)
        text = path.read_text(encoding="utf-8")
        res = extract_bytes(path.read_bytes(), ".txt", PV)
        assert res.report_date == date.fromisoformat(m[1]), path.name
        assert res.discipline_group == m[2], path.name
        assert len(res.items) == gt[path.name] and not res.issues, path.name   # HSE reports carry no progress items
        lines = text.split("\n")
        for it in res.items:
            assert validate_item(it, lines=lines, report_date=res.report_date, project_start=None) == [], (path.name, it)


# ----------------------------------------------------------------------------- XLSX parsing

def test_synthetic_sheets_parse_with_cell_evidence():
    templates = {}
    for path in SHEETS:
        res = extract_bytes(path.read_bytes(), ".xlsx", PV)
        templates[path.stem] = {s["template"] for s in res.meta["sheets"].values()} - {None}
        assert res.items and not res.issues
        wb = load_workbook(path, data_only=True)
        for it in res.items:
            assert it.source_ref["sheet"] in wb.sheetnames and it.source_ref["row"] > 1
            for c in it.source_cells:                     # every evidence cell is the real cell in the workbook
                v = wb[it.source_ref["sheet"]][c["cell"]].value
                assert (v.date().isoformat() if hasattr(v, "date") else v) == c["value"]
                assert c["cell"] == f"{c['column']}{it.source_ref['row']}"
    assert templates == {"electrical_cable_log": {"cable_log"}, "instrument_installation_register": {"instrument_register"},
                         "piping_spool_erection_tracker": {"spool_tracker"}}


def test_renamed_headers_still_parse_and_unknown_sheet_is_reported():
    data = xlsx_bytes([["S.No", "Line No", "Spool No", "Location", "Erection Date", "Status"],
                       [1, '6"-P-1301-A1A', "1301-SP-01", "Area-2", date(2026, 9, 3), "Done"],
                       [2, '6"-P-1301-A1A', "1301-SP-02", "Area-2", None, "WIP"]])
    res = extract_bytes(data, ".xlsx", PV)
    assert len(res.items) == 1
    it = res.items[0]
    assert (it.event_date, it.tags, it.area, it.quantity, it.unit) == (date(2026, 9, 3), ["LINE-1301"], "A2", 1.0, "spools")
    res = extract_bytes(xlsx_bytes([["Summary"], ["total", 4]]), ".xlsx", PV)
    assert not res.items and res.issues and "no sheet" in res.issues[0].message


# ----------------------------------------------------------------------------- validation

def item(**kw) -> ExtractedItem:
    base = dict(source_ref={"sheet": "S", "row": 2}, source_text="PT-1104 | 2026-09-01", activity_text="PT-1104", event_type="finish",
                event_date=date(2026, 9, 1), date_text="2026-09-01", discipline="instrumentation", tags=["PT-1104"],
                source_cells=[{"cell": "B2", "value": "PT-1104"}])
    return ExtractedItem(**(base | kw))


@pytest.mark.parametrize("kw,fragment", [
    ({"event_date": date(2026, 9, 20)}, "after the report date"),
    ({"event_date": date(2025, 1, 1)}, "implausibly early"),
    ({"event_type": "done"}, "event type"),
    ({"discipline": "plumbing"}, "discipline"),
    ({"quantity": -3.0, "unit": "m"}, "positive number"),
    ({"quantity": 3.0, "unit": "kg"}, "known unit"),
    ({"unit": "m"}, "unit without quantity"),
    ({"tags": ["pt1104"]}, "non-canonical"),
    ({"activity_text": "something else"}, "activity text"),
    ({"source_cells": None}, "no source cells"),
    ({"event_date": None}, "no event date"),
    ({"not_before": date(2026, 9, 5), "not_before_label": "pull date"}, "before the pull date"),
    ({"delay_reason": "rain"}, "delay reason without category"),
])
def test_validation_rules(kw, fragment):
    assert validate_item(item(), lines=None, report_date=date(2026, 9, 16), project_start=date(2026, 7, 1)) == []
    errors = validate_item(item(**kw), lines=None, report_date=date(2026, 9, 16), project_start=date(2026, 7, 1))
    assert any(fragment in e for e in errors), errors


def test_validation_checks_text_span():
    it = item(source_ref={"line": 1, "index": 0}, source_text="PT-1104 mounted", activity_text="PT-1104", span=(0, 15), source_cells=None)
    assert validate_item(it, lines=["PT-1104 mounted today"], report_date=None, project_start=None) == []
    assert "source text not found" in validate_item(it, lines=["something else"], report_date=None, project_start=None)[0]


# ----------------------------------------------------------------------------- ingestion checks

@pytest.mark.parametrize("name,data,exc", [
    ("report.pdf", b"%PDF", service.UnsupportedFile),
    ("report", b"x", service.UnsupportedFile),
    ("report.txt", b"", service.MalformedFile),
    ("report.txt", b"abc\x00def", service.MalformedFile),
    ("report.txt", "café".encode("latin-1"), service.MalformedFile),
    ("report.txt", b"x" * (service.MAX_UPLOAD_BYTES + 1), service.FileTooLarge),
    ("sheet.xlsx", b"not a zip", service.MalformedFile),
    ("sheet.xlsx", zip_bytes({"hello.txt": b"hi"}), service.MalformedFile),
    ("sheet.xlsx", zip_bytes({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<x/>", "xl/vbaProject.bin": b"\0"}),
     service.UnsupportedFile),
    ("sheet.xlsx", zip_bytes({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<broken"}), service.MalformedFile),
], ids=["pdf", "no-ext", "empty", "binary", "latin1", "too-large", "not-zip", "no-workbook", "macro", "broken-xml"])
def test_check_content_rejects(name, data, exc):
    with pytest.raises(exc):
        service.check_content(name, data)


def test_check_content_accepts_and_sanitizes_names():
    assert service.check_content("a.TXT", REPORTS[0].read_bytes()) == ("dpr_text", "txt")
    assert service.check_content("b.xlsx", SHEETS[0].read_bytes()) == ("spreadsheet", "xlsx")
    assert service.safe_filename("..\\..\\evil/report\x07.txt") == "report.txt"
    assert service.safe_filename(None) == "upload"


# ----------------------------------------------------------------------------- persistence, traceability, idempotency

@pytest.fixture
def db(tmp_path):
    engine, sm = new_db(tmp_path / "p2.db")
    load(sm)
    yield sm, tmp_path / "uploads"
    engine.dispose()


def ingest(session, uploads: Path, path: Path) -> SourceDocument:
    project = session.scalar(select(Project))
    return service.ingest_upload(session, project, path.name, path.read_bytes(), "supervisor", uploads)


def test_persist_and_trace_every_event(db):
    sm, uploads = db
    with sm() as session:
        docs = [ingest(session, uploads, p) for p in (REPORTS[0], *SHEETS)]
        for d in docs:
            run, outcome = service.process_document(session, d, uploads, PV)
            assert outcome == "processed" and run.status == "succeeded"
            expected = extract_bytes((REPORTS[0] if d.format == "txt" else SYNTH / "spreadsheets" / d.filename).read_bytes(),
                                     "." + d.format, PV)
            assert run.events_total == len(expected.items) == run.events_valid + run.events_invalid
            assert d.status == "extracted" and d.report_date == expected.report_date
        session.commit()
        events = session.scalars(select(ProgressEvent)).all()
        assert events and all(e.extraction_method and e.parser_version and e.locator_key for e in events)
        for e in events:
            ev = service.evidence(e.document, e, uploads)
            assert ev["found_in_source"] is True and ev["sha256"] == e.document.sha256
        txt = next(e for e in events if e.span_start is not None)
        ev = service.evidence(txt.document, txt, uploads)
        assert ev["line_text"][txt.span_start:txt.span_end] == txt.source_text and ev["context"]


def test_idempotent_upload_and_processing(db, monkeypatch):
    sm, uploads = db
    with sm() as session:
        doc = ingest(session, uploads, REPORTS[1])
        session.commit()
        with pytest.raises(service.DuplicateDocument) as e:
            ingest(session, uploads, REPORTS[1])
        assert e.value.extra["existing_document_id"] == doc.id
        session.rollback()
        run1, out1 = service.process_document(session, doc, uploads, PV)
        n = session.scalar(select(func.count()).select_from(ProgressEvent))
        run2, out2 = service.process_document(session, doc, uploads, PV)
        assert (out1, out2, run2.id) == ("processed", "unchanged", run1.id)
        monkeypatch.setattr(dpr, "PARSER_VERSION", "9.9.9")          # new parser version -> events replaced, never duplicated
        run3, out3 = service.process_document(session, doc, uploads, PV)
        session.commit()
        assert out3 == "processed" and run3.id != run1.id
        assert session.scalar(select(func.count()).select_from(ProgressEvent)) == n
        assert set(session.scalars(select(ProgressEvent.parser_version))) == {"9.9.9"}
        assert session.scalar(select(func.count()).select_from(SourceDocument).where(SourceDocument.kind == "dpr_text")) == 1
        assert len(list(uploads.iterdir())) == 1                       # one stored blob


def test_tampered_store_fails_safely_then_recovers(db):
    sm, uploads = db
    with sm() as session:
        doc = ingest(session, uploads, REPORTS[2])
        blob = uploads / doc.storage_uri
        original = blob.read_bytes()
        blob.write_bytes(original + b"tampered")
        run, outcome = service.process_document(session, doc, uploads, PV)
        assert (outcome, run.status, doc.status) == ("failed", "failed", "failed") and "hash" in run.error
        assert session.scalar(select(func.count()).select_from(ProgressEvent)) == 0
        blob.write_bytes(original)
        run, outcome = service.process_document(session, doc, uploads, PV)   # a failed run never blocks a retry
        assert outcome == "processed" and doc.status == "extracted" and doc.error is None


def test_batch_commits_each_document(db):
    sm, uploads = db
    with sm() as session:
        ids = [ingest(session, uploads, p).id for p in REPORTS[:3]]
        schedule_id = session.scalar(select(SourceDocument.id).where(SourceDocument.kind == "schedule_import"))
        session.commit()
        project = session.scalar(select(Project))
        res = service.process_batch(session, project, uploads, PV, [*ids, schedule_id, 99999, ids[0]])
        assert [r["outcome"] for r in res] == ["processed"] * 3 + ["rejected", "not_found"]
        assert {r["outcome"] for r in service.process_batch(session, project, uploads, PV)} == {"unchanged"}
    with sm() as fresh:                                                   # committed, visible to a new session
        assert fresh.scalar(select(func.count()).select_from(ExtractionRun)) == 3


# ----------------------------------------------------------------------------- API

@pytest.fixture(scope="module")
def api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    engine, sm = new_db(tmp / "api.db")
    code = load(sm).project_code
    engine.dispose()
    app = create_app(f"sqlite:///{(tmp / 'api.db').as_posix()}", api_keys={KEY: "supervisor"}, upload_dir=tmp / "uploads")
    with TestClient(app) as c:
        yield c, f"/api/v1/projects/{code}"
    app.state.engine.dispose()


def upload(c, base, path: Path, headers=H):
    return c.post(f"{base}/documents", files={"file": (path.name, path.read_bytes())}, headers=headers)


def test_api_auth(api, tmp_path):
    c, base = api
    assert c.get(f"{base}/documents").status_code == 401
    r = c.get(f"{base}/documents", headers={"X-API-Key": "wrong-key-0123456789"})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert upload(c, base, REPORTS[0], headers={}).status_code == 401
    closed = create_app(f"sqlite:///{(tmp_path / 'x.db').as_posix()}", api_keys={}, upload_dir=tmp_path)
    with TestClient(closed) as c2:                                     # no keys configured -> fail closed, never public
        assert c2.get(f"{base}/documents", headers=H).status_code == 503
    closed.state.engine.dispose()
    for bad in ("root:0123456789abcdef", "admin:short", "no-separator"):    # keys come only from P2E_API_KEYS, validated
        with pytest.raises(ValueError):
            parse_api_keys(bad)


def test_api_upload_process_events_evidence(api):
    c, base = api
    r = upload(c, base, REPORTS[3])
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (doc["status"], doc["kind"], doc["latest_run"]) == ("received", "dpr_text", None)
    dup = upload(c, base, REPORTS[3])
    assert dup.status_code == 409 and dup.json()["detail"]["existing_document_id"] == doc["id"]
    bad = c.post(f"{base}/documents", files={"file": ("x.exe", b"MZ")}, headers=H)
    assert bad.status_code == 415

    p = c.post(f"{base}/documents/{doc['id']}/process", headers=H).json()
    assert p["outcome"] == "processed" and p["run"]["events_total"] > 0
    assert c.post(f"{base}/documents/{doc['id']}/process", headers=H).json()["outcome"] == "unchanged"
    st = c.get(f"{base}/documents/{doc['id']}/status", headers=H).json()
    assert (st["status"], st["runs"], st["issues"]) == ("extracted", 1, [])
    assert c.get(f"{base}/documents/{doc['id']}", headers=H).json()["report_date"] == REPORTS[3].name[4:14]
    assert c.get(f"{base}/documents?kind=dpr_text&status=extracted", headers=H).json()["total"] >= 1

    events = c.get(f"{base}/events?document_id={doc['id']}", headers=H).json()
    assert events["total"] == p["run"]["events_total"]
    e = events["items"][0]
    assert e["source_type"] == "dpr_text" and e["document_filename"] == REPORTS[3].name
    assert c.get(f"{base}/events/{e['id']}", headers=H).json() == e
    ev = c.get(f"{base}/events/{e['id']}/evidence", headers=H).json()
    assert ev["found_in_source"] and ev["line_text"][ev["span_start"]:ev["span_end"]] == e["source_text"]
    assert c.get(f"{base}/events/999999", headers=H).status_code == 404
    assert c.get(f"{base}/documents/999999", headers=H).status_code == 404
    assert c.get("/api/v1/projects/NOPE/events", headers=H).status_code == 404


def test_api_batch_filters_and_sheet_evidence(api):
    c, base = api
    ids = [upload(c, base, p).json()["id"] for p in SHEETS]
    r = c.post(f"{base}/documents/process", json={"document_ids": [*ids, 424242]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"processed": 3, "not_found": 1}
    assert set(c.post(f"{base}/documents/process", headers=H).json()["counts"]) == {"unchanged"}
    assert c.post(f"{base}/documents/process", json={"document_ids": list(range(1001))}, headers=H).status_code == 422

    sheet = c.get(f"{base}/events?source_type=spreadsheet&discipline=instrumentation&event_type=finish", headers=H).json()
    assert sheet["total"] > 0 and all(i["discipline"] == "instrumentation" and i["reported_actual_finish"] for i in sheet["items"])
    ev = c.get(f"{base}/events/{sheet['items'][0]['id']}/evidence", headers=H).json()
    assert ev["found_in_source"] and ev["sheet"] == "Register" and all(x["matches"] for x in ev["cells"])
    dated = c.get(f"{base}/events?date_from=2026-09-05&date_to=2026-09-06&limit=1000", headers=H).json()
    assert dated["items"] and all("2026-09-05" <= i["event_date"] <= "2026-09-06" for i in dated["items"])
    page = c.get(f"{base}/events?limit=2&offset=1", headers=H).json()
    assert len(page["items"]) == 2 and page["offset"] == 1
    assert c.get(f"{base}/events?validation_status=maybe", headers=H).status_code == 422
    schedule = c.get(f"{base}/documents?kind=schedule_import", headers=H).json()["items"][0]
    assert c.post(f"{base}/documents/{schedule['id']}/process", headers=H).status_code == 415


def test_phase1_routes_stay_public(api):
    c, base = api
    assert c.get("/health").status_code == 200
    assert c.get(base).status_code == 200 and c.get(f"{base}/plan?limit=1").status_code == 200


# ----------------------------------------------------------------------------- evaluation

def test_evaluation_report():
    import scripts.phase2.evaluate_extraction as ev
    rep = ev.evaluate(SYNTH)
    for s in ("dev", "test", "all"):
        r = rep["splits"][s]
        assert r["expected_items"] > 0 and r["recall"] >= 0.9 and r["precision"] >= 0.9           # Phase 2 exit gate
        for f in ("activity_text", "event_type", "date"):
            assert r["field_exact"][f] >= 0.9
    assert rep["splits"]["all"]["expected_items"] == rep["splits"]["dev"]["expected_items"] + rep["splits"]["test"]["expected_items"]
    assert rep["ground_truth_gaps"]["count"] == sum(rep["ground_truth_gaps"]["by_field"].values())


def test_ground_truth_gap_needs_independent_evidence():
    from scripts.phase2.evaluate_extraction import gt_gap
    assert gt_gap("time", None, "10:00", "", "", truth_time="10:00")
    assert not gt_gap("time", None, "10:00", "", "", truth_time="14:00")      # wrong time stays an extractor error
    assert gt_gap("area", None, "A3", "", "", stated_area="temp DB A3 start")
    assert not gt_gap("area", None, "A3", "", "", stated_area="A1")            # invented area stays an extractor error
    assert gt_gap("source_span", "a | b", "a | x | b", "a | x | b", "a | b")
    assert not gt_gap("date", None, "2026-09-01", "", "")
