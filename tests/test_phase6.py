"""Phase 6: actual-progress dataset, dashboard, productivity, delay causes, knowledge entries (+ OKF), memory Q&A with
citations, and the exit gate (10 benchmark questions vs the ground truth). Synthetic project, read-only over the history."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from sqlalchemy import func, select

from p2e.analytics import metrics, qa
from p2e.db.models import AuditLog, EventLink, PlanNode, ProgressEvent
from p2e.link.context import get_context
from p2e.memory import knowledge, okf
from tests.test_phase3 import GLOSSARY, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase5 import api, linked  # noqa: F401
from tests.test_watch import applied  # noqa: F401

AS_OF = date(2026, 9, 16)


def ask(session, project, q, as_of=AS_OF):
    return qa.answer(session, project, q, get_context(session, project, GLOSSARY), as_of)


def test_dataset_rows(applied):
    session, project, _ = applied
    rows = metrics.dataset(session, project, AS_OF)
    assert len(rows) == session.scalar(select(func.count()).select_from(PlanNode).where(PlanNode.node_type == "activity"))
    for r in rows:
        if r["actual_finish"]:
            assert r["status"] == "completed" and r["actual_duration_days"] == (r["actual_finish"] - r["actual_start"]).days + 1
            assert r["duration_ratio"] == round(r["actual_duration_days"] / r["planned_duration_days"], 3)
        if r["actual_start"]:
            assert r["start_variance_days"] == (r["actual_start"] - r["planned_start"]).days
    early = {r["code"]: r for r in metrics.dataset(session, project, date(2026, 8, 31))}
    assert all(r["actual_start"] is None or r["actual_start"] <= date(2026, 8, 31) for r in early.values())   # as-of honoured
    assert any(r["delay_categories"] for r in rows) and any(r["reported_qty"] for r in rows)


def test_dashboard(applied):
    session, project, _ = applied
    d = metrics.dashboard(session, project, AS_OF)
    total = sum(v["activities"] for v in d["by_discipline"].values())
    assert total == sum(v["activities"] for v in d["by_area"].values()) == len(metrics.dataset(session, project, AS_OF))
    for v in d["by_discipline"].values():
        assert v["activities"] == v.get("completed", 0) + v.get("in_progress", 0) + v.get("not_started", 0)
    assert set(d["freshness"]) == {"civil", "piping", "electrical", "instrumentation", "mechanical", "hse"}
    assert all(f["last_report"] <= AS_OF for f in d["freshness"].values())
    pending = session.scalar(select(func.count()).select_from(EventLink).where(EventLink.state == "pending"))
    assert d["review_backlog"]["pending_events"] == pending and d["review_backlog"]["pending_conflicts"] > 0


def test_productivity_and_rates(applied):
    session, project, _ = applied
    rows = metrics.dataset(session, project, AS_OF)
    p = metrics.productivity(rows)["durations"]
    bf = p["Backfilling"]
    done = [r for r in rows if r["activity_type"] == "Backfilling" and r["actual_duration_days"]]
    assert bf["completed"] == len(done) and bf["mean_actual_days"] == round(sum(r["actual_duration_days"] for r in done) / len(done), 2)
    node = session.scalar(select(PlanNode).where(PlanNode.code == "PIP-A4-1405-ERC"))
    rate = metrics.quantity_rate(session, project, [node.id], AS_OF)["spools"]
    assert rate["per_day"] == round(rate["quantity"] / rate["days"], 2) and rate["event_ids"]


def test_knowledge_entries_cite_real_records(applied):
    session, project, _ = applied
    entries = knowledge.entries(session, project, AS_OF)
    kinds = {e["kind"] for e in entries}
    assert kinds == {"duration", "delays"}
    codes = {c for (c,) in session.execute(select(PlanNode.code))}
    for e in entries:
        assert e["citations"] and e["text"]
        for c in e["citations"]:
            assert (c["id"] in codes) if c["kind"] == "activity" else session.get(ProgressEvent, c["id"]) is not None
    files = okf.build_bundle(session, project, get_context(session, project, GLOSSARY))
    assert okf.conformance_problems(files) == [] and "knowledge/index.md" in files
    assert any(k.startswith("knowledge/duration/") for k in files) and any(k.startswith("knowledge/delays/") for k in files)


@pytest.mark.parametrize("question,intent", [
    ("How long did backfilling take?", "duration"),
    ("What delayed piping work?", "delays"),
    ("How many spools per day were erected on line 1405?", "rate"),
    ("Which civil activities started late?", "late"),
    ("How many electrical activities are completed?", "count"),
    ("What is the status of P-101A grouting?", "status"),
    ("When did each discipline last report?", "freshness"),
    ("Tell me about heavy rain", "narrative"),
])
def test_every_answer_is_cited(applied, question, intent):
    session, project, _ = applied
    a = ask(session, project, question)
    assert a["intent"] == intent and a["citations"] and a["answer"]
    for c in a["citations"]:
        assert c["kind"] in ("activity", "event", "document") and c["id"] is not None


def test_no_records_no_claims_and_no_injection(applied):
    session, project, _ = applied
    a = ask(session, project, "How long did 24-inch line hydrotests actually take?")
    assert a["filters"]["size"] == "24" and a["citations"] == [] and a["values"] == {}
    z = ask(session, project, "What delayed the zeppelin?")
    assert z["citations"] == [] and "zeppelin" in z["answer"]                # unknown subject: no project-wide guess
    assert ask(session, project, "What delayed the project?")["values"]["holds"] == len(metrics.delay_events(session, project))
    before = session.scalar(select(func.count()).select_from(AuditLog)), session.scalar(select(func.count()).select_from(PlanNode))
    ask(session, project, "status of x'; DROP TABLE plan_node; --")
    assert (session.scalar(select(func.count()).select_from(AuditLog)), session.scalar(select(func.count()).select_from(PlanNode))) == before
    zero = ask(session, project, "How many hydrotests were in progress on 2026-08-31?")
    assert zero["values"]["count"] == 0 and zero["citations"]               # a zero is shown with the population it counted
    assert zero["filters"]["as_of"] == date(2026, 8, 31)


def test_api(api):
    c, base, session, project = api
    c.post(f"{base}/apply", json={"as_of": "2026-09-16"}, headers=SUP)
    d = c.get(f"{base}/analytics/dashboard?as_of=2026-09-16", headers=SUP).json()
    assert d["by_discipline"] and d["freshness"]["piping"]["last_report"] == "2026-09-16"
    text = c.get(f"{base}/analytics/dataset.csv?as_of=2026-09-16", headers=SUP).text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == metrics.DATASET_COLUMNS and len(rows) == len(metrics.dataset(session, project, AS_OF))
    p = c.get(f"{base}/analytics/productivity?as_of=2026-09-16", headers=SUP).json()
    assert p["durations"] and p["rates"]
    dl = c.get(f"{base}/analytics/delays?as_of=2026-09-16", headers=SUP).json()
    assert sum(dl["by_category"].values()) == len(dl["reports"]) > 0 and dl["recurring"]
    assert c.get(f"{base}/knowledge?as_of=2026-09-16", headers=SUP).json()
    a = c.post(f"{base}/memory/ask", json={"question": "What delayed piping work?", "as_of": "2026-09-16"}, headers=SUP).json()
    assert a["intent"] == "delays" and a["citations"]
    assert c.post(f"{base}/memory/ask", json={"question": "x"}, headers=SUP).status_code == 422
    assert c.get(f"{base}/analytics/dashboard").status_code == 401


def test_benchmark_exit_gate():
    from scripts.phase6.evaluate_qa import evaluate
    from tests.conftest import SYNTH
    rep = evaluate(SYNTH)
    assert rep["passed"] == rep["total"] == 10, [r for r in rep["results"] if not r["passed"]]
