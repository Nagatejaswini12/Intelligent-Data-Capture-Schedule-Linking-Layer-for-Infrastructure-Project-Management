from __future__ import annotations

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from p2e.db.models import Base


def make_engine(db_url: str) -> Engine:
    engine = create_engine(db_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _record):   # SQLite ignores foreign keys unless asked per connection
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


class SchemaOutdated(RuntimeError):
    pass


def init_db(engine: Engine) -> None:
    """Create missing tables (idempotent). Alembic migrations take over in Phase 5; until then a database created by
    an earlier phase is detected and must be rebuilt (it only holds re-importable synthetic data)."""
    insp = inspect(engine)
    if insp.has_table("source_document") and "status" not in {c["name"] for c in insp.get_columns("source_document")}:
        raise SchemaOutdated("database was created before Phase 2 (missing source_document.status); rebuild it with "
                             "scripts/phase1/init_database.py --rebuild")
    if engine.dialect.name == "sqlite" and insp.has_table("source_document"):   # SQLite cannot widen a CHECK in place (W4)
        with engine.connect() as conn:
            ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'source_document'")).scalar() or ""
        if "'xlsx'" in ddl and "'docx'" not in ddl:
            raise SchemaOutdated("database predates .docx / .xer support; rebuild it with "
                                 "scripts/phase1/init_database.py --rebuild")
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    for table, column, ddl in (("event_link", "conflict", "JSON"),          # Phase 3.1
                               ("plan_node", "percent_complete", "FLOAT"),   # Phase 5
                               ("audit_log", "entry_hash", "VARCHAR(64)"),   # Phase 7
                               ("project", "shadow_mode", "BOOLEAN NOT NULL DEFAULT 0")):   # upgrade W5
        if column not in {c["name"] for c in insp.get_columns(table)}:
            with engine.begin() as conn:    # additive, nullable: existing databases keep all their data
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
