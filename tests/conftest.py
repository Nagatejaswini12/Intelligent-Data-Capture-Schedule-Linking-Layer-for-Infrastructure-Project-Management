"""Shared fixtures: the Phase 0 schedule is the only source of truth; every test DB is a temp SQLite file."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from p2e.db.session import init_db, make_engine, make_sessionmaker
from p2e.main import create_app
from p2e.plan.importers import import_schedule, read_schedule

SYNTH = Path(__file__).resolve().parents[1] / "data" / "synthetic"
SCHEDULE_CSV = SYNTH / "schedule" / "schedule.csv"
SCHEDULE_XML = SYNTH / "schedule" / "schedule.xml"
MANIFEST = json.loads((SYNTH / "manifest.json").read_text(encoding="utf-8"))
DATA_DATE = date.fromisoformat(MANIFEST["data_date"])


def csv_rows() -> list[dict]:
    with open(SCHEDULE_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def new_db(path: Path):
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    return engine, make_sessionmaker(engine)


def load(sm, schedule: Path = SCHEDULE_CSV):
    with sm.begin() as session:
        return import_schedule(session, read_schedule(schedule), DATA_DATE)


@pytest.fixture
def empty_db(tmp_path):
    engine, sm = new_db(tmp_path / "test.db")
    yield sm
    engine.dispose()


@pytest.fixture(scope="session")
def imported_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "p2e.db"
    engine, sm = new_db(path)
    load(sm)
    yield path, sm
    engine.dispose()


@pytest.fixture(scope="session")
def client(imported_db):
    app = create_app(f"sqlite:///{imported_db[0].as_posix()}")
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()
