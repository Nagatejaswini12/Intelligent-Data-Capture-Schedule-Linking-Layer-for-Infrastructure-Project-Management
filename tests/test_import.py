"""Database + importer tests against the Phase 0 schedule."""
from __future__ import annotations

import csv
from collections import Counter

import pytest
from sqlalchemy import func, select

from p2e.db.models import PlanDependency, PlanNode, PlanTag, Project, SourceDocument
from p2e.plan.importers import (REQUIRED_COLUMNS, ImportConflict, ScheduleValidationError, compare_schedules, read_schedule,
                                verify_import)
from p2e.plan.tags import extract_tags
from scripts.phase1.init_database import main as init_main
from tests.conftest import DATA_DATE, MANIFEST, SCHEDULE_CSV, SCHEDULE_XML, SYNTH, csv_rows, load

PROJECT = "CGS-EXP-01"


def count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


# --------------------------------------------------------------------------- database / clean import

def test_clean_import_creates_project_and_full_hierarchy(imported_db):
    _, sm = imported_db
    with sm() as s:
        p = s.scalar(select(Project))
        assert (p.code, p.data_date) == (PROJECT, DATA_DATE)
        assert count(s, PlanNode) == 469 == MANIFEST["stats"]["schedule_nodes"]
        assert count(s, PlanNode, PlanNode.node_type == "activity") == 317 == MANIFEST["stats"]["leaf_activities"]
        levels = Counter(s.scalars(select(PlanNode.level).where(PlanNode.node_type == "activity")))
        assert levels == {5: 302, 6: 15}
        assert Counter(s.scalars(select(PlanNode.node_type))) == {"activity": 317, "wbs": 149, "summary": 3}   # summaries: T-401, T-402, K-301
        src = s.scalar(select(SourceDocument))
        assert (src.kind, src.format, src.filename, src.node_count, src.activity_count) == ("schedule_import", "csv", "schedule.csv", 469, 317)


def test_codes_unique_and_hierarchy_valid(imported_db):
    _, sm = imported_db
    with sm() as s:
        assert verify_import(s, PROJECT) == []
        codes = list(s.scalars(select(PlanNode.code)))
        assert len(codes) == len(set(codes))
        nodes = {n.id: n for n in s.scalars(select(PlanNode))}
        for n in nodes.values():
            if n.parent_id is None:
                assert n.level == 1
            else:
                assert n.level == nodes[n.parent_id].level + 1
                assert nodes[n.parent_id].node_type != "activity"
        assert all(n.level <= 4 for n in nodes.values() if n.node_type == "wbs")   # L1–L4 hierarchy vs L5/L6 work


def test_database_matches_source_csv_exactly(imported_db):
    _, sm = imported_db
    with sm() as s:
        db = {n.code: n for n in s.scalars(select(PlanNode))}
        for r in csv_rows():
            n = db[r["node_id"]]
            assert (n.node_type, str(n.level), n.name, n.wbs_code) == (r["node_type"], r["level"], r["name"], r["wbs_code"])
            assert (n.parent.code if n.parent else "") == r["parent_id"]
            assert (n.planned_start.isoformat(), n.planned_finish.isoformat()) == (r["planned_start"], r["planned_finish"])
            assert (n.discipline or "", n.area or "") == (r["discipline"], r["area"])
            assert (n.actual_start.isoformat() if n.actual_start else "") == r["actual_start"]
        links = sum(len([p for p in r["predecessors"].split(";") if p]) for r in csv_rows())
        assert count(s, PlanDependency) == links


def test_tag_extraction_meets_phase1_gate():
    """Plan gate: tags extracted for >= 95% of tagged activities, with no spurious tags elsewhere."""
    with open(SYNTH / "ground_truth" / "activity_truth.csv", newline="", encoding="utf-8") as f:
        truth = {r["activity_id"]: sorted(t for t in r["canonical_tags"].split(";") if t) for r in csv.DictReader(f)}
    names = {r["node_id"]: r["name"] for r in csv_rows() if r["node_type"] == "activity"}
    tagged = [a for a in truth if truth[a]]
    exact = sum(extract_tags(names[a]) == truth[a] for a in tagged)
    assert exact / len(tagged) >= 0.95
    assert not [a for a in truth if not truth[a] and extract_tags(names[a])]
    assert extract_tags('Hydrotest line 24"-P-1203-A1A (TP-017)') == ["LINE-1203", "TP-017"]


def test_tags_stored_for_lookup(imported_db):
    _, sm = imported_db
    with sm() as s:
        codes = set(s.scalars(select(PlanNode.code).join(PlanTag).where(PlanTag.tag == "LINE-1203")))
        assert codes == {"PIP-A3-1203-ERC", "PIP-A3-1203-WLD", "PIP-A3-1203-HT", "PIP-A3-1203-RST"}


# --------------------------------------------------------------------------- idempotency / conflicts

def test_repeated_import_does_not_duplicate(empty_db):
    first, second = load(empty_db), load(empty_db)
    assert (first.status, second.status) == ("imported", "unchanged")
    with empty_db() as s:
        assert (count(s, PlanNode), count(s, Project), count(s, SourceDocument)) == (469, 1, 1)


def test_different_schedule_for_same_project_is_refused(empty_db):
    load(empty_db)
    with pytest.raises(ImportConflict):
        load(empty_db, SCHEDULE_XML)        # same project, different file
    with empty_db() as s:
        assert count(s, PlanNode) == 469


def test_mspdi_xml_is_compatible_and_importable(empty_db):
    assert compare_schedules(read_schedule(SCHEDULE_CSV).rows, read_schedule(SCHEDULE_XML).rows) == []
    r = load(empty_db, SCHEDULE_XML)
    assert (r.node_count, r.activity_count, r.dependency_count) == (469, 317, 211)
    with empty_db() as s:
        assert s.scalar(select(Project.data_date)) == DATA_DATE   # from MSPDI StatusDate


def test_init_command_is_repeatable(tmp_path, capsys):
    db = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    assert init_main(["--db", db]) == 0
    assert "status:        imported" in capsys.readouterr().out
    assert init_main(["--db", db]) == 0
    out = capsys.readouterr().out
    assert "status:        unchanged" in out and "nodes:         469" in out and "L5/L6 acts:    317" in out
    assert "compatible" in out


# --------------------------------------------------------------------------- malformed input is rejected, nothing written

def write_csv(path, rows, cols=REQUIRED_COLUMNS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def mutate(rows, code, **changes):
    return [dict(r, **changes) if r["node_id"] == code else r for r in rows]


ACT = "PIP-A3-1203-HT"
MALFORMED = {
    "duplicate id": (lambda rows: rows + [rows[-1]], "duplicate node/activity IDs"),
    "unknown parent": (lambda rows: mutate(rows, ACT, parent_id="NOPE"), "parent 'NOPE' does not exist"),
    "level not nested": (lambda rows: mutate(rows, ACT, level="6"), "does not follow parent level"),
    "level out of range": (lambda rows: mutate(rows, ACT, level="9"), "level '9' must be an integer 1-6"),
    "activity at L4": (lambda rows: mutate(rows, "CGS-EXP-01.A3.PIP.1203", node_type="activity", discipline="piping"),
                       "executable activity must be WBS level 5 or 6"),
    "bad node type": (lambda rows: mutate(rows, ACT, node_type="task"), "node_type 'task'"),
    "bad discipline": (lambda rows: mutate(rows, ACT, discipline="plumbing"), "discipline 'plumbing'"),
    "invalid date": (lambda rows: mutate(rows, ACT, planned_start="2026-02-30"), "invalid ISO date"),
    "start after finish": (lambda rows: mutate(rows, ACT, planned_start="2026-12-31", planned_duration_days=""),
                           "is after planned_finish"),
    "unknown predecessor": (lambda rows: mutate(rows, ACT, predecessors="XYZ:FS+0"), "predecessor 'XYZ'"),
    "finish without start": (lambda rows: mutate(rows, ACT, actual_finish="2026-08-01"), "actual_finish without"),
    "two roots": (lambda rows: mutate(rows, "CGS-EXP-01.A1", parent_id="", level="1"), "exactly one level-1 root"),
    "empty": (lambda rows: [], "schedule has no rows"),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_csv_rejected_and_nothing_written(case, tmp_path, empty_db):
    fn, expected = MALFORMED[case]
    path = write_csv(tmp_path / "bad.csv", fn(csv_rows()))
    with pytest.raises(ScheduleValidationError) as exc:
        load(empty_db, path)
    assert expected in str(exc.value)
    with empty_db() as s:
        assert count(s, PlanNode) == count(s, Project) == 0


def test_missing_column_rejected(tmp_path):
    path = write_csv(tmp_path / "bad.csv", csv_rows(), [c for c in REQUIRED_COLUMNS if c != "planned_finish"])
    with pytest.raises(ScheduleValidationError, match="missing required column.*planned_finish"):
        read_schedule(path)


@pytest.mark.parametrize("content, expected", [
    (b"<Project><Tasks>", "invalid or unsafe XML"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>', "invalid or unsafe XML"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', "invalid or unsafe XML"),
    (b"<root/>", "not an MS Project XML"),
])
def test_malformed_or_unsafe_xml_rejected(content, expected, tmp_path):
    path = tmp_path / "bad.xml"
    path.write_bytes(content)
    with pytest.raises(ScheduleValidationError, match=expected):
        read_schedule(path)


def test_unsupported_format_rejected(tmp_path):
    path = tmp_path / "schedule.xer"
    path.write_text("ERMHDR", encoding="utf-8")
    with pytest.raises(ScheduleValidationError, match="unsupported schedule format"):
        read_schedule(path)
