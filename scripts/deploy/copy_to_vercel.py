"""Copy the local demo database (SQLite) into the Vercel Postgres (Neon) database, and the raw uploads into Vercel Blob.

Run once from your PC after creating the database and the Blob store in the Vercel dashboard:
    set DATABASE_URL=<Neon connection string from Vercel>          (Storage -> your database -> .env.local tab)
    set BLOB_READ_WRITE_TOKEN=<token from Vercel>                  (Storage -> your Blob store -> .env.local tab; optional)
    .venv\\Scripts\\python scripts\\deploy\\copy_to_vercel.py
The target tables must be empty (refuses otherwise); --source defaults to data/p2e.db.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, inspect, select, text  # noqa: E402

from p2e.config import REPO_ROOT, db_url_from_env, get_settings  # noqa: E402
from p2e.db.models import AccessRequest, Base  # noqa: E402,F401  (AccessRequest: registers its table)
from p2e.db.session import init_db, make_engine  # noqa: E402
from p2e.ingest.service import store_blob  # noqa: E402


def copy(source_url: str, target_url: str) -> dict[str, int]:
    src, dst = make_engine(source_url), make_engine(target_url)
    init_db(dst)
    counts = {}
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:                # parents before children (foreign keys)
            if not inspect(src).has_table(table.name):
                continue
            if d.scalar(select(func.count()).select_from(table)):
                raise SystemExit(f"target table {table.name} is not empty; use a fresh database")
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            if rows:
                d.execute(table.insert(), rows)
            counts[table.name] = len(rows)
            pk = list(table.primary_key.columns)
            if dst.dialect.name == "postgresql" and rows and len(pk) == 1 and isinstance(rows[0][pk[0].name], int):
                d.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "   # ids copied:
                               f"(SELECT MAX({pk[0].name}) FROM {table.name}))"))                         # move sequence on
    return counts


def upload_files(upload_dir: Path) -> int:
    files = [p for p in upload_dir.glob("*") if p.is_file() and not p.name.endswith(".tmp")]
    for p in files:
        store_blob(upload_dir, p.stem, p.suffix.lstrip("."), p.read_bytes())
    return len(files)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=f"sqlite:///{(REPO_ROOT / 'data' / 'p2e.db').as_posix()}")
    ap.add_argument("--target", default=db_url_from_env(""))
    args = ap.parse_args()
    if not args.target or args.target.startswith("sqlite"):
        raise SystemExit("set DATABASE_URL (or --target) to the Vercel Postgres connection string")
    for name, n in copy(args.source, args.target).items():
        print(f"{name:28} {n:6} rows")
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        print(f"uploaded {upload_files(get_settings().upload_dir)} raw files to Vercel Blob")
    else:
        print("BLOB_READ_WRITE_TOKEN not set: raw upload files were not copied (evidence views need them)")
