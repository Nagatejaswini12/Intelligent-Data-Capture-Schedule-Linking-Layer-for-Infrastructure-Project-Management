"""Schedule import: parse (CSV or MS Project XML) -> validate everything -> insert in one transaction.

Nothing is written unless the whole file validates. Re-importing the same file is a no-op;
importing a *different* schedule over an existing project is refused (merge/re-baseline is later scope).
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from defusedxml import ElementTree as SafeET   # untrusted XML: blocks entity expansion / XXE
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from p2e.db.models import DISCIPLINES, LINK_TYPES, NODE_TYPES, PlanDependency, PlanNode, PlanTag, Project, SourceDocument
from p2e.plan.tags import extract_tags

REQUIRED_COLUMNS = ["node_id", "node_type", "parent_id", "level", "wbs_code", "name", "discipline", "area", "activity_type",
                    "planned_start", "planned_finish", "planned_duration_days", "planned_qty", "qty_unit", "predecessors",
                    "actual_start", "actual_finish"]
MAX_BYTES = 10 * 1024 * 1024
MAX_NODES = 100_000
MSP_NS = {"m": "http://schemas.microsoft.com/project"}
MSP_LINK = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
MSP_TEXT1 = "188743731"   # Text1 = activity ID, Text2 = discipline, Text3 = area (Phase 0 export convention)
MSP_TEXT2 = "188743734"
MSP_TEXT3 = "188743737"


class ScheduleValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        shown = "\n  ".join(errors[:20]) + (f"\n  … and {len(errors) - 20} more" if len(errors) > 20 else "")
        super().__init__(f"schedule rejected: {len(errors)} problem(s)\n  {shown}")


class ImportConflict(RuntimeError):
    pass


@dataclass
class Dependency:
    predecessor: str
    link_type: str
    lag_days: int


@dataclass
class NodeRow:
    code: str
    node_type: str
    parent: str | None
    level: int
    name: str
    wbs_code: str
    discipline: str | None
    area: str | None
    activity_type: str | None
    planned_start: date
    planned_finish: date
    planned_duration_days: int
    planned_qty: float | None
    qty_unit: str | None
    actual_start: date | None
    actual_finish: date | None
    predecessors: list[Dependency] = field(default_factory=list)


@dataclass
class ParsedSchedule:
    rows: list[dict]
    format: str
    filename: str
    sha256: str
    size_bytes: int
    data_date: date | None = None


@dataclass
class ImportResult:
    status: str             # "imported" | "unchanged"
    project_code: str
    node_count: int
    activity_count: int
    tag_count: int
    dependency_count: int


# ----------------------------------------------------------------------------- parsing

def read_schedule(path: Path) -> ParsedSchedule:
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ScheduleValidationError([f"{path.name}: file larger than {MAX_BYTES} bytes"])
    meta = dict(filename=path.name, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return ParsedSchedule(parse_csv(raw), "csv", **meta)
    if suffix == ".xml":
        rows, data_date = parse_mspdi(raw)
        return ParsedSchedule(rows, "mspdi", data_date=data_date, **meta)
    if suffix == ".xer":
        rows, data_date = parse_xer(raw)
        return ParsedSchedule(rows, "xer", data_date=data_date, **meta)
    raise ScheduleValidationError([f"{path.name}: unsupported schedule format (expected .csv, MS Project .xml or Primavera .xer)"])


def parse_csv(raw: bytes) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScheduleValidationError([f"not UTF-8 text: {e}"]) from None
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ScheduleValidationError([f"missing required column(s): {', '.join(missing)}"])
    return [{k: (v or "").strip() for k, v in row.items() if k in REQUIRED_COLUMNS} for row in reader]


def parse_mspdi(raw: bytes) -> tuple[list[dict], date | None]:
    """MSPDI -> the same row dicts as the CSV. Hierarchy comes from OutlineNumber, IDs from Text1 (activities) or WBS."""
    try:
        root = SafeET.fromstring(raw)
    except Exception as e:     # defusedxml raises its own types for forbidden constructs
        raise ScheduleValidationError([f"invalid or unsafe XML: {type(e).__name__}: {e}"]) from None
    if root.tag != f"{{{MSP_NS['m']}}}Project":
        raise ScheduleValidationError(["not an MS Project XML (MSPDI) document"])
    text = lambda el, t: (el.findtext(f"m:{t}", default="", namespaces=MSP_NS) or "").strip()
    status = text(root, "StatusDate")[:10]
    tasks = root.findall("m:Tasks/m:Task", MSP_NS)
    by_outline, by_uid, rows = {}, {}, []
    for t in tasks:
        ext = {text(e, "FieldID"): text(e, "Value") for e in t.findall("m:ExtendedAttribute", MSP_NS)}
        level = text(t, "OutlineLevel")
        summary = text(t, "Summary") == "1"
        node_type = "activity" if not summary else ("summary" if level.isdigit() and int(level) >= 5 else "wbs")
        wbs = text(t, "WBS")
        code = ext.get(MSP_TEXT1) or wbs
        if node_type == "summary":
            code = f"{wbs}#{text(t, 'OutlineNumber')}"   # MSPDI carries no own ID for L5 summary tasks
        hours = text(t, "Duration").removeprefix("PT").split("H")[0]
        row = {"node_id": code, "node_type": node_type, "parent_id": "", "level": level, "wbs_code": wbs, "name": text(t, "Name"),
               "discipline": ext.get(MSP_TEXT2, ""), "area": ext.get(MSP_TEXT3, ""), "activity_type": "",
               "planned_start": text(t, "Start")[:10], "planned_finish": text(t, "Finish")[:10],
               "planned_duration_days": str(int(hours) // 8) if hours.isdigit() else "", "planned_qty": "", "qty_unit": "",
               "predecessors": "", "actual_start": text(t, "ActualStart")[:10], "actual_finish": text(t, "ActualFinish")[:10],
               "_outline": text(t, "OutlineNumber"),
               "_links": [(text(p, "PredecessorUID"), text(p, "Type"), text(p, "LinkLag")) for p in t.findall("m:PredecessorLink", MSP_NS)]}
        by_outline[row["_outline"]] = row
        by_uid[text(t, "UID")] = row
        rows.append(row)
    for row in rows:
        parent = row["_outline"].rpartition(".")[0]
        row["parent_id"] = by_outline[parent]["node_id"] if parent in by_outline else ("" if not parent else f"?outline {parent}")
        links = []
        for uid, typ, lag in row.pop("_links"):
            pred = by_uid.get(uid, {}).get("node_id", f"?uid {uid}")
            days = int(lag) // 4800 if lag.lstrip("-").isdigit() else 0   # LinkLag is tenths of minutes (8 h days)
            links.append(f"{pred}:{MSP_LINK.get(typ, '?')}{'+' if days >= 0 else ''}{days}")
        row["predecessors"] = ";".join(links)
        del row["_outline"]
    return rows, (date.fromisoformat(status) if status else None)


XER_LINK = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
XER_CODES = {"discipline": "discipline", "area": "area", "activity type": "activity_type"}   # P6 activity code types we read


def xer_tables(raw: bytes) -> dict[str, list[dict]]:
    """Primavera P6 XER (tab-separated: %T table, %F field names, %R rows) -> {table: [row dicts]}."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")       # P6 writes the Windows code page by default
    if not text.startswith("ERMHDR"):
        raise ScheduleValidationError(["not a Primavera P6 XER file (missing ERMHDR header)"])
    tables, name, fields = {}, None, []
    for line in text.splitlines():
        tag, _, rest = line.partition("\t")
        if tag == "%T":
            name, fields = rest.strip(), []
            tables[name] = []
        elif tag == "%F":
            fields = rest.split("\t")
        elif tag == "%R" and name:
            tables[name].append(dict(zip(fields, rest.split("\t"))))
    return tables


def parse_xer(raw: bytes) -> tuple[list[dict], date | None]:
    """P6 XER -> the same row dicts as the CSV. Hierarchy from PROJWBS (the project node is level 1), a level-5 WBS
    element with activities is an L5 summary, activities are TASK rows; discipline / area / activity type come from P6
    activity codes of those names (TASKACTV); planned = target dates; predecessors from TASKPRED (lag hours / 8)."""
    t = xer_tables(raw)
    missing = [n for n in ("PROJWBS", "TASK") if not t.get(n)]
    if missing:
        raise ScheduleValidationError([f"XER has no {', '.join(missing)} table"])
    d10 = lambda v: (v or "").strip()[:10]
    code_type = {r["actv_code_type_id"]: XER_CODES.get(r.get("actv_code_type", "").strip().lower())
                 for r in t.get("ACTVTYPE", [])}
    code_value = {r["actv_code_id"]: r.get("short_name", "").strip() for r in t.get("ACTVCODE", [])}
    codes: dict[str, dict] = {}
    for r in t.get("TASKACTV", []):
        if code_type.get(r.get("actv_code_type_id")):
            codes.setdefault(r["task_id"], {})[code_type[r["actv_code_type_id"]]] = code_value.get(r.get("actv_code_id"), "")

    wbs = {r["wbs_id"]: r for r in t["PROJWBS"]}
    root_ids = [i for i, r in wbs.items() if r.get("proj_node_flag") == "Y" or r.get("parent_wbs_id") not in wbs]
    if len(root_ids) != 1:
        raise ScheduleValidationError([f"XER must have exactly one project WBS root, found {len(root_ids)}"])
    depth, path = {}, {}

    def walk(i: str, seen: tuple = ()) -> None:
        if i in depth:
            return
        if i in seen:
            raise ScheduleValidationError([f"XER WBS cycle at wbs_id {i}"])
        p = wbs[i].get("parent_wbs_id")
        if i == root_ids[0]:
            depth[i], path[i] = 1, wbs[i].get("wbs_short_name", "").strip()
            return
        walk(p, seen + (i,))
        depth[i], path[i] = depth[p] + 1, f"{path[p]}.{wbs[i].get('wbs_short_name', '').strip()}"
    for i in wbs:
        walk(i)

    tasks = t["TASK"]
    task_code = {r["task_id"]: r.get("task_code", "").strip() for r in tasks}
    has_tasks = {r.get("wbs_id") for r in tasks}
    summary = {i for i in wbs if depth[i] == 5 and i in has_tasks}
    node_id = {i: (wbs[i].get("wbs_short_name", "").strip() if i in summary else path[i]) for i in wbs}
    wbs_code = {i: (path[wbs[i]["parent_wbs_id"]] if i in summary else path[i]) for i in wbs}
    preds: dict[str, list[str]] = {}
    for r in t.get("TASKPRED", []):
        hrs = r.get("lag_hr_cnt", "0").strip() or "0"
        try:
            days = round(float(hrs) / 8)
        except ValueError:
            days = 0
        preds.setdefault(r["task_id"], []).append(
            f"{task_code.get(r.get('pred_task_id'), '?task ' + r.get('pred_task_id', ''))}:{XER_LINK.get(r.get('pred_type', ''), '?')}"
            f"{'+' if days >= 0 else ''}{days}")

    rows, under = [], {}
    for r in tasks:
        c = codes.get(r["task_id"], {})
        ps, pf = d10(r.get("target_start_date")), d10(r.get("target_end_date"))
        try:
            dur = str((date.fromisoformat(pf) - date.fromisoformat(ps)).days + 1)
        except ValueError:
            dur = ""
        w = r.get("wbs_id")
        rows.append({"node_id": task_code[r["task_id"]], "node_type": "activity", "parent_id": node_id.get(w, f"?wbs {w}"),
                     "level": str(depth.get(w, 0) + 1), "wbs_code": wbs_code.get(w, ""), "name": r.get("task_name", "").strip(),
                     "discipline": c.get("discipline", ""), "area": c.get("area", ""), "activity_type": c.get("activity_type", ""),
                     "planned_start": ps, "planned_finish": pf, "planned_duration_days": dur, "planned_qty": "", "qty_unit": "",
                     "predecessors": ";".join(preds.get(r["task_id"], [])), "actual_start": d10(r.get("act_start_date")),
                     "actual_finish": d10(r.get("act_end_date"))})
        under.setdefault(w, []).append(rows[-1])
    # WBS rows: dates span their activities; discipline / area only when every activity below agrees
    below: dict[str, list[dict]] = {i: [] for i in wbs}
    for w, acts in under.items():
        i = w
        while i in wbs:
            below[i] += acts
            i = wbs[i].get("parent_wbs_id") if i != root_ids[0] else None
    wbs_rows = []
    for i in sorted(wbs, key=lambda i: (depth[i], path[i])):
        acts = below[i]
        one = lambda f: (lambda vals: vals.pop() if len(vals) == 1 else "")({a[f] for a in acts})
        starts, finishes = [a["planned_start"] for a in acts if a["planned_start"]], [a["planned_finish"] for a in acts if a["planned_finish"]]
        ps, pf = (min(starts) if starts else ""), (max(finishes) if finishes else "")
        dur = str((date.fromisoformat(pf) - date.fromisoformat(ps)).days + 1) if ps and pf else ""
        parent = wbs[i].get("parent_wbs_id") if i != root_ids[0] else None
        wbs_rows.append({"node_id": node_id[i], "node_type": "summary" if i in summary else "wbs",
                         "parent_id": node_id[parent] if parent else "", "level": str(depth[i]), "wbs_code": wbs_code[i],
                         "name": wbs[i].get("wbs_name", "").strip(), "discipline": one("discipline"), "area": one("area"),
                         "activity_type": "", "planned_start": ps, "planned_finish": pf, "planned_duration_days": dur,
                         "planned_qty": "", "qty_unit": "", "predecessors": "", "actual_start": "", "actual_finish": ""})
    status = d10((t.get("PROJECT") or [{}])[0].get("last_recalc_date"))
    try:
        data_date = date.fromisoformat(status) if status else None
    except ValueError:
        data_date = None
    return wbs_rows + rows, data_date


# ----------------------------------------------------------------------------- validation

def _date(v: str, what: str, errors: list[str], required: bool) -> date | None:
    if not v:
        if required:
            errors.append(f"{what}: missing")
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        errors.append(f"{what}: invalid ISO date {v!r}")
        return None


def validate_rows(rows: list[dict]) -> list[NodeRow]:
    """Validate the whole schedule; raise ScheduleValidationError listing every problem."""
    errors: list[str] = []
    if not rows:
        raise ScheduleValidationError(["schedule has no rows"])
    if len(rows) > MAX_NODES:
        raise ScheduleValidationError([f"schedule has {len(rows)} rows (limit {MAX_NODES})"])
    codes = [r["node_id"] for r in rows]
    seen, dupes = set(), set()
    for c in codes:
        (dupes if c in seen else seen).add(c)
    if dupes:
        errors.append(f"duplicate node/activity IDs: {', '.join(sorted(dupes)[:10])}")
    if "" in seen:
        errors.append("row(s) with empty node_id")
    by_code = {r["node_id"]: r for r in rows}

    nodes: list[NodeRow] = []
    for i, r in enumerate(rows, start=2):   # CSV line numbers (header is line 1)
        c = r["node_id"] or f"<row {i}>"
        nt = r["node_type"]
        if nt not in NODE_TYPES:
            errors.append(f"{c}: node_type {nt!r} not one of {NODE_TYPES}")
        try:
            level = int(r["level"])
            if not 1 <= level <= 6:
                raise ValueError
        except ValueError:
            errors.append(f"{c}: level {r['level']!r} must be an integer 1-6")
            level = 0
        if nt == "activity" and level not in (5, 6):
            errors.append(f"{c}: executable activity must be WBS level 5 or 6 (got {r['level']})")
        disc = r["discipline"] or None
        if disc and disc not in DISCIPLINES:
            errors.append(f"{c}: discipline {disc!r} not one of {DISCIPLINES}")
        if nt == "activity" and not disc:
            errors.append(f"{c}: activity has no discipline")
        if not r["name"]:
            errors.append(f"{c}: empty name")
        ps = _date(r["planned_start"], f"{c} planned_start", errors, True)
        pf = _date(r["planned_finish"], f"{c} planned_finish", errors, True)
        dur = (pf - ps).days + 1 if ps and pf else 0
        if ps and pf and ps > pf:
            errors.append(f"{c}: planned_start {ps} is after planned_finish {pf}")
        if r["planned_duration_days"] and ps and pf and r["planned_duration_days"] != str(dur):
            errors.append(f"{c}: planned_duration_days {r['planned_duration_days']} != {dur} days between planned dates")
        as_ = _date(r["actual_start"], f"{c} actual_start", errors, False)
        af = _date(r["actual_finish"], f"{c} actual_finish", errors, False)
        if af and (not as_ or af < as_):
            errors.append(f"{c}: actual_finish without an earlier actual_start")
        qty = None
        if r["planned_qty"]:
            try:
                qty = float(r["planned_qty"])
                if qty < 0 or not r["qty_unit"]:
                    raise ValueError
            except ValueError:
                errors.append(f"{c}: planned_qty {r['planned_qty']!r} must be a non-negative number with a qty_unit")
        deps = []
        for p in filter(None, r["predecessors"].split(";")):
            pid, _, rest = p.partition(":")
            typ, lag = rest[:2], rest[2:] or "+0"
            if pid not in by_code or by_code[pid]["node_type"] != "activity" or pid == r["node_id"]:
                errors.append(f"{c}: predecessor {pid!r} is not another activity in this schedule")
            elif typ not in LINK_TYPES or not lag.lstrip("+-").isdigit():
                errors.append(f"{c}: predecessor link {p!r} must look like ID:FS+n (FS/SS/FF/SF)")
            else:
                deps.append(Dependency(pid, typ, int(lag)))
        parent = r["parent_id"] or None
        nodes.append(NodeRow(r["node_id"], nt, parent, level, r["name"], r["wbs_code"], disc, r["area"] or None,
                             r["activity_type"] or None, ps or date.min, pf or date.min, dur, qty, r["qty_unit"] or None,
                             as_, af, deps))

    roots = [n for n in nodes if n.parent is None]
    if len(roots) != 1 or roots[0].level != 1:
        errors.append(f"expected exactly one level-1 root without parent, found {[n.code for n in roots][:5]}")
    has_children = {n.parent for n in nodes if n.parent}
    for n in nodes:
        if n.parent is None:
            continue
        p = by_code.get(n.parent)
        if p is None:
            errors.append(f"{n.code}: parent {n.parent!r} does not exist")
        elif p["node_type"] == "activity":
            errors.append(f"{n.code}: parent {n.parent!r} is an activity (activities cannot have children)")
        elif p["level"].isdigit() and n.level != int(p["level"]) + 1:
            errors.append(f"{n.code}: level {n.level} does not follow parent level {p['level']}")
    for n in nodes:
        if n.node_type == "summary" and n.code not in has_children:
            errors.append(f"{n.code}: summary node has no child activities")
    if errors:
        raise ScheduleValidationError(errors)
    return nodes


# ----------------------------------------------------------------------------- import

def import_schedule(session: Session, parsed: ParsedSchedule, data_date: date | None = None) -> ImportResult:
    nodes = validate_rows(parsed.rows)
    root = next(n for n in nodes if n.parent is None)
    project = session.scalar(select(Project).where(Project.code == root.code))
    if project is not None:
        existing = session.scalar(select(SourceDocument).where(SourceDocument.project_id == project.id,
                                                               SourceDocument.kind == "schedule_import",
                                                               SourceDocument.sha256 == parsed.sha256))
        if existing is not None:
            return summarize(session, project, "unchanged")
        if session.scalar(select(func.count()).select_from(PlanNode).where(PlanNode.project_id == project.id)):
            raise ImportConflict(f"project {project.code} already has a schedule from a different file; "
                                 "re-baselining is not supported in Phase 1 (re-create the database to replace it)")
    else:
        project = Project(code=root.code, name=root.name, data_date=data_date or parsed.data_date)
        session.add(project)
        session.flush()
    src = SourceDocument(project_id=project.id, kind="schedule_import", status="imported", format=parsed.format, filename=parsed.filename,
                         sha256=parsed.sha256, size_bytes=parsed.size_bytes, node_count=len(nodes),
                         activity_count=sum(n.node_type == "activity" for n in nodes))
    session.add(src)
    session.flush()
    seq = {n.code: i for i, n in enumerate(nodes, start=1)}   # source-file order for lists and trees
    ids: dict[str, PlanNode] = {}
    for n in sorted(nodes, key=lambda n: n.level):             # parents before children
        pn = PlanNode(project_id=project.id, source_document_id=src.id, seq=seq[n.code], code=n.code, node_type=n.node_type,
                      parent=ids[n.parent] if n.parent else None, level=n.level, name=n.name, wbs_code=n.wbs_code,
                      discipline=n.discipline, area=n.area, activity_type=n.activity_type, planned_start=n.planned_start,
                      planned_finish=n.planned_finish, planned_duration_days=n.planned_duration_days,
                      planned_qty=n.planned_qty, qty_unit=n.qty_unit, actual_start=n.actual_start, actual_finish=n.actual_finish)
        if n.node_type == "activity":
            pn.tags = [PlanTag(tag=t) for t in extract_tags(n.name)]
        ids[n.code] = pn
        session.add(pn)
    session.flush()
    for n in nodes:
        for d in n.predecessors:
            session.add(PlanDependency(successor_id=ids[n.code].id, predecessor_id=ids[d.predecessor].id,
                                       link_type=d.link_type, lag_days=d.lag_days))
    session.flush()
    return summarize(session, project, "imported")


def summarize(session: Session, project: Project, status: str) -> ImportResult:
    count = lambda q: session.scalar(select(func.count()).select_from(q.subquery()))
    nodes = select(PlanNode.id).where(PlanNode.project_id == project.id)
    acts = nodes.where(PlanNode.node_type == "activity")
    return ImportResult(status, project.code, count(nodes), count(acts),
                        count(select(PlanTag.tag).join(PlanNode).where(PlanNode.project_id == project.id)),
                        count(select(PlanDependency.successor_id).join(PlanNode, PlanDependency.successor_id == PlanNode.id)
                              .where(PlanNode.project_id == project.id)))


def verify_import(session: Session, project_code: str) -> list[str]:
    """Post-import integrity checks against the database itself. Returns problems (empty = OK)."""
    problems = []
    project = session.scalar(select(Project).where(Project.code == project_code))
    if project is None:
        return [f"project {project_code} not found"]
    nodes = session.scalars(select(PlanNode).where(PlanNode.project_id == project.id)).all()
    codes = [n.code for n in nodes]
    if len(codes) != len(set(codes)):
        problems.append("duplicate codes in plan_node")
    by_id = {n.id: n for n in nodes}
    roots = [n for n in nodes if n.parent_id is None]
    if len(roots) != 1 or roots[0].level != 1:
        problems.append("hierarchy must have exactly one level-1 root")
    for n in nodes:
        p = by_id.get(n.parent_id)
        if n.parent_id is not None and (p is None or n.level != p.level + 1 or p.node_type == "activity"):
            problems.append(f"{n.code}: broken parent link")
    parents = {n.parent_id for n in nodes}
    problems += [f"{n.code}: activity has children" for n in nodes if n.node_type == "activity" and n.id in parents]
    return problems


COMPARE_FIELDS = ["node_type", "level", "name", "wbs_code", "discipline", "area", "planned_start", "planned_finish",
                  "planned_duration_days", "actual_start", "actual_finish", "predecessors"]


def compare_schedules(a: list[dict], b: list[dict]) -> list[str]:
    """Differences between two parsed schedules on the fields both formats carry (activities matched by ID).
    MSPDI has no activity_type/quantity fields and no own ID for L5 summary tasks, so those are not compared."""
    diffs = []
    shape = lambda rows: sorted((r["node_type"], r["level"]) for r in rows)
    if shape(a) != shape(b):
        diffs.append("node counts by type/level differ")
    acts = lambda rows: {r["node_id"]: r for r in rows if r["node_type"] == "activity"}
    aa, bb = acts(a), acts(b)
    if set(aa) != set(bb):
        diffs.append(f"activity ID sets differ: {sorted(set(aa) ^ set(bb))[:5]}")
    for code in sorted(set(aa) & set(bb)):
        for f in COMPARE_FIELDS:
            if aa[code][f] != bb[code][f]:
                diffs.append(f"{code}.{f}: {aa[code][f]!r} != {bb[code][f]!r}")
    return diffs
