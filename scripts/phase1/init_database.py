r"""Phase 1: create the database and import the Phase 0 synthetic schedule (safe to re-run).

    .venv\Scripts\python scripts\phase1\init_database.py            # data/p2e.db from data/synthetic/schedule/schedule.csv
    .venv\Scripts\python scripts\phase1\init_database.py --rebuild  # delete the SQLite file first
    options: --db sqlite:///path.db   --schedule path/to/schedule.csv|.xml|.xer (Primavera P6)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.engine import make_url  # noqa: E402

from p2e.config import get_settings  # noqa: E402
from p2e.db.session import SchemaOutdated, init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.plan.importers import (ImportConflict, ScheduleValidationError, compare_schedules, import_schedule,  # noqa: E402
                                read_schedule, verify_import)


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Create the P2E database and import the synthetic schedule.")
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--schedule", type=Path, default=settings.synthetic_dir / "schedule" / "schedule.csv")
    ap.add_argument("--rebuild", action="store_true", help="delete the SQLite database file before importing")
    args = ap.parse_args(argv)

    url = make_url(args.db)
    if args.rebuild:
        if url.get_backend_name() != "sqlite" or not url.database:
            print("--rebuild only supports file-based SQLite URLs", file=sys.stderr)
            return 2
        Path(url.database).unlink(missing_ok=True)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    engine = make_engine(args.db)
    try:
        init_db(engine)
    except SchemaOutdated as e:
        print(f"IMPORT FAILED: {e}", file=sys.stderr)
        return 1
    try:
        parsed = read_schedule(args.schedule)
        data_date = None
        manifest = args.schedule.parent.parent / "manifest.json"   # Phase 0 dataset carries the status date here
        if parsed.data_date is None and manifest.exists():
            data_date = date.fromisoformat(json.loads(manifest.read_text(encoding="utf-8"))["data_date"])
        with make_sessionmaker(engine).begin() as session:
            result = import_schedule(session, parsed, data_date)
            problems = verify_import(session, result.project_code)
            if problems:
                raise ScheduleValidationError(problems)
    except (ScheduleValidationError, ImportConflict) as e:
        print(f"IMPORT FAILED: {e}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    print(f"database:      {url.database if url.get_backend_name() == 'sqlite' else url.render_as_string(hide_password=True)}")
    print(f"source:        {args.schedule} ({parsed.format}, sha256 {parsed.sha256[:12]}...)")
    print(f"status:        {result.status}" + ("  (same file already imported; nothing changed)" if result.status == "unchanged" else ""))
    print(f"project:       {result.project_code}")
    print(f"nodes:         {result.node_count}")
    print(f"L5/L6 acts:    {result.activity_count}")
    print(f"tags:          {result.tag_count}   logic links: {result.dependency_count}")
    print(f"integrity:     OK (unique codes, single L1 root, levels nest, activities are leaves)")
    other = args.schedule.with_suffix(".xml" if parsed.format == "csv" else ".csv")
    if other.exists():
        diffs = compare_schedules(parsed.rows, read_schedule(other).rows)
        print(f"{other.name + ':':<15}" + ("compatible (same activities, hierarchy shape, dates, logic)" if not diffs
                                           else f"{len(diffs)} difference(s): {diffs[:3]}"))
    print(f"elapsed:       {elapsed:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
