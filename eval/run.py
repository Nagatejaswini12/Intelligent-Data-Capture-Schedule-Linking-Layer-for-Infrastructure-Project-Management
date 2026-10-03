r"""Phase 7 evaluation harness: one command -> eval/report.md (+ eval/phase7_report.json).

    .venv\Scripts\python -m eval.run                 # headline split: test (rules were tuned on dev only)
    .venv\Scripts\python -m eval.run --split all

Reuses the existing evaluations (Phase 0 dataset checks, Phase 2 extraction, Phase 3 linking incl. ablations, threshold
calibration and reliability, Phase 5 apply + exit gate, Phase 6 Q&A benchmark) and adds the Time Agent dialogue
scenarios, the silent-activity watch, latency and the LLM call ratio, then checks every target from the master plan (§9)
and the testing plan (§3). Each section builds its own fresh temporary database; data/p2e.db is never touched.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "phase0"))   # the dataset validator imports its siblings by name

from sqlalchemy import func, select  # noqa: E402

from p2e.agent import time_agent  # noqa: E402
from p2e.db.models import EventLink, PlanNode, Project  # noqa: E402
from p2e.decide import apply as engine  # noqa: E402
from p2e.decide import watch  # noqa: E402
from p2e.extract.pipeline import extract_bytes, load_project_vocab  # noqa: E402
from p2e.ingest import service as ingest  # noqa: E402
from p2e.link import service as linking  # noqa: E402
from p2e.link.context import refresh_context  # noqa: E402
import validate_dataset  # noqa: E402
from scripts.phase2 import evaluate_extraction  # noqa: E402
from scripts.phase3 import evaluate_linking  # noqa: E402
from scripts.phase5 import evaluate_apply  # noqa: E402
from scripts.phase6 import evaluate_qa  # noqa: E402

DATA = ROOT / "data" / "synthetic"
AS_OF = date(2026, 9, 16)


def fresh_linked_db(tmp: Path):
    refresh_context()
    eng, sm = evaluate_linking.build_db(DATA, tmp)
    session = sm()
    project = session.scalar(select(Project))
    t = time.perf_counter()
    linking.link_events(session, project, DATA / "glossary.json")
    session.commit()
    return eng, session, project, time.perf_counter() - t


def dialogues(session, project, uploads: Path) -> dict:
    spec = json.loads((ROOT / "eval" / "time_agent_dialogues.json").read_text(encoding="utf-8"))
    ref = datetime.fromisoformat(spec["reference_datetime"]).replace(tzinfo=ZoneInfo(project.timezone))
    results = []
    for d in spec["dialogues"]:
        out = None
        for turn in d["turns"]:
            out = time_agent.handle(session, project, turn["message"], ref, "supervisor", uploads, DATA / "glossary.json",
                                    discipline=turn.get("discipline"), answers=turn.get("answers"))
            session.commit()
            if out["status"] in ("recorded", "rejected", "checklist", "duplicate"):
                break
        link = linking.get_link(session, project, out["event_id"]) if out.get("event_id") else None
        got = {"status": out["status"], "decision": link.decision if link else None, "plan_node_code": link.node.code if link and link.node else None}
        exp = d["expect"]
        ok = all(got.get(k) == v for k, v in exp.items())
        wrong = got["decision"] == "matched" and got["plan_node_code"] != exp.get("plan_node_code")
        results.append({"id": d["id"], "turns": len(d["turns"]), "passed": ok, "wrong_activity": wrong, "got": got, "expected": exp,
                        "reply": out["reply"]})
    recorded = [r for r in results if r["got"]["status"] == "recorded"]
    return {"dialogues": len(results), "passed": sum(r["passed"] for r in results),
            "task_success": round(sum(r["passed"] for r in results) / len(results), 4),
            "mean_turns_to_log": round(sum(r["turns"] for r in recorded) / len(recorded), 2) if recorded else None,
            "wrong_activity_logs": sum(r["wrong_activity"] for r in results), "results": results}


def watch_stats(session, project) -> dict:
    truth = defaultdict(set)
    with open(DATA / "ground_truth" / "truth_events.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            truth[r["activity_id"]].add(date.fromisoformat(r["event_date"]))
    items = watch.silent_activities(session, project, AS_OF, 3)
    window = {AS_OF - timedelta(days=k) for k in range(3)}
    missed = [i for i in items if truth[i["plan_node_code"]] & window]
    again = watch.silent_activities(session, project, AS_OF, 3)
    return {"as_of": str(AS_OF), "window_days": 3, "silent": len(items), "truly_worked_but_unreported": len(missed),
            "no_truth_work_in_window": len(items) - len(missed), "deterministic": again == items,
            "note": "silent = expected active without a linked report; 'no truth work' items are idle / slipping, not errors"}


def latency(session, project, uploads: Path) -> dict:
    pv = load_project_vocab(DATA / "glossary.json")
    docs = sorted((DATA / "reports").glob("*.txt")) + sorted((DATA / "spreadsheets").glob("*.xlsx"))
    t = time.perf_counter()
    for p in docs:
        extract_bytes(p.read_bytes(), p.suffix.lower(), pv)
    extraction = time.perf_counter() - t
    dpr = ("CGS EXPANSION PROJECT - DAILY PROGRESS REPORT\nDiscipline: Instrumentation\nDate: 2026-09-16    Report No: LAT\n\n"
           "Work Done Today:\n1. LT-1103 loop check started today\n2. PT-1102 impulse tubing started today\n")
    t = time.perf_counter()
    doc = ingest.ingest_upload(session, project, "latency.txt", dpr.encode(), "supervisor", uploads)
    ingest.process_document(session, doc, uploads, pv)
    linking.link_events(session, project, DATA / "glossary.json")
    nodes = [l.plan_node_id for l in session.scalars(select(EventLink).where(EventLink.plan_node_id.is_not(None)))]
    engine.apply(session, project, AS_OF, node_ids=nodes)
    session.commit()
    single = time.perf_counter() - t
    return {"extraction_ms_per_document": round(1000 * extraction / len(docs), 1),
            "single_dpr_upload_to_actual_s": round(single, 2)}


def evaluate(split: str) -> dict:
    rep: dict = {"generated": datetime.now().isoformat(timespec="seconds"), "headline_split": split}
    ds = validate_dataset.validate(DATA, regen=True)
    rep["dataset"] = {"checks": len(ds.results), "passed": len(ds.results) - len(ds.failed()), "failed": [r[0] for r in ds.failed()]}
    rep["extraction"] = evaluate_extraction.evaluate(DATA)
    rep["linking"] = evaluate_linking.evaluate(DATA)
    rep["apply"] = evaluate_apply.evaluate(DATA)
    rep["qa"] = evaluate_qa.evaluate(DATA)
    from eval import calibration
    rep["confidence_calibration"] = calibration.evaluate(DATA)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        eng, session, project, link_s = fresh_linked_db(tmp)
        events = session.scalar(select(func.count()).select_from(EventLink))
        llm_calls = session.scalar(select(func.count()).select_from(EventLink).where(EventLink.llm_suggestion.is_not(None)))
        rep["linking_runtime"] = {"events": events, "link_ms_per_event": round(1000 * link_s / events, 2), "llm_calls": llm_calls,
                                  "llm_call_ratio": round(llm_calls / events, 4), "llm": "disabled (no on-premise model configured)"}
        rep["watch"] = watch_stats(session, project)
        rep["time_agent"] = dialogues(session, project, tmp / "uploads")
        rep["latency"] = latency(session, project, tmp / "uploads") | {"link_ms_per_event": rep["linking_runtime"]["link_ms_per_event"]}
        session.close()
        eng.dispose()
    rep["targets"] = targets(rep, split)
    return rep


def targets(rep: dict, split: str) -> list[dict]:
    ex = rep["extraction"]["splits"][split]
    ln = rep["linking"]["splits"][split]
    gold_new = {k: v for k, v in rep["linking"]["unmatched_type_vs_gold"].items() if k.startswith("new_activity->")}
    new_recall = sum(v for k, v in gold_new.items() if not k.endswith("->-")) / max(1, sum(gold_new.values()))
    field = min(ex["field_exact_excluding_gt_gaps"][f] for f in ("event_type", "date", "quantity"))
    mag = rep["linking"]["mag_learning_curve"]
    rows = [
        ("Dataset checks", "all pass", f"{rep['dataset']['passed']}/{rep['dataset']['checks']}", rep["dataset"]["passed"] == rep["dataset"]["checks"]),
        ("Extraction item recall", ">= 0.92", ex["recall"], ex["recall"] >= 0.92),
        ("Extraction item precision", ">= 0.90", ex["precision"], ex["precision"] >= 0.90),
        ("Extraction field accuracy (type, date, qty; excl. ground-truth gaps)", ">= 0.90 each", field, field >= 0.90),
        ("Linking top-1 (items with a true activity)", ">= 0.85", ln["top1_activity"], ln["top1_activity"] >= 0.85),
        ("Linking top-3 recall", ">= 0.95", ln["top3_activity"], ln["top3_activity"] >= 0.95),
        ("Auto-apply precision", ">= 0.95", ln["auto_precision_correct_activity"], (ln["auto_precision_correct_activity"] or 0) >= 0.95),
        ("Auto-apply coverage (all events)", "report (aim >= 0.60)", round(ln["auto_matched"] / ln["items"], 4), None),
        ("NEW detection recall (all splits)", ">= 0.90", round(new_recall, 4), new_recall >= 0.90),
        ("Unmatched never auto-applied to a wrong node", "100%", ln["auto_matched_wrong_activity"] == 0, ln["auto_matched_wrong_activity"] == 0),
        ("Calibration ECE (top-candidate score)", "<= 0.05", rep["linking"]["reliability_test"]["ece"], rep["linking"]["reliability_test"]["ece"] <= 0.05),
        ("Calibrated confidence ECE (isotonic fitted on dev, evaluated on test)", "<= 0.05",
         f"{rep['confidence_calibration']['test']['raw']['ece']} -> {rep['confidence_calibration']['test']['calibrated']['ece']}",
         rep["confidence_calibration"]["test"]["calibrated"]["ece"] <= 0.05),
        ("LLM call ratio", "<= 0.30", rep["linking_runtime"]["llm_call_ratio"], rep["linking_runtime"]["llm_call_ratio"] <= 0.30),
        ("Alias learning curve (test top-1)", "uplift", f"{mag['test_before']['top1_activity']} -> {mag['test_after']['top1_activity']}",
         mag["test_after"]["top1_activity"] > mag["test_before"]["top1_activity"]),
        ("Time Agent task success (20 dialogues)", ">= 0.90", rep["time_agent"]["task_success"], rep["time_agent"]["task_success"] >= 0.90),
        ("Time Agent mean turns to log", "<= 3", rep["time_agent"]["mean_turns_to_log"], (rep["time_agent"]["mean_turns_to_log"] or 99) <= 3),
        ("Time Agent wrong-activity logs", "0", rep["time_agent"]["wrong_activity_logs"], rep["time_agent"]["wrong_activity_logs"] == 0),
        ("Memory Q&A benchmark (correct + cited)", ">= 8/10", f"{rep['qa']['passed']}/{rep['qa']['total']}", rep["qa"]["passed"] >= 8),
        ("Applied actuals with audit + source evidence", "100%", rep["apply"]["exit_gate"]["audit_complete"], rep["apply"]["exit_gate"]["audit_complete"]),
        ("Applied dates equal ground truth", "report", f"{len(rep['apply']['applied_not_matching_truth'])} mismatches", None),
        ("Report -> schedule actual (single DPR)", "<= 10 s", rep["latency"]["single_dpr_upload_to_actual_s"], rep["latency"]["single_dpr_upload_to_actual_s"] <= 10),
    ]
    return [{"metric": m, "target": t, "value": v, "met": ok} for m, t, v, ok in rows]


def markdown(rep: dict) -> str:
    s = rep["headline_split"]
    L = [f"# P2E Bridge — evaluation report", "",
         f"Generated {rep['generated']} by `python -m eval.run --split {s}` on the synthetic project (rules tuned on **dev**; headline numbers on **{s}**). "
         "Deterministic parser/linker metrics on synthetic data, not field accuracy.", "", "## Targets", "",
         "| Metric | Target | Value | Met |", "|---|---|---|---|"]
    for t in rep["targets"]:
        L.append(f"| {t['metric']} | {t['target']} | {t['value']} | {'—' if t['met'] is None else ('yes' if t['met'] else '**no**')} |")
    ex = rep["extraction"]["splits"]
    L += ["", "## Extraction (Phase 2)", "", "| Split | Expected | Predicted | P | R | F1 |", "|---|---|---|---|---|---|"]
    L += [f"| {k} | {v['expected_items']} | {v['predicted_items']} | {v['precision']} | {v['recall']} | {v['f1']} |" for k, v in ex.items()]
    L += [f"", f"Ground-truth gaps (independently confirmed, not extractor errors): {rep['extraction']['ground_truth_gaps']['count']}."]
    ln = rep["linking"]
    L += ["", "## Linking (Phase 3 / 3.1)", "", "| Split | Matched | Review | Unmatched | Outcome agreement | Wrong auto | Top-1 | Top-3 | Unmatched recall |",
          "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {k} | {v['matched']} | {v['review']} | {v['unmatched']} | {v['outcome_accuracy']} | {v['auto_matched_wrong_activity']} | {v['top1_activity']} | {v['top3_activity']} | {v['unmatched_recall']} |"
          for k, v in ln["splits"].items()]
    L += ["", "### Ablations (test)", "", "| Variant | Outcome agreement | Auto | Wrong auto | Top-3 |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v['outcome_accuracy']} | {v['auto_matched']} | {v['auto_matched_wrong_activity']} | {v['top3_activity']} |" for k, v in ln["ablations_test_split"].items()]
    m = ln["mag_learning_curve"]
    L += [f"", f"Without aliases (MAG) = the full system before any confirmation; alias learning curve after replaying {m['replayed_dev_confirmations']} dev confirmations: "
          f"{m['aliases_learned']} aliases, test top-1 {m['test_before']['top1_activity']} → {m['test_after']['top1_activity']}, wrong auto {m['test_after']['auto_matched_wrong_activity']}. "
          "Without embeddings / LLM adjudication: not applicable (no embeddings; LLM disabled)."]
    c = ln["calibration"]
    L += ["", "### Threshold calibration", "", f"{c['rule']}. Calibrated T_auto = {c['calibrated_T_auto']}; configured = {c['configured_auto_min_score']}. "
          f"Thresholds giving identical dev decisions to the configured one: {c['thresholds_with_identical_dev_decisions_to_configured']} "
          f"(the other gates bind, not the score). Test at calibrated: {c['test_at_calibrated']}; at configured: {c['test_at_configured']}.", "",
          "| Threshold | Dev auto | Dev coverage | Dev precision | Test auto | Test coverage | Test precision |", "|---|---|---|---|---|---|---|"]
    L += [f"| {p['threshold']} | {p['dev']['auto']} | {p['dev']['coverage']} | {p['dev']['precision']} | {p['test']['auto']} | {p['test']['coverage']} | {p['test']['precision']} |"
          for p in c["precision_coverage_curve"]]
    r = ln["reliability_test"]
    L += ["", f"### Reliability (test) — ECE {r['ece']}", "", "| Bucket | Items | Mean confidence | Top-1 accuracy |", "|---|---|---|---|"]
    L += [f"| {b['bucket']} | {b['items']} | {b.get('mean_confidence', '—')} | {b.get('top1_accuracy', '—')} |" for b in r["buckets"]]
    L += ["", f"{r['note']}. Calibrated (isotonic map fitted on dev, 10 bins, items with a candidate): test ECE {rep['confidence_calibration']['test']['raw']['ece']} -> "
          f"{rep['confidence_calibration']['test']['calibrated']['ece']}, Brier {rep['confidence_calibration']['test']['raw']['brier']} -> "
          f"{rep['confidence_calibration']['test']['calibrated']['brier']}; details in eval/calibration_report.md (evaluation only; API returns the raw score).",
          "", "### Cross-source conflicts", ""]
    cf = ln["conflicts"]
    L += [f"Gold {cf['gold_conflict_items']}, detected {cf['detected']} (all routed to review), missed {[x['item_id'] for x in cf['missed']]}, "
          f"same-fact counterparts {cf['same_fact_counterparts']}, false conflicts {[x['item_id'] for x in cf['false_conflicts']]}."]
    L += ["", "### Per hard case (all items)", "", "| Hard case | Items | Outcome agreement | Wrong auto |", "|---|---|---|---|"]
    L += [f"| {k} | {v['items']} | {v['outcome_accuracy']} | {v['auto_matched_wrong_activity']} |" for k, v in ln["by_hard_case"].items()]
    ap = rep["apply"]
    L += ["", "## Schedule application (Phase 5)", "", f"Applied activities {ap['applied_activities']}, fields {ap['applied_fields']}, blocked {ap['blocked_activities']} {ap['blocked_by_rule']}. "
          f"Applied vs truth {ap['applied_vs_truth']}. Exit gate {ap['exit_gate']}. Export round trip {ap['export_round_trip']}."]
    ta = rep["time_agent"]
    L += ["", "## Time Agent (Phase 4)", "", f"{ta['passed']}/{ta['dialogues']} scripted dialogues as expected, mean turns to log {ta['mean_turns_to_log']}, wrong-activity logs {ta['wrong_activity_logs']}.", "",
          "| Dialogue | Turns | Expected | Got | Pass |", "|---|---|---|---|---|"]
    L += [f"| {d['id']} | {d['turns']} | {d['expected']} | {d['got']} | {'yes' if d['passed'] else '**no**'} |" for d in ta["results"]]
    w = rep["watch"]
    L += ["", "## Silent activity watch", "", f"As of {w['as_of']} ({w['window_days']}-day window): {w['silent']} silent; {w['truly_worked_but_unreported']} truly worked but unreported; "
          f"{w['no_truth_work_in_window']} idle/slipping; deterministic {w['deterministic']}."]
    q = rep["qa"]
    L += ["", "## Memory Q&A (Phase 6)", "", f"{q['passed']}/{q['total']} benchmark questions correct with citations.", "",
          "| Question | Intent | Citations | Pass |", "|---|---|---|---|"]
    L += [f"| {r['question']} | {r['intent']} | {r['citations']} | {'yes' if r['passed'] else '**no**'} |" for r in q["results"]]
    lt = rep["latency"]
    L += ["", "## Latency and LLM use", "", f"Extraction {lt['extraction_ms_per_document']} ms/document; linking {lt['link_ms_per_event']} ms/event; "
          f"single DPR upload → applied actual {lt['single_dpr_upload_to_actual_s']} s. LLM call ratio {rep['linking_runtime']['llm_call_ratio']} ({rep['linking_runtime']['llm']})."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7 evaluation harness -> eval/report.md")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="test")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "report.md")
    args = ap.parse_args(argv)
    rep = evaluate(args.split)
    args.out.write_text(markdown(rep), encoding="utf-8", newline="\n")
    (args.out.parent / "phase7_report.json").write_text(json.dumps(rep, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    met = [t for t in rep["targets"] if t["met"] is not None]
    print(f"targets met: {sum(t['met'] for t in met)}/{len(met)}")
    for t in rep["targets"]:
        print(f"  {'OK ' if t['met'] else ('-- ' if t['met'] is None else 'NO ')} {t['metric']}: {t['value']} (target {t['target']})")
    print(f"written: {args.out.relative_to(ROOT)} and eval/phase7_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
