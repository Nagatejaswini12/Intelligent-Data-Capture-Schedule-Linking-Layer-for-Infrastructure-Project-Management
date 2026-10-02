r"""Phase 2 batch ingestion: store + extract + validate many reports/sheets into the database (safe to re-run).

    .venv\Scripts\python scripts\phase2\ingest_documents.py                 # the 81 synthetic DPRs + 3 sheets into data/p2e.db
    .venv\Scripts\python scripts\phase2\ingest_documents.py path\a.txt dir\  # specific files / folders (*.txt, *.xlsx)
    options: --db sqlite:///path.db   --upload-dir data\uploads   --project CODE (default: the only project)

Run scripts\phase1\init_database.py first (events belong to a project with an imported schedule).
Re-running is idempotent: identical files are recognised by SHA-256 and already-processed ones come back 'unchanged'.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from p2e.config import get_settings  # noqa: E402
from p2e.db.models import Project  # noqa: E402
from p2e.db.session import SchemaOutdated, init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.extract.pipeline import load_project_vocab  # noqa: E402
from p2e.ingest.service import DuplicateDocument, IngestError, ingest_upload, process_batch  # noqa: E402


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        files += sorted(f for f in p.iterdir() if f.suffix.lower() in (".txt", ".xlsx")) if p.is_dir() else [p]
    return files


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Ingest and extract daily progress reports / discipline sheets.")
    ap.add_argument("paths", nargs="*", type=Path,
                    default=[settings.synthetic_dir / "reports", settings.synthetic_dir / "spreadsheets"])
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--upload-dir", type=Path, default=settings.upload_dir)
    ap.add_argument("--project", help="project code (default: the only project in the database)")
    args = ap.parse_args(argv)

    engine = make_engine(args.db)
    try:
        init_db(engine)
    except SchemaOutdated as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    with make_sessionmaker(engine)() as session:
        projects = list(session.scalars(select(Project).where(Project.code == args.project) if args.project else select(Project)))
        if len(projects) != 1:
            print("FAILED: " + (f"project {args.project!r} not found" if args.project else
                                f"{len(projects)} projects in the database; pass --project (import a schedule first)"), file=sys.stderr)
            return 1
        project = projects[0]
        ids, rejected = [], 0
        for f in collect(args.paths):
            try:
                ids.append(ingest_upload(session, project, f.name, f.read_bytes(), "cli", args.upload_dir).id)
                session.commit()
            except DuplicateDocument as e:
                session.rollback()
                ids.append(e.extra["existing_document_id"])
            except (IngestError, OSError) as e:
                session.rollback()
                rejected += 1
                print(f"  rejected {f}: {getattr(e, 'detail', e)}", file=sys.stderr)
        results = process_batch(session, project, args.upload_dir, load_project_vocab(settings.glossary_path), ids)
        for r in results:
            if r["outcome"] not in ("processed", "unchanged"):
                print(f"  document {r['document_id']}: {r['outcome']} {r['error'] or ''}", file=sys.stderr)
        runs = [r["run"] for r in results if r["run"] is not None and r["run"].status == "succeeded"]
        print(f"project:    {project.code}")
        print(f"documents:  {len(ids)} ingested/recognised, {rejected} rejected")
        print(f"outcomes:   {dict(Counter(r['outcome'] for r in results))}")
        print(f"events:     {sum(r.events_total for r in runs)} ({sum(r.events_valid for r in runs)} valid, "
              f"{sum(r.events_invalid for r in runs)} invalid), issues: {sum(r.issues_count for r in runs)}")
    engine.dispose()
    return 0 if rejected == 0 and all(r["outcome"] in ("processed", "unchanged") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
