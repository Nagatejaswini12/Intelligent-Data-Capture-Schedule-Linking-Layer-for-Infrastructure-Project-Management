r"""Upgrade W3: write the daily / weekly project-manager report (printable HTML) to a folder.

    .venv\Scripts\python scripts\phase8\generate_reports.py                          # daily report, today
    .venv\Scripts\python scripts\phase8\generate_reports.py --period weekly --as-of 2026-09-16
    options: --db sqlite:///path.db   --project CODE   --out exports\reports

Schedule it daily with Windows Task Scheduler (or cron). Open the file in a browser; "Save as PDF" gives the PDF.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from p2e.analytics import report  # noqa: E402
from p2e.config import get_settings  # noqa: E402
from p2e.db.models import Project  # noqa: E402
from p2e.db.session import SchemaOutdated, init_db, make_engine, make_sessionmaker  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Write the project-manager report as HTML.")
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--project")
    ap.add_argument("--as-of", type=date.fromisoformat, help="default: today in the project timezone")
    ap.add_argument("--period", choices=sorted(report.PERIOD_DAYS), default="daily")
    ap.add_argument("--out", type=Path, default=Path("exports") / "reports")
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
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"{project.code}-{args.period}-report-{as_of}.html"
        path.write_text(report.pm_report(session, project, as_of, args.period), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
