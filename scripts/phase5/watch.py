r"""Silent-activity watch: activities the plan expects to be active that no field report mentioned recently.

    .venv\Scripts\python scripts\phase5\watch.py --as-of 2026-09-16               # whole project, 3-day window
    .venv\Scripts\python scripts\phase5\watch.py --days 5 --discipline piping
    options: --db sqlite:///path.db   --project CODE   --area A3   --limit 30
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
from p2e.db.session import init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.decide import watch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="List silent activities (expected active, no recent field report).")
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--project")
    ap.add_argument("--as-of", type=date.fromisoformat)
    ap.add_argument("--days", type=int, default=watch.WATCH_DAYS)
    ap.add_argument("--discipline")
    ap.add_argument("--area")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)
    eng = make_engine(args.db)
    init_db(eng)
    with make_sessionmaker(eng)() as session:
        projects = list(session.scalars(select(Project).where(Project.code == args.project) if args.project else select(Project)))
        if len(projects) != 1:
            print("FAILED: pass --project (none or several projects)", file=sys.stderr)
            return 1
        project = projects[0]
        as_of = args.as_of or datetime.now(ZoneInfo(project.timezone)).date()
        items = watch.silent_activities(session, project, as_of, args.days, args.discipline, args.area)
        print(f"{project.code}: {len(items)} silent activities as of {as_of} (no report in {args.days} days)  "
              f"{dict(Counter(i['expectation'] for i in items))}")
        for i in items[: args.limit]:
            last = f"last report {i['last_reported']} ({i['days_silent']} d)" if i["last_reported"] else "never reported"
            print(f"  {i['plan_node_code']:<22} {i['activity_name'][:45]:<45} {last:<32} {i['expectation']}")
    eng.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
