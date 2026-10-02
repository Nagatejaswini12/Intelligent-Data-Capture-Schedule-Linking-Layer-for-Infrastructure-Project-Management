"""Read-side schedule queries (service layer). Returns ORM objects / plain dicts; the API layer maps them to schemas."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import PlanDependency, PlanNode, PlanTag, Project


def list_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).options(selectinload(Project.sources)).order_by(Project.code)))


def get_project(session: Session, code: str) -> Project | None:
    return session.scalar(select(Project).options(selectinload(Project.sources)).where(Project.code == code))


def schedule_summary(session: Session, project: Project) -> dict:
    rows = session.execute(select(PlanNode.node_type, PlanNode.level, PlanNode.discipline, PlanNode.area,
                                  PlanNode.planned_start, PlanNode.planned_finish)
                           .where(PlanNode.project_id == project.id)).all()
    acts = [r for r in rows if r.node_type == "activity"]
    srt = lambda c: dict(sorted(c.items()))
    return {
        "total_nodes": len(rows),
        "executable_activities": len(acts),
        "nodes_by_type": srt(Counter(r.node_type for r in rows)),
        "nodes_by_level": srt(Counter(str(r.level) for r in rows)),
        "activities_by_level": srt(Counter(str(r.level) for r in acts)),
        "activities_by_discipline": srt(Counter(r.discipline for r in acts)),
        "activities_by_area": srt(Counter(r.area for r in acts if r.area)),
        "planned_start": min((r.planned_start for r in rows), default=None),
        "planned_finish": max((r.planned_finish for r in rows), default=None),
    }


def list_nodes(session: Session, project: Project, *, node_type: str | None = None, executable: bool | None = None,
               level: int | None = None, discipline: str | None = None, area: str | None = None, q: str | None = None,
               tag: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[PlanNode], int]:
    stmt = select(PlanNode).where(PlanNode.project_id == project.id)
    if node_type:
        stmt = stmt.where(PlanNode.node_type == node_type)
    if executable is not None:
        stmt = stmt.where((PlanNode.node_type == "activity") if executable else (PlanNode.node_type != "activity"))
    if level is not None:
        stmt = stmt.where(PlanNode.level == level)
    if discipline:
        stmt = stmt.where(PlanNode.discipline == discipline)
    if area:
        stmt = stmt.where(PlanNode.area == area)
    if q:
        stmt = stmt.where(PlanNode.name.icontains(q, autoescape=True))   # literal substring, not fuzzy/semantic
    if tag:
        stmt = stmt.where(PlanNode.tags.any(PlanTag.tag == tag.strip().upper()))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    items = session.scalars(stmt.options(selectinload(PlanNode.tags), selectinload(PlanNode.parent))
                            .order_by(PlanNode.seq).limit(limit).offset(offset)).all()
    return list(items), total


def get_node(session: Session, project: Project, code: str) -> PlanNode | None:
    return session.scalar(
        select(PlanNode).where(PlanNode.project_id == project.id, PlanNode.code == code)
        .options(selectinload(PlanNode.tags), selectinload(PlanNode.parent), selectinload(PlanNode.children),
                 selectinload(PlanNode.predecessors).selectinload(PlanDependency.predecessor)))


def ancestors(node: PlanNode) -> list[PlanNode]:
    chain, p = [], node.parent
    while p is not None:
        chain.append(p)
        p = p.parent
    return chain[::-1]


def successors(session: Session, node: PlanNode) -> list[PlanDependency]:
    return list(session.scalars(select(PlanDependency).where(PlanDependency.predecessor_id == node.id)
                                .options(selectinload(PlanDependency.successor))))


def hierarchy(session: Session, project: Project, root_code: str | None = None, depth: int | None = None) -> dict | None:
    """Nested tree from one query (≤ a few thousand nodes per project). None if root_code is unknown."""
    nodes = session.execute(select(PlanNode.id, PlanNode.parent_id, PlanNode.code, PlanNode.node_type, PlanNode.level,
                                   PlanNode.name, PlanNode.discipline, PlanNode.area, PlanNode.planned_start,
                                   PlanNode.planned_finish).where(PlanNode.project_id == project.id)
                            .order_by(PlanNode.seq)).all()
    kids: dict[int | None, list] = {}
    for n in nodes:
        kids.setdefault(n.parent_id, []).append(n)
    start = next((n for n in nodes if (n.code == root_code if root_code else n.parent_id is None)), None)
    if start is None:
        return None

    def build(n, d: int) -> dict:
        children = kids.get(n.id, [])
        return {"code": n.code, "node_type": n.node_type, "level": n.level, "name": n.name, "discipline": n.discipline,
                "area": n.area, "planned_start": n.planned_start, "planned_finish": n.planned_finish,
                "child_count": len(children),
                "children": [build(c, d + 1) for c in children] if depth is None or d < depth else []}

    return build(start, 0)
