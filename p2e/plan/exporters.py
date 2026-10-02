"""Phase 5 export: the schedule with current actuals as CSV (Phase 0/1 columns + percent_complete) and MSPDI XML, in the
same shapes the Phase 1 importer reads, so a planner can load them into MS Project / P6 (activities keyed by Activity ID,
MSPDI Text1)."""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import PlanDependency, PlanNode, Project

COLUMNS = ["node_id", "node_type", "parent_id", "level", "wbs_code", "name", "discipline", "area", "activity_type",
           "planned_start", "planned_finish", "planned_duration_days", "planned_qty", "qty_unit", "predecessors",
           "actual_start", "actual_finish", "percent_complete"]
MSP_NS = "http://schemas.microsoft.com/project"
EXT_ATTRS = [("188743731", "Text1", "Activity ID"), ("188743734", "Text2", "Discipline"), ("188743737", "Text3", "Area")]
LINK_TYPE = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}


def rows(session: Session, project: Project) -> list[dict]:
    nodes = session.scalars(select(PlanNode).options(selectinload(PlanNode.parent), selectinload(PlanNode.predecessors)
                                                     .selectinload(PlanDependency.predecessor))
                            .where(PlanNode.project_id == project.id).order_by(PlanNode.seq)).all()
    out = []
    for n in nodes:
        val = lambda v: "" if v is None else (v.isoformat() if isinstance(v, date) else str(v))   # noqa: E731
        preds = ";".join(f"{d.predecessor.code}:{d.link_type}{'+' if d.lag_days >= 0 else ''}{d.lag_days}"
                         for d in sorted(n.predecessors, key=lambda d: d.predecessor.seq))
        out.append({"node_id": n.code, "node_type": n.node_type, "parent_id": n.parent.code if n.parent else "", "level": str(n.level),
                    "wbs_code": n.wbs_code, "name": n.name, "discipline": val(n.discipline), "area": val(n.area),
                    "activity_type": val(n.activity_type), "planned_start": val(n.planned_start), "planned_finish": val(n.planned_finish),
                    "planned_duration_days": val(n.planned_duration_days),
                    "planned_qty": "" if n.planned_qty is None else f"{n.planned_qty:g}", "qty_unit": val(n.qty_unit),
                    "predecessors": preds, "actual_start": val(n.actual_start), "actual_finish": val(n.actual_finish),
                    "percent_complete": "" if n.percent_complete is None else f"{n.percent_complete:g}"})
    return out


def to_csv(data: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(data)
    return buf.getvalue()


def to_mspdi(project: Project, data: list[dict], status_date: date) -> bytes:
    q = lambda t: f"{{{MSP_NS}}}{t}"                # noqa: E731
    ET.register_namespace("", MSP_NS)

    def sub(parent, tag, text=None):
        e = ET.SubElement(parent, q(tag))
        if text is not None:
            e.text = str(text)
        return e

    uid = {r["node_id"]: i + 1 for i, r in enumerate(data)}
    children = defaultdict(list)
    for r in data:
        children[r["parent_id"]].append(r["node_id"])
    outline: dict[str, str] = {}

    def number(nid, prefix):
        outline[nid] = prefix
        for k, c in enumerate(children[nid], 1):
            number(c, f"{prefix}.{k}")

    for k, root_id in enumerate(children[""], 1):
        number(root_id, str(k))
    root = ET.Element(q("Project"))
    sub(root, "SaveVersion", 14)
    sub(root, "Name", f"{project.code}.xml")
    sub(root, "Title", project.name)
    sub(root, "ScheduleFromStart", 1)
    sub(root, "StatusDate", f"{status_date.isoformat()}T17:00:00")
    sub(root, "MinutesPerDay", 480)
    ea = sub(root, "ExtendedAttributes")
    for fid, fname, alias in EXT_ATTRS:
        x = sub(ea, "ExtendedAttribute")
        sub(x, "FieldID", fid)
        sub(x, "FieldName", fname)
        sub(x, "Alias", alias)
    tasks = sub(root, "Tasks")
    for r in data:
        t = sub(tasks, "Task")
        sub(t, "UID", uid[r["node_id"]])
        sub(t, "ID", uid[r["node_id"]])
        sub(t, "Name", r["name"])
        sub(t, "WBS", r["wbs_code"])
        sub(t, "OutlineNumber", outline[r["node_id"]])
        sub(t, "OutlineLevel", r["level"])
        sub(t, "Start", f"{r['planned_start']}T08:00:00")
        sub(t, "Finish", f"{r['planned_finish']}T17:00:00")
        sub(t, "Duration", f"PT{int(r['planned_duration_days']) * 8}H0M0S")
        sub(t, "Milestone", 0)
        sub(t, "Summary", 0 if r["node_type"] == "activity" else 1)
        if r["actual_start"]:
            sub(t, "ActualStart", f"{r['actual_start']}T08:00:00")
        if r["actual_finish"]:
            sub(t, "ActualFinish", f"{r['actual_finish']}T17:00:00")
        if r["percent_complete"]:
            sub(t, "PercentComplete", round(float(r["percent_complete"])))
        for p in filter(None, r["predecessors"].split(";")):
            pid, rest = p.split(":")
            link = sub(t, "PredecessorLink")
            sub(link, "PredecessorUID", uid[pid])
            sub(link, "Type", LINK_TYPE[rest[:2]])
            sub(link, "LinkLag", int(rest[2:]) * 4800)     # tenths of minutes, 8 h days
            sub(link, "LagFormat", 7)
        for (fid, _, _), v in zip(EXT_ATTRS, [r["node_id"] if r["node_type"] == "activity" else "", r["discipline"], r["area"]]):
            if v:
                x = sub(t, "ExtendedAttribute")
                sub(x, "FieldID", fid)
                sub(x, "Value", v)
    ET.indent(root)
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
