"""Linking runs and planner decisions (persistence around context -> retrieve -> decide -> [LLM] -> MAG).

Idempotent: an event whose link was made with the same linker, context (CAG) and alias-memory (MAG) versions is left
unchanged; a planner's confirmed/rejected decision is never overwritten by the linker.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import EventLink, LinkCandidate, PlanNode, ProgressEvent, Project
from p2e.link import adjudicate
from p2e.link.conflicts import apply_conflicts
from p2e.link.context import ProjectContext, get_context
from p2e.link.decide import LINKER_VERSION, decide
from p2e.link.retrieve import ScheduleIndex, make_query
from p2e.memory import aliases as mag


class LinkError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def link_events(session: Session, project: Project, glossary_path: Path, event_ids: list[int] | None = None,
                llm=None) -> dict:
    """Link valid events (all of the project, or the given ids). Returns outcome counts. Caller commits."""
    ctx = get_context(session, project, glossary_path)
    index = ScheduleIndex.build(session, project, ctx)
    active = mag.active(session, project.id)
    mag_version = mag.fingerprint(active)
    objects, actions = mag.for_retrieval(active)
    action_ids = {a.phrase: a.id for a in active if a.kind == "action"}
    stmt = select(ProgressEvent).where(ProgressEvent.project_id == project.id, ProgressEvent.validation_status == "valid")
    if event_ids is not None:
        stmt = stmt.where(ProgressEvent.id.in_(event_ids))
    existing = {l.progress_event_id: l for l in session.scalars(
        select(EventLink).options(selectinload(EventLink.candidates)).where(EventLink.project_id == project.id))}
    counts: Counter = Counter()
    used: set[int] = set()
    for ev in session.scalars(stmt.order_by(ProgressEvent.id)):
        link = existing.get(ev.id)
        if link is not None and link.state in ("confirmed", "rejected"):
            counts["kept_planner_decision"] += 1
            continue
        if link is not None and (link.linker_version, link.context_version, link.mag_version) == (LINKER_VERSION, ctx.version, mag_version):
            counts["unchanged"] += 1
            continue
        q = make_query(ctx, ev.activity_text, ev.tags or [], ev.area, ev.discipline, ev.source_ref, ev.unit, actions,
                       ctx.thresholds["alias_auto_min_confirmations"])
        d = decide(q, index, ctx, objects)
        suggestion = None
        if llm is not None and d.decision == "review" and len(d.ranked) >= 2:
            suggestion = adjudicate.adjudicate(llm, ctx, ev.activity_text, ev.source_text, d.ranked)
        if link is None:
            link = EventLink(project_id=project.id, progress_event_id=ev.id)
            session.add(link)
        else:
            link.candidates.clear()                           # delete old candidates before re-inserting ranks
            session.flush()
        link.candidates = [LinkCandidate(rank=i, plan_node_id=s.cand.node.id, score=s.score, methods=sorted(s.cand.methods),
                                         matched_tags=s.cand.matched_tags, matched_terms=s.cand.matched_terms,
                                         features=s.features, reasons=s.reasons) for i, s in enumerate(d.ranked, 1)]
        link.plan_node_id, link.decision, link.confidence, link.margin = d.node_id, d.decision, d.confidence, d.margin
        link.unmatched_type, link.method, link.retrieval_used, link.reasons = d.unmatched_type, d.method, d.used_retrieval, d.reasons
        link.llm_suggestion, link.linker_version, link.context_version, link.mag_version = suggestion, LINKER_VERSION, ctx.version, mag_version
        link.state = "auto" if d.decision != "review" else "pending"
        link.conflict = None                                  # recomputed below by the conflict layer
        link.decided_by = link.decided_at = None
        if d.decision == "matched":                          # count alias memory that contributed to an applied match
            used.update(d.ranked[0].cand.alias_ids)
            used.update(action_ids[t[6:]] for t in q.actions.values() if t.startswith("alias:"))
        counts[d.decision] += 1
    session.flush()
    conflicts = apply_conflicts(session, project, ctx.thresholds["conflict_date_shift_days"])   # before any match is accepted
    if used:
        mag.mark_used(session, used)
    session.flush()
    return {"context_version": ctx.version, "mag_version": mag_version, "linker_version": LINKER_VERSION, "counts": dict(counts),
            "conflicts": conflicts}


def get_link(session: Session, project: Project, event_id: int) -> EventLink:
    link = session.scalar(select(EventLink).options(selectinload(EventLink.candidates).selectinload(LinkCandidate.node),
                                                    selectinload(EventLink.event).selectinload(ProgressEvent.document))
                          .where(EventLink.project_id == project.id, EventLink.progress_event_id == event_id))
    if link is None:
        raise LinkError(404, f"no link decision for event {event_id} in project {project.code} (run linking first)")
    return link


def confirm(session: Session, project: Project, link: EventLink, node_code: str, actor: str, glossary_path: Path) -> dict:
    """Planner confirms the event belongs to `node_code` (any L5/L6 activity, not only a candidate). MAG learns from it."""
    node = session.scalar(select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.code == node_code))
    if node is None or node.node_type != "activity":
        raise LinkError(422, f"{node_code!r} is not an executable L5/L6 activity of project {project.code}")
    link.plan_node_id, link.decision, link.unmatched_type = node.id, "matched", None
    link.state, link.decided_by, link.decided_at = "confirmed", actor, datetime.now(timezone.utc)
    ctx: ProjectContext = get_context(session, project, glossary_path)
    index = ScheduleIndex.build(session, project, ctx)
    learned = mag.learn(session, ctx, index, index.by_code[node.code], link.event, actor)
    session.flush()
    apply_conflicts(session, project, ctx.thresholds["conflict_date_shift_days"])   # the confirmed report still counts as evidence
    return learned


def reject(session: Session, project: Project, link: EventLink, actor: str, glossary_path: Path) -> None:
    """Planner decides the event matches no schedule activity (new / unknown work). Nothing is learned; the rejected report
    no longer takes part in conflict detection (a conflict it caused is lifted for the other reports)."""
    link.plan_node_id, link.decision, link.unmatched_type = None, "unmatched", "planner"
    link.state, link.decided_by, link.decided_at = "rejected", actor, datetime.now(timezone.utc)
    link.conflict = None
    session.flush()
    ctx = get_context(session, project, glossary_path)
    apply_conflicts(session, project, ctx.thresholds["conflict_date_shift_days"])
