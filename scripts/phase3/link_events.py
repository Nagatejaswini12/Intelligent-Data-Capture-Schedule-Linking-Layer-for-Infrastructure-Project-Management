r"""Phase 3: link the database's valid progress events to L5/L6 schedule activities (safe to re-run), optionally export OKF.

    .venv\Scripts\python scripts\phase3\link_events.py                    # link events in data/p2e.db
    .venv\Scripts\python scripts\phase3\link_events.py --okf exports\okf  # also write the OKF v0.2 knowledge bundle
    options: --db sqlite:///path.db   --project CODE (default: the only project)

Run scripts\phase1\init_database.py and scripts\phase2\ingest_documents.py first. The LLM tie-breaker is used only if
P2E_LLM_ENDPOINT points at a self-hosted endpoint (see p2e/link/adjudicate.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select  # noqa: E402

from p2e.config import get_settings  # noqa: E402
from p2e.db.models import EventLink, Project  # noqa: E402
from p2e.db.session import SchemaOutdated, init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.link import adjudicate, service  # noqa: E402
from p2e.link.context import get_context  # noqa: E402
from p2e.memory import okf  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Link progress events to schedule activities; optionally export OKF.")
    ap.add_argument("--db", default=settings.db_url)
    ap.add_argument("--project", help="project code (default: the only project in the database)")
    ap.add_argument("--okf", type=Path, help="write the OKF knowledge bundle to this directory")
    args = ap.parse_args(argv)
    engine = make_engine(args.db)
    try:
        init_db(engine)
        llm = adjudicate.from_env()
    except (SchemaOutdated, ValueError) as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    with make_sessionmaker(engine)() as session:
        projects = list(session.scalars(select(Project).where(Project.code == args.project) if args.project else select(Project)))
        if len(projects) != 1:
            print("FAILED: " + (f"project {args.project!r} not found" if args.project else
                                f"{len(projects)} projects in the database; pass --project"), file=sys.stderr)
            return 1
        project = projects[0]
        out = service.link_events(session, project, settings.glossary_path, llm=llm)
        session.commit()
        print(f"project:          {project.code}")
        print(f"versions:         linker {out['linker_version']}  context (CAG) {out['context_version']}  aliases (MAG) {out['mag_version']}")
        print(f"this run:         {out['counts']}  (linker decisions before the conflict layer)")
        print(f"conflict layer:   {out['conflicts']}")
        totals = dict(session.execute(select(EventLink.decision, func.count()).where(EventLink.project_id == project.id)
                                      .group_by(EventLink.decision)).all())
        print(f"stored decisions: {totals}")
        print(f"LLM tie-breaker:  {'on' if llm is not None else 'off (P2E_LLM_ENDPOINT not set)'}")
        if args.okf:
            files = okf.build_bundle(session, project, get_context(session, project, settings.glossary_path))
            problems = okf.conformance_problems(files)
            okf.write_bundle(files, args.okf)
            print(f"OKF v{okf.OKF_VERSION}:          {len(files)} files -> {args.okf} ({'conformant' if not problems else problems})")
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
