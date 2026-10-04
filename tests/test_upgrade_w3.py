"""Upgrade W3: project-manager report (content, escaping, API, CLI)."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from p2e.analytics import report
from tests.test_phase3 import KEYS, SUP, db, world  # noqa: F401  (shared fixtures)
from tests.test_phase5 import api, linked  # noqa: F401
from tests.test_watch import applied  # noqa: F401

AS_OF = date(2026, 9, 16)
ROOT = Path(__file__).resolve().parents[1]


def test_weekly_report_content(applied):
    session, project, _ = applied
    data = report.build(session, project, AS_OF, "weekly")
    assert data["from"] == date(2026, 9, 10) and (data["started"] or data["finished"])
    assert all(date(2026, 9, 10) <= r["actual_start"] <= AS_OF for r in data["started"])
    html = report.render(data)
    for heading in ("Started", "Finished", "Delays and causes", "Expected work with no report", "Past planned finish"):
        assert f"<h2>{heading}" in html
    daily = report.build(session, project, AS_OF, "daily")
    assert len(daily["started"]) <= len(data["started"]) and daily["from"] == AS_OF


def test_field_text_is_escaped(applied):
    session, project, _ = applied
    data = report.build(session, project, AS_OF, "weekly")
    data["started"] = [dict(data["started"][0] if data["started"] else data["finished"][0], name="<script>alert(1)</script>")]
    html = report.render(data)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_report_api(api):
    c, base, _, _ = api
    assert c.get(f"{base}/reports/pm").status_code == 401
    r = c.get(f"{base}/reports/pm", headers=SUP, params={"as_of": "2026-09-16", "period": "weekly"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "Weekly project report" in r.text
    assert c.get(f"{base}/reports/pm", headers=SUP, params={"period": "monthly"}).status_code == 422
    dl = c.get(f"{base}/reports/pm", headers=SUP, params={"as_of": "2026-09-16", "download": True})
    assert "attachment" in dl.headers["content-disposition"]


def test_cli_writes_report(applied, tmp_path):
    session, project, _ = applied
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "phase8" / "generate_reports.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    url = session.get_bind().url.render_as_string(hide_password=False)
    assert gen.main(["--db", url, "--as-of", "2026-09-16", "--period", "weekly", "--out", str(tmp_path)]) == 0
    out = tmp_path / f"{project.code}-weekly-report-2026-09-16.html"
    assert out.exists() and "<!doctype html>" in out.read_text(encoding="utf-8")
