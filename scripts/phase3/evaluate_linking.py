r"""Phase 3 linking evaluation against data/synthetic/ground_truth/labels.csv.

    .venv\Scripts\python scripts\phase3\evaluate_linking.py            # prints tables, writes eval/phase3_linking.json
    .venv\Scripts\python scripts\phase3\evaluate_linking.py --show 20  # also list up to 20 disagreements

Builds a fresh temporary database (Phase 1 import -> Phase 2 ingest/extract -> Phase 3 link through the real service), so
the numbers are reproducible and data/p2e.db is not touched. Gold outcome: labels `expected_outcome` (auto_apply ->
matched, review -> review, unmatched -> unmatched); gold activity: `true_activity_id`; ambiguous items: `candidate_activity_ids`.
The decision rules were tuned on dev only; test is reported as held-out. Safety metric: auto-matches to a WRONG activity.
Cross-source conflicts (Phase 3.1): gold = labels with hard case `conflicting_date`; "same-fact counterpart" = another
source's report of the same truth event (`event_key`); anything else flagged is counted as a false conflict.
Layer contributions: without the conflict layer, without stage-2 retrieval (RAG), without glossary/synonym expansion (CAG), and the alias-memory
learning curve (MAG: replay planner confirmations of dev items, then re-link test). The LLM tie-breaker is not evaluated
(no on-premise model is configured; it is advisory only).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from p2e.db.models import EventLink, Project, ProgressEvent  # noqa: E402
from p2e.db.session import init_db, make_engine, make_sessionmaker  # noqa: E402
from p2e.extract.pipeline import load_project_vocab  # noqa: E402
from p2e.ingest.service import ingest_upload, process_batch  # noqa: E402
from p2e.link import service  # noqa: E402
from p2e.link.context import get_context, refresh_context  # noqa: E402
from p2e.link.decide import decide  # noqa: E402
from p2e.link.retrieve import ScheduleIndex, make_query  # noqa: E402
from p2e.memory import aliases as mag  # noqa: E402
from p2e.plan.importers import import_schedule, read_schedule  # noqa: E402

GOLD = {"auto_apply": "matched", "review": "review", "unmatched": "unmatched"}
REPLAY_ACTOR = "process:ground-truth-replay"


def build_db(data_dir: Path, tmp: Path):
    engine = make_engine(f"sqlite:///{(tmp / 'eval.db').as_posix()}")
    init_db(engine)
    sm = make_sessionmaker(engine)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    with sm.begin() as session:
        import_schedule(session, read_schedule(data_dir / "schedule" / "schedule.csv"), date.fromisoformat(manifest["data_date"]))
    with sm() as session:
        project = session.scalar(select(Project))
        ids = []
        for f in sorted((data_dir / "reports").glob("*.txt")) + sorted((data_dir / "spreadsheets").glob("*.xlsx")):
            ids.append(ingest_upload(session, project, f.name, f.read_bytes(), "eval", tmp / "uploads").id)
        session.commit()
        process_batch(session, project, tmp / "uploads", load_project_vocab(data_dir / "glossary.json"), ids)
    return engine, sm


def score_split(rows: list[dict]) -> dict:
    """rows: {gold, decision, node, true, cands, gold_cands}"""
    n = len(rows)
    conf = Counter((r["gold"], r["decision"]) for r in rows)
    auto = [r for r in rows if r["decision"] == "matched"]
    wrong = [r for r in auto if r["node"] != r["true"]]
    with_true = [r for r in rows if r["true"]]
    amb = [r for r in rows if r["gold_cands"] and not r["true"]]
    gold_auto = [r for r in rows if r["gold"] == "matched"]
    gold_un = [r for r in rows if r["gold"] == "unmatched"]
    pred_un = [r for r in rows if r["decision"] == "unmatched"]
    rate = lambda a, b: round(a / b, 4) if b else None
    return {
        "items": n,
        "matched": sum(r["decision"] == "matched" for r in rows),
        "review": sum(r["decision"] == "review" for r in rows),
        "unmatched": sum(r["decision"] == "unmatched" for r in rows),
        "outcome_accuracy": rate(sum(v for (g, d), v in conf.items() if g == d), n),
        "confusion_gold_to_predicted": {f"{g}->{d}": v for (g, d), v in sorted(conf.items())},
        "auto_matched": len(auto),
        "auto_precision_correct_activity": rate(len(auto) - len(wrong), len(auto)),
        "auto_matched_wrong_activity": len(wrong),
        "auto_coverage_of_gold_auto": rate(sum(r["decision"] == "matched" and r["node"] == r["true"] for r in gold_auto), len(gold_auto)),
        "gold_auto_sent_to_review": sum(r["decision"] == "review" for r in gold_auto),
        "gold_review_auto_matched_correct_activity": sum(r["gold"] == "review" and r["decision"] == "matched" and r["node"] == r["true"] for r in rows),
        "top1_activity": rate(sum(r["cands"][:1] == [r["true"]] for r in with_true), len(with_true)),
        "top3_activity": rate(sum(r["true"] in r["cands"][:3] for r in with_true), len(with_true)),
        "topk_activity_recall": rate(sum(r["true"] in r["cands"] for r in with_true), len(with_true)),
        "ambiguous_candidate_recall": rate(sum(len(set(r["gold_cands"]) & set(r["cands"])) for r in amb), sum(len(r["gold_cands"]) for r in amb)),
        "unmatched_recall": rate(sum(r["decision"] == "unmatched" for r in gold_un), len(gold_un)),
        "unmatched_precision": rate(sum(r["gold"] == "unmatched" for r in pred_un), len(pred_un)),
    }


def split_report(rows: list[dict]) -> dict:
    return {s: score_split([r for r in rows if s == "all" or r["split"] == s]) for s in ("dev", "test", "all")}


def evaluate(data_dir: Path) -> dict:
    with open(data_dir / "ground_truth" / "labels.csv", newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    refresh_context()
    with tempfile.TemporaryDirectory() as tmp:
        engine, sm = build_db(data_dir, Path(tmp))
        glossary = data_dir / "glossary.json"
        with sm() as session:
            project = session.scalar(select(Project))
            run1 = service.link_events(session, project, glossary)
            session.commit()
            events = {(e.document.filename, e.locator_key): e
                      for e in session.scalars(select(ProgressEvent).options(selectinload(ProgressEvent.document)))}
            ctx = get_context(session, project, glossary)
            index = ScheduleIndex.build(session, project, ctx)

            def stored_rows() -> list[dict]:
                links = {l.progress_event_id: l for l in session.scalars(
                    select(EventLink).options(selectinload(EventLink.candidates)).execution_options(populate_existing=True))}
                code = {n.id: n.code for n in index.nodes}
                out = []
                for lab in labels:
                    ev = events[(lab["source_path"].split("/")[-1], lab["locator"])]
                    l = links[ev.id]
                    out.append(row(lab, ev, l.decision, code.get(l.plan_node_id), [code[c.plan_node_id] for c in l.candidates],
                                   l.method, l.retrieval_used, l.confidence, l.unmatched_type, l.conflict))
                return out

            def memory_rows(c, idx, retrieval=True) -> list[dict]:
                out = []
                for lab in labels:
                    ev = events[(lab["source_path"].split("/")[-1], lab["locator"])]
                    q = make_query(c, ev.activity_text, ev.tags or [], ev.area, ev.discipline, ev.source_ref, ev.unit, {})
                    d = decide(q, idx, c, [], retrieval=retrieval)
                    out.append(row(lab, ev, d.decision, idx.nodes_by_id[d.node_id].code if d.node_id else None,
                                   [s.cand.node.code for s in d.ranked], d.method, d.used_retrieval, d.confidence, d.unmatched_type))
                return out

            full = stored_rows()
            report = {"method": "deterministic evidence + stage-2 lexical/attribute retrieval + gated decision; no LLM",
                      "linker_run": run1, "splits": split_report(full)}
            report["conflicts"] = conflict_report(full, run1["conflicts"])
            report["by_hard_case"] = by_hard_case(full)
            report["by_method"] = {m: dict(Counter(r["decision"] for r in full if r["method"] == m))
                                   for m in sorted({r["method"] for r in full})}
            report["retrieval_used"] = dict(Counter(f"{'stage2' if r['retrieval'] else 'deterministic_only'}->{r['decision']}" for r in full))
            report["auto_precision_by_confidence"] = confidence_bands(full)
            report["unmatched_type_vs_gold"] = dict(Counter(f"{r['gold_unmatched_type'] or '-'}->{r['unmatched_type'] or '-'}"
                                                            for r in full if r["gold"] == "unmatched" or r["decision"] == "unmatched"))

            index.nodes_by_id = {n.id: n for n in index.nodes}
            no_rag = memory_rows(ctx, index, retrieval=False)
            bare = dataclasses.replace(ctx, expansions={}, synonyms={}, _typo={})
            bare_index = ScheduleIndex.build(session, project, bare)
            bare_index.nodes_by_id = {n.id: n for n in bare_index.nodes}
            no_cag = memory_rows(bare, bare_index)
            no_conflict_layer = memory_rows(ctx, index)        # same decisions, conflict layer not applied
            report["ablations_test_split"] = {
                "full": pick(report["splits"]["test"]),
                "without_conflict_layer": pick(score_split([r for r in no_conflict_layer if r["split"] == "test"])),
                "without_stage2_retrieval_RAG": pick(score_split([r for r in no_rag if r["split"] == "test"])),
                "without_glossary_and_synonyms_CAG": pick(score_split([r for r in no_cag if r["split"] == "test"])),
            }

            # MAG learning curve: a planner confirms the gold activity for every dev item the linker did not auto-match
            # correctly; alias memory learns from those confirmations only; then everything not confirmed is re-linked.
            learned, skipped = [], []
            for r in full:
                if r["split"] == "dev" and r["true"] and not (r["decision"] == "matched" and r["node"] == r["true"]):
                    link = service.get_link(session, project, r["event_id"])
                    res = service.confirm(session, project, link, r["true"], REPLAY_ACTOR, glossary)
                    learned += res["learned"]
                    skipped += res["skipped"]
            session.commit()
            run2 = service.link_events(session, project, glossary)
            session.commit()
            after = stored_rows()
            aliases = mag.active(session, project.id)
            report["mag_learning_curve"] = {
                "replayed_dev_confirmations": sum(1 for r in full if r["split"] == "dev" and r["true"]
                                                  and not (r["decision"] == "matched" and r["node"] == r["true"])),
                "aliases_learned": len(aliases), "alias_learning_skipped": dict(Counter(s["reason"].split(":")[0] for s in skipped)),
                "aliases": [{"kind": a.kind, "phrase": a.phrase, "target": a.target, "use_count": a.use_count} for a in aliases],
                "relink_run": run2,
                "test_before": pick(report["splits"]["test"]),
                "test_after": pick(score_split([r for r in after if r["split"] == "test"])),
            }
        engine.dispose()
    return report


def row(lab, ev, decision, node, cands, method, retrieval, confidence, unmatched_type, conflict=None) -> dict:
    return {"split": lab["split"], "gold": GOLD[lab["expected_outcome"]], "true": lab["true_activity_id"] or None,
            "gold_cands": [c for c in lab["candidate_activity_ids"].split(";") if c], "hard": [h for h in lab["hard_cases"].split(";") if h],
            "gold_unmatched_type": lab["unmatched_type"], "event_id": ev.id, "text": ev.activity_text, "decision": decision,
            "node": node, "cands": cands, "method": method, "retrieval": retrieval, "confidence": confidence,
            "unmatched_type": unmatched_type, "item_id": lab["item_id"], "event_key": lab["event_key"],
            "conflict_rules": sorted({f["rule"] for f in conflict["findings"]}) if conflict else []}


def conflict_report(rows: list[dict], layer_counts: dict) -> dict:
    gold = [r for r in rows if "conflicting_date" in r["hard"]]
    gold_keys = {r["event_key"] for r in gold if r["event_key"]}
    flagged = [r for r in rows if r["conflict_rules"]]
    counterparts = [r for r in flagged if "conflicting_date" not in r["hard"] and r["event_key"] in gold_keys]
    false = [r for r in flagged if "conflicting_date" not in r["hard"] and r["event_key"] not in gold_keys]
    detected = [r for r in gold if r["conflict_rules"]]
    return {
        "layer": layer_counts,
        "gold_conflict_items": len(gold),
        "detected": len(detected),
        "detected_routed_to_review": sum(r["decision"] == "review" for r in detected),
        "missed": [{"item_id": r["item_id"], "text": r["text"], "decision": r["decision"]} for r in gold if not r["conflict_rules"]],
        "flagged_events": len(flagged),
        "same_fact_counterparts": len(counterparts),
        "false_conflicts": [{"item_id": r["item_id"], "text": r["text"], "rules": r["conflict_rules"]} for r in false],
        "flagged_auto_matched": sum(r["decision"] == "matched" for r in flagged),
        "by_rule": dict(Counter(rule for r in flagged for rule in r["conflict_rules"])),
    }


def pick(r: dict) -> dict:
    keys = ("outcome_accuracy", "matched", "review", "unmatched", "auto_matched", "auto_precision_correct_activity", "auto_matched_wrong_activity",
            "auto_coverage_of_gold_auto", "top1_activity", "top3_activity", "unmatched_recall")
    return {k: r[k] for k in keys}


def by_hard_case(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for r in rows:
        for h in r["hard"] or ["(none)"]:
            groups[h].append(r)
    return {h: {"items": len(rs), "outcome_accuracy": round(sum(r["gold"] == r["decision"] for r in rs) / len(rs), 4),
                "auto_matched_wrong_activity": sum(r["decision"] == "matched" and r["node"] != r["true"] for r in rs),
                "predicted": dict(Counter(r["decision"] for r in rs))} for h, rs in sorted(groups.items())}


def confidence_bands(rows: list[dict]) -> dict:
    out = {}
    for lo, hi in ((0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        rs = [r for r in rows if r["decision"] == "matched" and lo <= r["confidence"] < hi]
        out[f"[{lo}, {min(hi, 1.0)}]"] = {"auto_matched": len(rs), "correct_activity": sum(r["node"] == r["true"] for r in rs)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate Phase 3 schedule linking against the Phase 0 ground truth.")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "phase3_linking.json")
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args(argv)
    rep = evaluate(args.data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    cols = ("items", "matched", "review", "unmatched", "outcome_accuracy", "auto_matched", "auto_precision_correct_activity", "auto_matched_wrong_activity",
            "auto_coverage_of_gold_auto", "top1_activity", "top3_activity", "ambiguous_candidate_recall", "unmatched_recall",
            "unmatched_precision")
    print(f"{'metric':<40} {'dev':>8} {'test':>8} {'all':>8}")
    for c in cols:
        print(f"{c:<40} " + " ".join(f"{str(rep['splits'][s][c]):>8}" for s in ("dev", "test", "all")))
    print("\nconfusion (all, gold->predicted):", rep["splits"]["all"]["confusion_gold_to_predicted"])
    print("\nlayer contributions on test:")
    for k, v in rep["ablations_test_split"].items():
        print(f"  {k:<36} outcome {v['outcome_accuracy']}  auto {v['auto_matched']}  wrong {v['auto_matched_wrong_activity']}  "
              f"top3 {v['top3_activity']}  unmatched recall {v['unmatched_recall']}")
    m = rep["mag_learning_curve"]
    print(f"\nMAG: {m['replayed_dev_confirmations']} dev confirmations replayed -> {m['aliases_learned']} aliases learned "
          f"(skipped: {m['alias_learning_skipped']})")
    for k in ("test_before", "test_after"):
        v = m[k]
        print(f"  {k:<12} outcome {v['outcome_accuracy']}  auto {v['auto_matched']}  wrong {v['auto_matched_wrong_activity']}  "
              f"coverage {v['auto_coverage_of_gold_auto']}  top1 {v['top1_activity']}")
    c = rep["conflicts"]
    print(f"\ncross-source date conflicts: gold {c['gold_conflict_items']}, detected {c['detected']} "
          f"(routed to review {c['detected_routed_to_review']}), missed {len(c['missed'])} {[m['item_id'] for m in c['missed']]}")
    print(f"  flagged events {c['flagged_events']}: same-fact counterparts {c['same_fact_counterparts']}, "
          f"false conflicts {len(c['false_conflicts'])} {[f['item_id'] for f in c['false_conflicts']]}, "
          f"still auto-matched {c['flagged_auto_matched']}  rules {c['by_rule']}")
    print("\nauto precision by confidence:", rep["auto_precision_by_confidence"])
    if args.show:
        print("\nhard cases:")
        for h, v in rep["by_hard_case"].items():
            print(f"  {h:<26} n={v['items']:<4} acc={v['outcome_accuracy']:<6} wrong={v['auto_matched_wrong_activity']}  {v['predicted']}")
    print(f"\nwritten: {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
