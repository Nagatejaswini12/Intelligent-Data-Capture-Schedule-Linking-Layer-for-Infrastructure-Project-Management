"""Upgrade W3: the daily / weekly project-manager report as one self-contained, printable HTML page.

Built only from what the system already computes (dataset, delay events, efficiency, dashboard, silent-activity watch);
every value is HTML-escaped because field text is untrusted. "Save as PDF" in the browser gives the PDF.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from html import escape

from sqlalchemy.orm import Session

from p2e.analytics import efficiency, metrics
from p2e.db.models import Project
from p2e.decide import watch

PERIOD_DAYS = {"daily": 1, "weekly": 7}


def _within(d: date | None, start: date, end: date) -> bool:
    return d is not None and start <= d <= end


def build(session: Session, project: Project, as_of: date, period: str = "daily") -> dict:
    start = as_of - timedelta(days=PERIOD_DAYS[period] - 1)
    rows = metrics.dataset(session, project, as_of)
    dash = metrics.dashboard(session, project, as_of)
    delays = [(ev, n) for ev, n in metrics.delay_events(session, project) if _within(ev.event_date, start, as_of)]
    return {"project": project.code, "name": project.name, "period": period, "from": start, "to": as_of,
            "started": [r for r in rows if _within(r["actual_start"], start, as_of)],
            "finished": [r for r in rows if _within(r["actual_finish"], start, as_of)],
            "delays": delays, "delay_categories": Counter(ev.delay_category for ev, _ in delays),
            "backlog": dash["review_backlog"], "efficiency": efficiency.efficiency(session, project, as_of),
            "silent": watch.silent_activities(session, project, as_of),
            "late_finishes": [r for r in rows if r["status"] != "completed" and r["planned_finish"] < as_of]}


def _table(head: list[str], body: list[list]) -> str:
    if not body:
        return '<p class="muted">None in this period.</p>'
    cell = lambda c: escape(str(c)) if c is not None else "—"
    return ("<table><thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in row) + "</tr>" for row in body) + "</tbody></table>")


def render(data: dict) -> str:
    e, eff = escape, data["efficiency"]
    rate = f"{round(eff['auto_link_rate'] * 100)}%" if eff["auto_link_rate"] is not None else "—"
    kpis = [("Activities started", len(data["started"])), ("Activities finished", len(data["finished"])),
            ("Hold / delay reports", len(data["delays"])), ("Waiting for planner review", data["backlog"]["pending_events"]),
            ("Linked automatically (to date)", rate), ("AI tokens used (to date)", eff["tokens"]["ours_estimated"]),
            ("Expected work with no report", len(data["silent"])), ("Past planned finish, not complete", len(data["late_finishes"]))]
    causes = " · ".join(f"{e(k)}: {v}" for k, v in sorted(data["delay_categories"].items()))
    sections = [
        ("Started", _table(["Activity", "Name", "Discipline", "Actual start", "Source docs"],
                           [[r["code"], r["name"], r["discipline"], r["actual_start"], r["sources"]] for r in data["started"]])),
        ("Finished", _table(["Activity", "Name", "Discipline", "Actual finish", "Source docs"],
                            [[r["code"], r["name"], r["discipline"], r["actual_finish"], r["sources"]] for r in data["finished"]])),
        ("Delays and causes", (f"<p>{causes}</p>" if causes else "") + _table(
            ["Date", "Category", "Activity", "Report text", "Evidence"],
            [[ev.event_date, ev.delay_category, n.code if n else "not linked", ev.source_text[:160],
              f"event {ev.id} · {ev.document.filename if ev.document else ''}"] for ev, n in data["delays"]])),
        ("Expected work with no report", _table(["Activity", "Name", "Why expected", "Last report"],
            [[i["plan_node_code"], i["activity_name"], i["expectation"], i["last_reported"]] for i in data["silent"][:30]])),
        ("Past planned finish and not complete", _table(["Activity", "Name", "Planned finish", "Status"],
            [[r["code"], r["name"], r["planned_finish"], r["status"]] for r in data["late_finishes"][:30]])),
    ]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data['project'])} {e(data['period'])} report {data['to']}</title>
<style>body{{font:14px/1.45 system-ui,sans-serif;color:#1d232b;background:#fff;margin:24px auto;max-width:1000px;padding:0 16px}}
h1{{font-size:22px;margin:0}}h2{{font-size:16px;margin:24px 0 8px;border-bottom:1px solid #d9dee5;padding-bottom:4px}}
.muted{{color:#5f6b7a}}.kpis{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;margin-top:16px}}
.kpi{{border:1px solid #d9dee5;border-radius:6px;padding:8px}}.kpi b{{display:block;font-size:20px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}th,td{{border-bottom:1px solid #e6e9ee;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#f3f5f8}}@media print{{body{{margin:0}}h2{{break-after:avoid}}}}</style></head><body>
<h1>{e(data['name'])}: {e(data['period'].title())} project report</h1>
<p class="muted">{e(data['project'])} · {data['from']} to {data['to']} · generated by P2E Bridge from recorded field reports;
every row cites its activity, event and source document.</p>
<div class="kpis">{''.join(f'<div class="kpi"><b>{e(str(v))}</b>{e(k)}</div>' for k, v in kpis)}</div>
{''.join(f'<h2>{e(t)}</h2>{body}' for t, body in sections)}
<p class="muted">Estimates with default assumptions (see the ROI page): planner time saved to date {eff['planner_hours_saved']} h;
AI tokens per 1,000 reports {eff['tokens']['ours_per_1000_reports']} vs ~{eff['tokens']['llm_for_everything_per_1000_reports']} if an LLM read everything.</p>
</body></html>"""


def pm_report(session: Session, project: Project, as_of: date, period: str = "daily") -> str:
    return render(build(session, project, as_of, period))
