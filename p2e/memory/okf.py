"""OKF export: the project's stable linking knowledge as an Open Knowledge Format v0.2 bundle (Markdown + YAML frontmatter).

Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md (v0.2). SQLite stays the source of
truth; the bundle is a generated, read-only export. Frontmatter uses the spec's fields: type (required), title,
description, tags, generated {by, at}, sources [{id, resource, title, last_modified}], verified [{by, at}], status,
stale_after. `verified` is written only for confirmed aliases, with the actor that confirmed them: `human:<api role>` for a
planner confirmation through the API (role keys, no personal accounts yet) or `process:<id>` for an automated replay.
Everything else carries no `verified` key, i.e. it is honestly unverified.

    bundle/
      index.md                (okf_version 0.2)   log.md
      project/overview.md  project/glossary.md  project/matching-rules.md
      schedule/<activity-type>.md                 one concept per activity family
      aliases/index.md  aliases/<kind>-<phrase>.md one concept per active or revoked alias
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e import __version__
from p2e.db.models import Alias, PlanNode, Project, SourceDocument
from p2e.link.context import RULES_PATH, ProjectContext
from p2e.link.decide import LINKER_VERSION, WEIGHTS
from p2e.memory import knowledge

OKF_VERSION = "0.2"
PRODUCER = f"p2e-okf-export/{__version__}"
SCHEDULE_STALE_AFTER = timedelta(days=7)   # producer policy: schedule concepts are re-exported at least weekly


def _ts(d: datetime) -> str:
    if d.tzinfo is None:                     # SQLite returns naive datetimes; they were written in UTC
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "item"


def _doc(front: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000) + "---\n\n" + body.rstrip() + "\n"


def build_bundle(session: Session, project: Project, ctx: ProjectContext, now: datetime | None = None) -> dict[str, str]:
    """-> {bundle-relative path: file text}. Deterministic for the same database state and `now`."""
    now = now or datetime.now(timezone.utc)
    gen = {"by": PRODUCER, "at": _ts(now)}
    files: dict[str, str] = {}
    sched = session.scalars(select(SourceDocument).where(SourceDocument.project_id == project.id,
                                                         SourceDocument.kind == "schedule_import").order_by(SourceDocument.id)).all()
    sched_sources = [{"id": f"schedule-{d.id}", "resource": f"p2e://projects/{project.code}/source_documents/{d.id}",
                      "title": f"{d.filename} (sha256 {d.sha256[:12]})", "last_modified": _ts(d.created_at)} for d in sched]
    nodes = session.scalars(select(PlanNode).options(selectinload(PlanNode.tags))
                            .where(PlanNode.project_id == project.id, PlanNode.node_type == "activity").order_by(PlanNode.seq)).all()

    files["project/overview.md"] = _doc(
        {"type": "Project", "title": f"{project.code}: {project.name}", "description": "Project identity, data date and schedule size.",
         "tags": ["project"], "generated": gen, "sources": sched_sources},
        f"# Project\n\n| Field | Value |\n|---|---|\n| Code | `{project.code}` |\n| Name | {project.name} |\n"
        f"| Timezone | {project.timezone} |\n| Data date | {project.data_date or '-'} |\n| Executable L5/L6 activities | {len(nodes)} |\n"
        f"| Disciplines | {', '.join(ctx.disciplines)} |\n| Areas | {', '.join(ctx.areas)} |\n\n"
        "See the [glossary](/project/glossary.md), the [matching rules](/project/matching-rules.md) and the "
        "[confirmed aliases](/aliases/index.md).\n")

    gpath = Path(ctx.sources["glossary"]["path"])
    rows = "\n".join(f"| `{k}` | {v} |" for k, v in sorted(ctx.expansions.items()))
    files["project/glossary.md"] = _doc(
        {"type": "Glossary", "title": "Field abbreviations and Hinglish terms",
         "description": "How site reports abbreviate work; used to normalise report text before matching.",
         "tags": ["glossary", "cag"], "generated": gen,
         "sources": [{"id": "glossary", "resource": gpath.name, "title": f"project glossary (sha256 {ctx.sources['glossary']['sha256'][:12]})"}]},
        f"# Terms\n\nPart of the cached project context (CAG version `{ctx.version}`).[^glossary]\n\n| Field term | Meaning |\n|---|---|\n{rows}\n\n"
        "[^glossary]: project glossary\n")

    acts = "\n".join(f"| `{a}` | {', '.join(ts)} |" for a, ts in ctx.actions.items())
    files["project/matching-rules.md"] = _doc(
        {"type": "Matching Rules", "title": "Schedule-linking rules",
         "description": "Work-action lexicon, novelty markers, weights and thresholds the linker applies.",
         "tags": ["linking", "rules", "cag"], "generated": gen, "linker_version": LINKER_VERSION, "context_version": ctx.version,
         "sources": [{"id": "rules", "resource": RULES_PATH.name, "title": f"matching rules (sha256 {ctx.sources['rules']['sha256'][:12]})"}]},
        "# Decision\n\nAn event is linked automatically only when the object (tag, confirmed alias or the single activity with "
        "the reported discipline/area/action) and the reported work action both agree, the area does not conflict and the "
        "runner-up is clearly weaker; otherwise it goes to planner review. Reports of extra/unplanned work and unknown tags "
        "are flagged unmatched.[^rules]\n\n"
        f"# Weights\n\n```json\n{json.dumps(WEIGHTS, indent=2)}\n```\n\n# Thresholds\n\n```json\n{json.dumps(ctx.thresholds, indent=2)}\n```\n\n"
        f"# Work actions\n\n| Action | Field terms |\n|---|---|\n{acts}\n\n# Novelty markers\n\n{', '.join(ctx.novelty)}\n\n"
        "[^rules]: matching rules\n")

    families: dict[str, list[PlanNode]] = defaultdict(list)
    for n in nodes:
        families[n.activity_type or "Other"].append(n)
    stale = _ts(now + SCHEDULE_STALE_AFTER)
    sched_index = []
    for fam, ns in sorted(families.items()):
        path = f"schedule/{_slug(fam)}.md"
        table = "\n".join(f"| `{n.code}` | {n.name} | {n.discipline or '-'} | {n.area or '-'} | {n.planned_start} | {n.planned_finish} | "
                          f"{', '.join(t.tag for t in n.tags) or '-'} |" for n in ns)
        desc = f"{len(ns)} executable activities of type {fam}."
        files[path] = _doc(
            {"type": "Schedule Activity Family", "title": fam, "description": desc, "tags": ["schedule", _slug(fam)],
             "generated": gen, "sources": sched_sources, "stale_after": stale},
            f"# Activities\n\n| Code | Name | Discipline | Area | Planned start | Planned finish | Tags |\n|---|---|---|---|---|---|---|\n{table}\n")
        sched_index.append(f"* [{fam}](/{path}) - {desc}")

    aliases = session.scalars(select(Alias).options(selectinload(Alias.node), selectinload(Alias.source_event))
                              .where(Alias.project_id == project.id).order_by(Alias.kind, Alias.phrase)).all()
    alias_index = []
    for a in aliases:
        path = f"aliases/{a.kind}-{_slug(a.phrase)}.md"
        ev = a.source_event
        desc = f"Field wording '{a.phrase}' means {a.target} ({a.kind})."
        files[path] = _doc(
            {"type": "Terminology Alias", "title": a.phrase, "description": desc, "tags": ["alias", "mag", a.kind],
             "status": "stable" if a.status == "active" else "deprecated",
             "generated": {"by": PRODUCER, "at": _ts(a.updated_at)},
             "verified": [{"by": a.confirmed_by, "at": _ts(a.updated_at)}],   # actor as stored: human:<role> or process:<id>
             "sources": [{"id": "event", "resource": f"p2e://projects/{project.code}/events/{ev.id}",
                          "title": f"confirmed report text: {ev.source_text}"}],
             "kind": a.kind, "target": a.target, "learned_from_activity": a.node.code, "confirmations": a.confirmations,
             "use_count": a.use_count, "mag_version": a.mag_version},
            f"# Alias\n\n'{a.phrase}' -> `{a.target}`. Learned when a planner confirmed the report below as activity "
            f"`{a.node.code}` ({a.node.name}).[^event]\n\n| Field | Value |\n|---|---|\n| Status | {a.status} |\n"
            f"| Confirmations | {a.confirmations} |\n| Used in automatic matches | {a.use_count} |\n| Created | {_ts(a.created_at)} |\n\n"
            "[^event]: confirmed report text\n")
        alias_index.append(f"* [{a.phrase}](/{path}) - {desc}")
    know_index = []
    for k in knowledge.entries(session, project, now.date()):         # Phase 6: institutional knowledge
        path = f"knowledge/{k['id']}.md"
        refs = [{"id": f"r{i}", "resource": f"p2e://projects/{project.code}/{'activities' if c['kind'] == 'activity' else 'events'}/{c['id']}",
                 "title": c["text"][:200]} for i, c in enumerate(k["citations"], 1)]
        table = "\n".join(f"| {c['id']} | {c['text']} | {c.get('date') or '-'} |" for c in k["citations"])
        files[path] = _doc(
            {"type": "Knowledge Entry", "title": k["title"], "description": k["text"], "tags": ["knowledge", k["kind"]],
             "generated": gen, "sources": refs, "values": k["values"]},
            f"# Finding\n\n{k['text']}\n\n# Evidence\n\n| Record | Text | Date |\n|---|---|---|\n{table}\n")
        know_index.append(f"* [{k['title']}](/{path}) - {k['text']}")
    if know_index:
        files["knowledge/index.md"] = "# Institutional knowledge\n\n" + "\n".join(know_index) + "\n"
    files["aliases/index.md"] = "# Confirmed aliases (MAG)\n\n" + ("\n".join(alias_index) if alias_index else "* (none confirmed yet)") + "\n"
    files["schedule/index.md"] = "# Schedule activity families\n\n" + "\n".join(sched_index) + "\n"
    files["index.md"] = _doc({"okf_version": OKF_VERSION}, (
        f"# Project\n\n* [Overview](/project/overview.md) - Project identity, data date and schedule size.\n"
        "* [Glossary](/project/glossary.md) - How site reports abbreviate work.\n"
        "* [Matching rules](/project/matching-rules.md) - What the linker applies.\n\n"
        "# Knowledge\n\n* [Schedule activity families](schedule/) - One concept per activity type.\n"
        "* [Confirmed aliases](aliases/) - Field wording learned from planner confirmations.\n"
        "* [Institutional knowledge](knowledge/) - Actual durations and delay patterns from the project history.\n"))
    log = defaultdict(list)
    log[now.date().isoformat()].append(f"* **Update**: Exported by {PRODUCER} (context `{ctx.version}`, {len(aliases)} aliases).")
    for a in aliases:
        log[a.created_at.date().isoformat()].append(f"* **Creation**: Alias [{a.phrase}](/aliases/{a.kind}-{_slug(a.phrase)}.md) confirmed by {a.confirmed_by}.")
    for d in sched:
        log[d.created_at.date().isoformat()].append(f"* **Initialization**: Schedule {d.filename} imported.")
    files["log.md"] = "# Directory Update Log\n\n" + "\n\n".join(f"## {day}\n" + "\n".join(items) for day, items in sorted(log.items(), reverse=True)) + "\n"
    return files


def write_bundle(files: dict[str, str], out_dir: Path) -> None:
    for rel, text in files.items():
        p = Path(out_dir) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


def zip_bundle(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, text in sorted(files.items()):
            z.writestr(rel, text)
    return buf.getvalue()


def conformance_problems(files: dict[str, str]) -> list[str]:
    """OKF v0.2 §11: every non-reserved .md has parseable frontmatter with a non-empty `type`."""
    problems = []
    for rel, text in files.items():
        if rel.split("/")[-1] in ("index.md", "log.md"):
            continue
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        try:
            front = yaml.safe_load(m.group(1)) if m else None
        except yaml.YAMLError as e:
            problems.append(f"{rel}: frontmatter not parseable ({e})")
            continue
        if not isinstance(front, dict) or not front.get("type"):
            problems.append(f"{rel}: missing frontmatter `type`")
    return problems
