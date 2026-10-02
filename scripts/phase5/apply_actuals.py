r"""Phase 5: apply actuals from accepted links to the schedule (audited, idempotent), optionally export the schedule.

    .venv\Scripts\python scripts\phase5\apply_actuals.py --dry-run               # show what would change, write nothing
    .venv\Scripts\python scripts\phase5\apply_actuals.py --as-of 2026-09-16      # apply (audit entries actor process:auto-apply)
    .venv\Scripts\python scripts\phase5\apply_actuals.py --export exports\schedule   # also write CSV + MSPDI
    options: --db sqlite:///path.db   --project CODE

Run after scripts\phase3\link_events.py. Every change can be reverted with POST .../audit/{id}/undo.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from p2e.config import get_settings  # noqa: E402
from p2e.db.models import Project  # noqa: E402
from p2e.db.session import SchemaOutdated, init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.decide import apply as engine  # noqa: E402
from p2e.plan import exporters  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Apply actuals from linked progress events; optionally export the schedule.")
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--project")
    ap.add_argument("--as-of", type=date.fromisoformat, help="latest allowed actual date (default: today, project timezone)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export", type=Path, help="write <code>-actuals.csv and .xml to this directory")
    args = ap.parse_args(argv)
    eng = make_engine(args.db)
    try:
        init_db(eng)
    except SchemaOutdated as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    with make_sessionmaker(eng)() as session:
        projects = list(session.scalars(select(Project).where(Project.code == args.project) if args.project else select(Project)))
        if len(projects) != 1:
            print("FAILED: pass --project (none or several projects)", file=sys.stderr)
            return 1
        project = projects[0]
        as_of = args.as_of or datetime.now(ZoneInfo(project.timezone)).date()
        r = engine.apply(session, project, as_of, dry_run=args.dry_run)
        changed = Counter(f for x in r["applied"] for f in (x.changes if args.dry_run else x.changes))
        session.rollback() if args.dry_run else session.commit()
        print(f"project:   {project.code}   as of {as_of}{'   (dry run: nothing written)' if args.dry_run else ''}")
        print(f"applied:   {len(r['applied'])} activities  fields {dict(changed)}")
        print(f"blocked:   {len(r['blocked'])} activities (review queue)  {dict(Counter(b.split(':')[0].split(' (')[0] for p in r['blocked'] for b in p.blockers))}")
        print(f"unchanged: {r['unchanged']}")
        if args.export:
            args.export.mkdir(parents=True, exist_ok=True)
            data = exporters.rows(session, project)
            (args.export / f"{project.code}-actuals.csv").write_text(exporters.to_csv(data), encoding="utf-8", newline="")
            (args.export / f"{project.code}-actuals.xml").write_bytes(exporters.to_mspdi(project, data, as_of))
            print(f"export:    {args.export}")
    eng.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
