"""Upgrade W2: efficiency + ROI proof, computed from records that already exist (no extra bookkeeping).

Decision tier per linked report (who or what decided it):
  automatic       the deterministic linker matched it (tag / alias / attribute evidence), 0 LLM tokens
  planner         a human confirmed, rejected or held it (decided_by human:* or a supervisor retract)
  review_pending  waiting in the planner queue
  flagged         not linkable and flagged (new / unknown work) by the linker
LLM calls are counted where an LLM actually ran (the advisory tie-breaker's stored suggestion). Token and rupee figures
are calls x documented assumptions, which the caller can override; they are estimates, labelled as such.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from p2e.db.models import AuditLog, EventLink, ProgressEvent, Project, SourceDocument
from p2e.decide import apply as engine


@dataclass(frozen=True)
class Assumptions:
    """Editable ROI inputs (defaults are placeholders for OIL to replace with its own figures)."""
    manual_minutes_per_item: float = 5.0        # planner time to find the activity and key in one reported item by hand
    planner_inr_per_hour: float = 750.0
    manual_lag_days: float = 3.0                # typical delay from site report to schedule update today
    tokens_per_llm_call: int = 1500             # prompt + answer for one item if an LLM read it
    inr_per_1k_tokens: float = 0.25             # cloud-LLM price used for the "LLM for everything" comparison


def tier(link: EventLink) -> str:
    by = link.decided_by or ""
    if by.startswith(("human:", "supervisor-retract")):
        return "planner"
    if link.state == "pending":
        return "review_pending"
    return "automatic" if link.decision == "matched" else "flagged"


def _utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes for timezone-aware columns; they were written in UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def efficiency(session: Session, project: Project, as_of: date, a: Assumptions = Assumptions()) -> dict:
    reported = func.coalesce(ProgressEvent.report_date, ProgressEvent.event_date)    # sheets carry dates per row, not per file
    links = session.scalars(select(EventLink).join(ProgressEvent, ProgressEvent.id == EventLink.progress_event_id)
                            .where(EventLink.project_id == project.id, reported <= as_of)).all()
    tiers = Counter(tier(link) for link in links)
    methods = Counter(link.method for link in links if tier(link) == "automatic")
    llm_calls = sum(link.llm_suggestion is not None for link in links)
    items = len(links)
    reports = session.scalar(select(func.count()).select_from(SourceDocument).where(
        SourceDocument.project_id == project.id, SourceDocument.kind != "schedule_import",
        SourceDocument.report_date.is_(None) | (SourceDocument.report_date <= as_of)))

    # processing time: upload of the evidence -> automatic schedule update (seconds, real clock)
    uploaded = dict(session.execute(select(ProgressEvent.id, SourceDocument.created_at)
                                    .join(SourceDocument, SourceDocument.id == ProgressEvent.source_document_id)
                                    .where(ProgressEvent.project_id == project.id)).all())
    waits = []
    for entry in session.scalars(select(AuditLog).where(AuditLog.project_id == project.id, AuditLog.rule == "auto_evidence")):
        times = [_utc(uploaded[e]) for e in entry.evidence_event_ids if e in uploaded]
        if times:
            waits.append(max(0.0, (_utc(entry.created_at) - min(times)).total_seconds()))

    proposals = engine.propose(session, project, as_of)
    shadow = {"enabled": bool(project.shadow_mode),
              "would_update": sum(1 for p in proposals if p.changes and not p.blockers),
              "blocked_for_review": sum(1 for p in proposals if p.blockers)}

    auto = tiers["automatic"]
    hours_saved = auto * a.manual_minutes_per_item / 60
    ours_tokens = llm_calls * a.tokens_per_llm_call
    all_llm_tokens = items * a.tokens_per_llm_call
    per_1000 = 1000 / reports if reports else 0.0
    return {
        "as_of": as_of,
        "assumptions": asdict(a),
        "reports": reports,
        "items": items,
        "tiers": {k: tiers[k] for k in ("automatic", "planner", "review_pending", "flagged")},
        "automatic_by_evidence": dict(sorted(methods.items())),
        "auto_link_rate": round(auto / items, 4) if items else None,
        "llm_calls": llm_calls,
        "llm_call_ratio": round(llm_calls / items, 4) if items else None,
        "processing_seconds_median": round(median(waits), 1) if waits else None,
        "manual_lag_days": a.manual_lag_days,
        "shadow": shadow,
        "planner_hours_saved": round(hours_saved, 1),
        "planner_inr_saved": round(hours_saved * a.planner_inr_per_hour),
        "tokens": {"ours_estimated": ours_tokens, "llm_for_everything_estimated": all_llm_tokens,
                   "ours_per_1000_reports": round(ours_tokens * per_1000),
                   "llm_for_everything_per_1000_reports": round(all_llm_tokens * per_1000)},
        "inr_per_1000_reports": {"ours": round(ours_tokens * per_1000 / 1000 * a.inr_per_1k_tokens, 2),
                                 "llm_for_everything": round(all_llm_tokens * per_1000 / 1000 * a.inr_per_1k_tokens, 2)},
    }
