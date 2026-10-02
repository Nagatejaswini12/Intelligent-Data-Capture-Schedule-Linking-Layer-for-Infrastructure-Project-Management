"""Institutional knowledge entries distilled from the project history (Phase 6), computed on demand, each with provenance:
  duration/<activity type>  how long completed activities of a type actually took vs plan (cites the activities)
  delays/<discipline>       recurring delay causes reported in the field (cites the reports)
Used as the narrative corpus of the memory Q&A and exported to OKF. SQLite stays the source of truth.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from p2e.analytics import metrics
from p2e.db.models import Project


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "other"


def entries(session: Session, project: Project, as_of: date) -> list[dict]:
    rows = metrics.dataset(session, project, as_of)
    out = []
    for t, d in metrics.productivity(rows)["durations"].items():
        done = [r for r in rows if r["code"] in set(d["activities"])]
        out.append({
            "id": f"duration/{slug(t)}", "kind": "duration", "title": f"{t}: actual vs planned duration",
            "text": (f"{d['completed']} completed {t.lower()} activities took {d['mean_actual_days']} days on average against "
                     f"{d['mean_planned_days']} planned (ratio {d['mean_ratio']})."),
            "values": {k: d[k] for k in ("completed", "mean_actual_days", "mean_planned_days", "mean_ratio")},
            "citations": [{"kind": "activity", "id": r["code"], "text": r["name"], "date": f"{r['actual_start']}..{r['actual_finish']}"}
                          for r in done]})
    by_disc = defaultdict(list)
    for e, n in metrics.delay_events(session, project):
        if e.event_date and e.event_date <= as_of:
            by_disc[e.discipline or "-"].append((e, n))
    for disc, items in sorted(by_disc.items()):
        cats = defaultdict(list)
        for e, _ in items:
            cats[e.delay_category].append(e.delay_reason)
        summary = "; ".join(f"{c} {len(rs)}x ({', '.join(sorted(set(rs)))})" for c, rs in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0])))
        out.append({
            "id": f"delays/{slug(disc)}", "kind": "delays", "title": f"Delay causes reported in {disc}",
            "text": f"{len(items)} hold reports in {disc}: {summary}.",
            "values": {"holds": len(items), "by_category": {c: len(rs) for c, rs in sorted(cats.items())}},
            "citations": [{"kind": "event", "id": e.id, "text": e.source_text, "date": str(e.event_date),
                           "activity": n.code if n else None} for e, n in items]})
    return out
