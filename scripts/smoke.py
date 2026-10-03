r"""End-to-end smoke test over HTTP (testing plan: seed -> upload 3 formats -> check counts -> export valid XML).

    .venv\Scripts\python scripts\smoke.py                                  # in-process: temporary DB + the real FastAPI app
    .venv\Scripts\python scripts\smoke.py --base-url http://localhost:8000 --api-key <planner key>   # against a running server

Uses only the public API: upload a text DPR, a spreadsheet and a Time Agent message, process, link, apply, then check
counts, the audit trail, the audit hash chain and that the MSPDI export is well-formed XML. Exit code 0 = all checks passed.
The in-process mode never touches data/p2e.db.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "synthetic"
KEY = "smoke-planner-key-0123456789"


def run(client, key: str, as_of: str = "2026-09-16") -> list[tuple[str, bool, str]]:
    from defusedxml import ElementTree as SafeET

    h = {"X-API-Key": key}
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), str(detail)))
        return ok

    check("health", client.get("/health").json().get("status") == "ok")
    projects = client.get("/api/v1/projects").json()
    if not check("schedule imported", projects, projects):
        return checks
    base = f"/api/v1/projects/{projects[0]['code']}"
    dpr = (DATA / "reports" / "dpr_2026-09-10_piping.txt").read_bytes()
    sheet = (DATA / "spreadsheets" / "instrument_installation_register.xlsx").read_bytes()
    docs = []
    for name, data in (("smoke_dpr.txt", dpr), ("smoke_sheet.xlsx", sheet)):
        r = client.post(f"{base}/documents", files={"file": (name, data)}, headers=h)
        if r.status_code == 409:                       # already ingested on this server: reuse it
            docs.append(r.json()["detail"]["existing_document_id"])
        elif check(f"upload {name}", r.status_code == 201, r.text[:200]):
            docs.append(r.json()["id"])
    for d in docs:
        out = client.post(f"{base}/documents/{d}/process", headers=h).json()
        check(f"process document {d}", out.get("outcome") in ("processed", "unchanged") and out["run"]["events_total"] > 0, out.get("outcome"))
    agent = client.post(f"{base}/agent/messages", headers=h, json={"message": "PT-1102 impulse tubing started today",
                        "discipline": "instrumentation", "reference_datetime": f"{as_of}T18:00:00"}).json()
    check("time agent message recorded", agent.get("status") in ("recorded", "duplicate"), agent.get("reply"))
    run_out = client.post(f"{base}/links/run", headers=h).json()
    check("linking ran", "counts" in run_out, run_out.get("counts"))
    for d in docs:
        events = client.get(f"{base}/events", params={"document_id": d, "limit": 1000}, headers=h).json()
        links = client.get(f"{base}/links", params={"document_id": d, "limit": 1000}, headers=h).json()
        valid = sum(e["validation_status"] == "valid" for e in events["items"])
        check(f"document {d}: every valid event has exactly one decision", links["total"] == valid, f"{links['total']} links / {valid} valid events")
    applied = client.post(f"{base}/apply", headers=h, json={"as_of": as_of}).json()
    check("apply ran", "applied" in applied, f"{len(applied.get('applied', []))} applied, {len(applied.get('blocked', []))} blocked")
    audit = client.get(f"{base}/audit", params={"limit": 1000}, headers=h).json()
    check("every apply entry cites source reports", all(e["evidence_event_ids"] for e in audit["items"] if e["action"] == "apply"))
    chain = client.get(f"{base}/audit/verify", headers=h).json()
    check("audit hash chain intact", chain.get("ok"), chain)
    xml = client.get(f"{base}/export/schedule.xml", params={"status_date": as_of}, headers=h)
    try:
        root = SafeET.fromstring(xml.content)
        tasks = root.findall("{http://schemas.microsoft.com/project}Tasks/{http://schemas.microsoft.com/project}Task")
        check("MSPDI export is valid XML with tasks", xml.status_code == 200 and tasks, f"{len(tasks)} tasks")
    except Exception as e:                             # noqa: BLE001 - report any parse failure as a failed check
        check("MSPDI export is valid XML with tasks", False, e)
    csv_text = client.get(f"{base}/export/schedule.csv", headers=h).text
    check("CSV export has the schedule columns", csv_text.splitlines()[0].startswith("node_id,node_type"))
    return checks


def in_process() -> list[tuple[str, bool, str]]:
    from fastapi.testclient import TestClient

    from p2e.db.session import init_db, make_engine, make_sessionmaker
    from p2e.main import create_app
    from p2e.plan.importers import import_schedule, read_schedule

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        url = f"sqlite:///{(tmp / 'smoke.db').as_posix()}"
        eng = make_engine(url)
        init_db(eng)
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        with make_sessionmaker(eng).begin() as s:
            import_schedule(s, read_schedule(DATA / "schedule" / "schedule.csv"), date.fromisoformat(manifest["data_date"]))
        eng.dispose()
        app = create_app(url, api_keys={KEY: "planner"}, upload_dir=tmp / "uploads", web_dist=tmp / "no-web")
        with TestClient(app) as c:
            out = run(c, KEY)
        app.state.engine.dispose()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="End-to-end smoke test over the HTTP API.")
    ap.add_argument("--base-url", help="running server (default: in-process app on a temporary database)")
    ap.add_argument("--api-key", help="planner/admin key for --base-url")
    args = ap.parse_args(argv)
    if args.base_url:
        import httpx
        if not args.api_key:
            print("--api-key is required with --base-url", file=sys.stderr)
            return 2
        with httpx.Client(base_url=args.base_url, timeout=60) as c:
            checks = run(c, args.api_key)
    else:
        checks = in_process()
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} smoke checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
