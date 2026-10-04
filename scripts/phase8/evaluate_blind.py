r"""Upgrade W5: honest numbers on field reports written by people OUTSIDE the team (a "blind set").

    .venv\Scripts\python scripts\phase8\evaluate_blind.py                       # data\blind\
    .venv\Scripts\python scripts\phase8\evaluate_blind.py --blind path\to\set --out eval\blind_report.json

The blind folder holds the reports (.txt / .docx DPRs, .xlsx / .csv sheets) and labels.csv written by the same outside
person BEFORE seeing the system's output:

    file,activity_code,event_type,event_date
    my_dpr_1.txt,PIP-A3-1203-ERC,start,2026-09-14
    my_dpr_1.txt,NEW,finish,2026-09-14          # work that is not in the schedule

Everything runs on a fresh temporary database (synthetic schedule + glossary); nothing else is touched.
Reported: wrong automatic links (the number that matters), automatic precision and coverage, review rate (and whether
the right activity was in the top 3), NEW-work flagged, and items the extractor missed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from p2e.config import get_settings  # noqa: E402
from p2e.db.models import EventLink, LinkCandidate, PlanNode, ProgressEvent, Project, SourceDocument  # noqa: E402
from p2e.db.session import init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.extract.pipeline import load_project_vocab  # noqa: E402
from p2e.ingest.service import KINDS, ingest_upload, process_batch  # noqa: E402
from p2e.link import service as linking  # noqa: E402
from p2e.link.context import refresh_context  # noqa: E402
from p2e.plan.importers import import_schedule, read_schedule  # noqa: E402


def evaluate(blind: Path, data_dir: Path) -> dict:
    labels_path = blind / "labels.csv"
    if not labels_path.exists():
        raise SystemExit(f"FAILED: {labels_path} not found (see the format at the top of this script)")
    with labels_path.open(encoding="utf-8-sig") as fh:
        labels = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    files = sorted(p for p in blind.iterdir() if p.suffix.lower() in KINDS and p.name != labels_path.name)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        refresh_context()
        engine = make_engine(f"sqlite:///{(tmp / 'blind.db').as_posix()}")
        init_db(engine)
        sm = make_sessionmaker(engine)
        manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
        with sm.begin() as session:
            import_schedule(session, read_schedule(data_dir / "schedule" / "schedule.csv"), date.fromisoformat(manifest["data_date"]))
        with sm() as session:
            project = session.scalar(select(Project))
            ids = [ingest_upload(session, project, f.name, f.read_bytes(), "blind-eval", tmp / "up").id for f in files]
            session.commit()
            processed = process_batch(session, project, tmp / "up", load_project_vocab(data_dir / "glossary.json"), ids)
            linking.link_events(session, project, data_dir / "glossary.json")
            session.commit()
            rows = session.execute(select(ProgressEvent, SourceDocument.filename, EventLink)
                                   .join(SourceDocument, SourceDocument.id == ProgressEvent.source_document_id)
                                   .join(EventLink, EventLink.progress_event_id == ProgressEvent.id, isouter=True)
                                   .where(ProgressEvent.validation_status == "valid")).all()
            code = dict(session.execute(select(PlanNode.id, PlanNode.code)).all())
            top3: dict[int, set] = {}
            for c in session.scalars(select(LinkCandidate).where(LinkCandidate.rank <= 3)):
                top3.setdefault(c.link_id, set()).add(code.get(c.plan_node_id))
            pool = [{"file": fn, "type": ev.event_type, "date": ev.event_date.isoformat() if ev.event_date else "",
                     "decision": link.decision if link else "none", "code": code.get(link.plan_node_id) if link else None,
                     "top3": top3.get(link.id, set()) if link else set(), "used": False} for ev, fn, link in rows]
        engine.dispose()
    outcome, wrong = Counter(), []
    for lab in labels:
        same = [p for p in pool if not p["used"] and p["file"] == lab["file"] and p["type"] == lab["event_type"]
                and p["date"] == lab["event_date"]]
        pick = next((p for p in same if p["code"] == lab["activity_code"]), None) or \
               next((p for p in same if lab["activity_code"] in p["top3"]), None) or (same[0] if same else None)
        if pick is None:
            outcome["missed_by_extraction"] += 1
            continue
        pick["used"] = True
        new = lab["activity_code"].upper() == "NEW"
        if pick["decision"] == "matched":
            if not new and pick["code"] == lab["activity_code"]:
                outcome["auto_correct"] += 1
            else:
                outcome["auto_wrong"] += 1
                wrong.append({**lab, "linked_to": pick["code"]})
        elif pick["decision"] == "review":
            outcome["review_right_in_top3" if lab["activity_code"] in pick["top3"] else
                    ("review_new_work" if new else "review_not_in_top3")] += 1
        else:
            outcome["flagged_new_correct" if new else "flagged_but_planned"] += 1
    auto, n = outcome["auto_correct"] + outcome["auto_wrong"], len(labels)
    return {"blind_dir": str(blind), "files": len(files), "labels": n,
            "processing": dict(Counter(p["outcome"] for p in processed)), "outcomes": dict(outcome),
            "auto_precision": round(outcome["auto_correct"] / auto, 4) if auto else None,
            "auto_coverage": round(auto / n, 4) if n else None,
            "wrong_automatic_links": outcome["auto_wrong"], "wrong_examples": wrong[:20],
            "extraction_recall": round((n - outcome["missed_by_extraction"]) / n, 4) if n else None}


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Score extraction + linking on an outside-written blind set.")
    ap.add_argument("--blind", type=Path, default=Path("data") / "blind")
    ap.add_argument("--data", type=Path, default=settings.synthetic_dir)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    r = evaluate(args.blind, args.data)
    print(f"blind set:              {r['files']} files, {r['labels']} labelled items")
    print(f"WRONG automatic links:  {r['wrong_automatic_links']}")
    print(f"automatic precision:    {r['auto_precision']}   coverage: {r['auto_coverage']}")
    print(f"extraction recall:      {r['extraction_recall']}")
    print(f"outcomes:               {r['outcomes']}")
    if args.out:
        args.out.write_text(json.dumps(r, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
