"""Phase 5 decision + apply engine: accepted links -> validated actual dates / percent -> plan_node + append-only audit_log.

Evidence = progress events whose link is `matched` (linker auto-match or planner-confirmed). Per activity:
  proposed actual start  = earliest reported start / progress / resume date ("earliest credible start"), only when a
                           start was explicitly reported (progress alone only proves the work had begun by that day)
  proposed actual finish = latest reported finish date                    ("latest credible finish")
  percent complete       = 100 when finished; else the largest quantity any single source reports / planned quantity
                           (max per source, so a DPR and the tracker reporting the same spool are not double-counted),
                           capped at 99, never decreasing
Rules that BLOCK the activity (nothing written, it appears in the review queue with the reasons):
  a report dated after the as-of date; no reported start for an activity without a recorded start; an unresolved cross-source date conflict on a confirmed report; start (or finish) reports more than MAX_GAP_DAYS apart; a reported start earlier
  than the recorded actual start; a finish different from the recorded actual finish; work dated after the (recorded or
  reported) finish; a finish without any known start; finish before start.
Warnings (recorded, not blocking): a predecessor that has not finished (FS) / started (SS).
Applying is atomic per activity and idempotent; a change a planner undid is not re-applied automatically.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import AuditLog, EventLink, PlanDependency, PlanNode, PlanTag, ProgressEvent, Project
from p2e.link.conflicts import stream_of
from p2e.plan.tags import extract_tags

APPLY_VERSION = "1.0.0"
MAX_GAP_DAYS = 1
FIELDS = ("actual_start", "actual_finish", "percent_complete")
AUTO_ACTOR = "process:auto-apply"


class ApplyError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class Proposal:
    node: PlanNode
    proposed: dict                                   # field -> value after applying (ISO / number / None)
    changes: dict                                    # field -> [before, after] for fields that change
    evidence: list[int]
    confidence: float | None
    basis: str                                       # auto | planner | mixed
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _value(f: str, v):
    return date.fromisoformat(v) if v is not None and f != "percent_complete" else v


def accepted_links(session: Session, project: Project, node_ids) -> dict[int, list[EventLink]]:
    stmt = (select(EventLink).options(selectinload(EventLink.event).selectinload(ProgressEvent.document))
            .where(EventLink.project_id == project.id, EventLink.decision == "matched", EventLink.plan_node_id.is_not(None),
                   EventLink.state.in_(("auto", "confirmed"))).order_by(EventLink.progress_event_id))
    if node_ids is not None:
        stmt = stmt.where(EventLink.plan_node_id.in_(node_ids))
    groups: dict[int, list[EventLink]] = defaultdict(list)
    for l in session.scalars(stmt):
        if l.event.validation_status == "valid":
            groups[l.plan_node_id].append(l)
    return groups


def _undone(session: Session, project: Project) -> set[tuple]:
    """(node, field, value) changes a planner undid: never re-applied automatically."""
    reverted = select(AuditLog.reverts_id).where(AuditLog.project_id == project.id, AuditLog.reverts_id.is_not(None))
    out = set()
    for e in session.scalars(select(AuditLog).where(AuditLog.id.in_(reverted))):
        out |= {(e.plan_node_id, f, json_key(v[1])) for f, v in e.changes.items()}
    return out


def json_key(v):
    return v if not isinstance(v, float) else round(v, 4)


def propose(session: Session, project: Project, as_of: date, node_ids=None) -> list[Proposal]:
    groups = accepted_links(session, project, node_ids)
    nodes = {n.id: n for n in session.scalars(select(PlanNode).options(
        selectinload(PlanNode.predecessors).selectinload(PlanDependency.predecessor)).where(PlanNode.id.in_(list(groups))))}
    undone = _undone(session, project)
    out = []
    for nid in sorted(groups):
        n, links = nodes[nid], groups[nid]
        evs = [l.event for l in links]
        dated = [e for e in evs if e.event_date]
        blockers, warnings = [], []
        future = sorted({e.event_date for e in dated if e.event_date > as_of})
        if future:
            blockers.append(f"report dated after {as_of}: {', '.join(map(str, future))}")
        if any(l.conflict for l in links):            # Phase 3.1: identity confirmed, date still contradicted
            blockers.append("unresolved cross-source date conflict: reject the wrong report or set the actuals by override")
        work = [e for e in dated if e.event_type in ("start", "progress", "resume")]
        for et in ("start", "finish"):
            days = sorted({e.event_date for e in dated if e.event_type == et})
            if days and (days[-1] - days[0]).days > MAX_GAP_DAYS:
                blockers.append(f"{et} reported as {', '.join(map(str, days))} (more than {MAX_GAP_DAYS} day apart)")
        p_start = min((e.event_date for e in work), default=None)
        p_finish = max((e.event_date for e in dated if e.event_type == "finish"), default=None)
        start, finish = n.actual_start, n.actual_finish
        if p_start:
            if start is None and not any(e.event_type == "start" for e in work):
                blockers.append(f"actual start not reported (first work reported on {p_start} only proves it had started "
                                "by then); set the start by override")
            elif start is None:
                start = p_start
            elif p_start < start:
                blockers.append(f"reported start {p_start} is earlier than the recorded actual start {start}")
        if p_finish:
            if finish is None:
                finish = p_finish
            elif p_finish != finish:
                blockers.append(f"finish reported as {p_finish} but the recorded actual finish is {finish}")
        if finish:
            late = sorted({e.event_date for e in work if e.event_date > finish})
            if late:
                blockers.append(f"work reported on {', '.join(map(str, late))} after the finish {finish}")
            if start is None:
                blockers.append("finish reported without any known actual start")
            elif finish < start:
                blockers.append(f"finish {finish} before start {start}")
        pct = n.percent_complete
        target = 100.0 if finish else _quantity_percent(n, evs)
        if target is not None and (pct is None or target > pct):
            pct = target
        proposed = {"actual_start": _iso(start), "actual_finish": _iso(finish), "percent_complete": pct}
        changes = {}
        for f in FIELDS:
            before = _iso(getattr(n, f))
            if proposed[f] != before:
                if (nid, f, json_key(proposed[f])) in undone:
                    warnings.append(f"{f} {proposed[f]} was undone by a planner; not re-applied automatically")
                    proposed[f] = before
                else:
                    changes[f] = [before, proposed[f]]
        if "actual_start" in changes:
            for d in n.predecessors:
                p = d.predecessor
                if d.link_type == "FS" and p.actual_finish is None:
                    warnings.append(f"predecessor {p.code} (FS) has no actual finish")
                elif d.link_type == "SS" and p.actual_start is None:
                    warnings.append(f"predecessor {p.code} (SS) has no actual start")
        states = {l.state for l in links}
        out.append(Proposal(n, proposed, changes, sorted(e.id for e in evs), min(l.confidence for l in links),
                            "auto" if states == {"auto"} else "planner" if states == {"confirmed"} else "mixed", blockers, warnings))
    return out


def _quantity_percent(n: PlanNode, evs: list[ProgressEvent]) -> float | None:
    if not n.planned_qty or not n.qty_unit:
        return None
    per_source: dict[tuple, float] = defaultdict(float)
    for e in evs:
        if e.event_type == "progress" and e.unit == n.qty_unit and e.quantity:
            per_source[stream_of(e)] += e.quantity
    if not per_source:
        return None
    return round(min(99.0, max(per_source.values()) / n.planned_qty * 100), 1)


def apply(session: Session, project: Project, as_of: date, actor: str = AUTO_ACTOR, node_ids=None, dry_run: bool = False) -> dict:
    """Write every unblocked change; caller commits. Returns applied entries, blocked activities and counts."""
    applied, blocked, unchanged = [], [], 0
    for p in propose(session, project, as_of, node_ids):
        if p.blockers:
            blocked.append(p)
        elif not p.changes:
            unchanged += 1
        else:
            applied.append(p if dry_run else _write(session, project, p.node, p.changes, actor, f"{p.basis}_evidence",
                                                     p.confidence, p.evidence, p.warnings, "apply"))
    session.flush()
    return {"applied": applied, "blocked": blocked, "unchanged": unchanged, "as_of": as_of, "dry_run": dry_run}


def _write(session, project, node: PlanNode, changes: dict, actor, rule, confidence, evidence, warnings, action, reverts_id=None):
    for f, (_, after) in changes.items():
        setattr(node, f, _value(f, after))
    entry = AuditLog(project_id=project.id, plan_node_id=node.id, action=action, changes=changes, actor=actor, rule=rule,
                     confidence=confidence, evidence_event_ids=evidence, warnings=warnings, reverts_id=reverts_id)
    session.add(entry)
    session.flush()                                  # plan_node CHECK constraints run here
    return entry


def _check_state(start: date | None, finish: date | None, pct: float | None, as_of: date) -> list[str]:
    errors = []
    if finish and start is None:
        errors.append("an actual finish needs an actual start")
    if start and finish and finish < start:
        errors.append(f"finish {finish} before start {start}")
    for label, d in (("start", start), ("finish", finish)):
        if d and d > as_of:
            errors.append(f"actual {label} {d} is after {as_of}")
    if pct is not None and not 0 <= pct <= 100:
        errors.append("percent_complete must be between 0 and 100")
    if pct == 100 and finish is None:
        errors.append("100 percent needs an actual finish")
    return errors


def override(session: Session, project: Project, node: PlanNode, values: dict, actor: str, as_of: date,
             evidence: list[int] | None = None) -> AuditLog:
    """Planner sets actuals explicitly (resolving a blocked activity). Only the given fields change."""
    if node.node_type != "activity":
        raise ApplyError(422, f"{node.code} is not an executable activity")
    after = {f: _iso(getattr(node, f)) for f in FIELDS} | {f: _iso(v) for f, v in values.items()}
    errors = _check_state(_value("actual_start", after["actual_start"]), _value("actual_finish", after["actual_finish"]),
                          after["percent_complete"], as_of)
    if errors:
        raise ApplyError(422, "; ".join(errors))
    changes = {f: [_iso(getattr(node, f)), after[f]] for f in FIELDS if after[f] != _iso(getattr(node, f))}
    if not changes:
        raise ApplyError(409, "nothing to change")
    return _write(session, project, node, changes, actor, "planner_override", None, evidence or [], [], "override")


def undo(session: Session, project: Project, entry_id: int, actor: str) -> AuditLog:
    e = session.scalar(select(AuditLog).where(AuditLog.id == entry_id, AuditLog.project_id == project.id))
    if e is None:
        raise ApplyError(404, f"audit entry {entry_id} not found in project {project.code}")
    if e.action not in ("apply", "override"):
        raise ApplyError(409, f"a {e.action} entry cannot be undone")
    if session.scalar(select(AuditLog.id).where(AuditLog.reverts_id == e.id)):
        raise ApplyError(409, f"audit entry {entry_id} was already undone")
    node = e.node
    moved = [f for f, (_, after) in e.changes.items() if _iso(getattr(node, f)) != after]
    if moved:
        raise ApplyError(409, f"{', '.join(moved)} changed after entry {entry_id}; undo the later entries first")
    restored = {f: _iso(getattr(node, f)) for f in FIELDS} | {f: before for f, (before, _) in e.changes.items()}
    errors = _check_state(_value("actual_start", restored["actual_start"]), _value("actual_finish", restored["actual_finish"]),
                          restored["percent_complete"], date.max)
    if errors:
        raise ApplyError(409, f"undo would leave an invalid state ({'; '.join(errors)}); undo the later entries first")
    return _write(session, project, node, {f: [after, before] for f, (before, after) in e.changes.items()}, actor, "undo",
                  None, e.evidence_event_ids, [], "undo", reverts_id=e.id)


def create_activity(session: Session, project: Project, parent_code: str, code: str, name: str, planned_start: date,
                    planned_finish: date, event: ProgressEvent, actor: str) -> PlanNode:
    """Planner marks a report as NEW work: an L5 activity under an L4 WBS node (or L6 under an L5 summary)."""
    parent = session.scalar(select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.code == parent_code))
    if parent is None or not ((parent.node_type == "wbs" and parent.level == 4) or parent.node_type == "summary"):
        raise ApplyError(422, f"{parent_code!r} must be an L4 WBS node or an L5 summary of project {project.code}")
    if session.scalar(select(PlanNode.id).where(PlanNode.project_id == project.id, PlanNode.code == code)):
        raise ApplyError(409, f"activity code {code!r} already exists")
    if planned_finish < planned_start:
        raise ApplyError(422, "planned_finish before planned_start")
    seq = (session.scalar(select(func.max(PlanNode.seq)).where(PlanNode.project_id == project.id)) or 0) + 1
    node = PlanNode(project_id=project.id, source_document_id=event.source_document_id, seq=seq, code=code, node_type="activity",
                    parent_id=parent.id, level=parent.level + 1, name=name,
                    wbs_code=parent.code if parent.node_type == "wbs" else parent.wbs_code, discipline=parent.discipline,
                    area=parent.area, activity_type=None, planned_start=planned_start, planned_finish=planned_finish,
                    planned_duration_days=(planned_finish - planned_start).days + 1)
    node.tags = [PlanTag(tag=t) for t in extract_tags(name)]
    session.add(node)
    session.flush()
    session.add(AuditLog(project_id=project.id, plan_node_id=node.id, action="create_activity", actor=actor, rule="new_activity",
                         changes={"activity": [None, code], "parent": [None, parent_code]}, evidence_event_ids=[event.id]))
    session.flush()
    return node
