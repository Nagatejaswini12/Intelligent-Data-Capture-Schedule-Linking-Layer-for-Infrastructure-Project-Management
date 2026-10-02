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
    Base.metadata.create_all(engine)
    if "conflict" not in {c["name"] for c in inspect(engine).get_columns("event_link")}:
        with engine.begin() as conn:    # Phase 3.1 additive, nullable column: existing Phase 3 databases keep their decisions
            conn.execute(text("ALTER TABLE event_link ADD COLUMN conflict JSON"))


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
