r"""Phase 2 extraction evaluation against data/synthetic/ground_truth/expected_extraction.json.

    .venv\Scripts\python scripts\phase2\evaluate_extraction.py            # prints tables, writes eval/phase2_extraction.json
    .venv\Scripts\python scripts\phase2\evaluate_extraction.py --show 10  # also print up to 10 misses per category

Deterministic rule/template extraction, so these are parser-conformance metrics, not "AI accuracy".
Items are matched on (document, source locator): DPR line + position on the line, or sheet + row + field.
Dev/test come from labels.csv `split`; extra (unmatched predicted) items take the split of their report/event day.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from p2e.extract.pipeline import extract_bytes, load_project_vocab  # noqa: E402

FIELDS = ["event_type", "date", "time", "quantity", "unit", "discipline", "area", "tags", "delay_reason", "delay_category",
          "activity_text", "source_span"]


def key(locator: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in locator.items())


def predicted_fields(it) -> dict:
    return {"event_type": it.event_type, "date": it.event_date.isoformat() if it.event_date else None, "time": it.event_time,
            "quantity": it.quantity, "unit": it.unit, "discipline": it.discipline, "area": it.area, "tags": sorted(it.tags),
            "delay_reason": it.delay_reason, "delay_category": it.delay_category, "activity_text": it.activity_text,
            "source_span": it.source_text}


def evaluate(data_dir: Path) -> dict:
    gt = json.loads((data_dir / "ground_truth" / "expected_extraction.json").read_text(encoding="utf-8"))["documents"]
    with open(data_dir / "ground_truth" / "labels.csv", newline="", encoding="utf-8") as f:
        split_of = {r["item_id"]: r["split"] for r in csv.DictReader(f)}
    splits = json.loads((data_dir / "ground_truth" / "splits.json").read_text(encoding="utf-8"))
    day_split = {d: "dev" for d in splits["dev_days"]} | {d: "test" for d in splits["test_days"]}
    vocab = load_project_vocab(data_dir / "glossary.json")

    stats = {s: {"expected": 0, "predicted": 0, "matched": 0, "field_ok": defaultdict(int), "field_gap": defaultdict(int)} for s in ("dev", "test", "all")}
    misses: dict[str, list] = {"missing": [], "extra": [], "field": []}
    docs_out = {"report_date_ok": 0, "group_ok": 0, "dpr_docs": 0, "sheets": {}, "noise_line_extractions": 0, "issues": 0}
    for doc in gt:
        res = extract_bytes((data_dir / doc["path"]).read_bytes(), Path(doc["path"]).suffix.lower(), vocab)
        docs_out["issues"] += len(res.issues)
        pred = {i.locator_key: i for i in res.items}
        exp = {key(i["locator"]): i for i in doc["items"]}
        if doc["source_type"] == "dpr":
            docs_out["dpr_docs"] += 1
            docs_out["report_date_ok"] += res.report_date is not None and res.report_date.isoformat() == doc["report_date"]
            docs_out["group_ok"] += res.discipline_group == doc["discipline_group"]
            noise = {n["line"] for n in doc["non_event_lines"]}
            docs_out["noise_line_extractions"] += sum(i.source_ref["line"] in noise for i in res.items)
        else:
            got = res.meta["sheets"].get(doc["sheet"], {})
            docs_out["sheets"][doc["doc_id"]] = {"header_row_ok": got.get("header_row") == doc["header_row"],
                                                 "column_mapping_ok": got.get("column_mapping") == doc["column_mapping"]}
        for k, e in exp.items():
            for s in (split_of[e["item_id"]], "all"):
                stats[s]["expected"] += 1
            p = pred.get(k)
            if p is None:
                misses["missing"].append((doc["doc_id"], k, e["source_span"]))
                continue
            pf = predicted_fields(p)
            for s in (split_of[e["item_id"]], "all"):
                stats[s]["matched"] += 1
                stats[s]["predicted"] += 1
            for f in FIELDS:
                ev = sorted(e["tags"]) if f == "tags" else e[f]
                ok = pf[f] == ev
                gap = not ok and gt_gap(f, ev, pf[f], pf["source_span"], e["source_span"])
                for s in (split_of[e["item_id"]], "all"):
                    stats[s]["field_ok"][f] += ok
                    stats[s]["field_gap"][f] += gap
                if not ok:
                    misses["field"].append((doc["doc_id"], k, f, ev, pf[f], "gt_gap" if gap else "extractor"))
        for k, p in pred.items():
            if k not in exp:
                day = (res.report_date or p.event_date)
                s = day_split.get(day.isoformat() if day else "", "test")
                for s_ in (s, "all"):
                    stats[s_]["predicted"] += 1
                misses["extra"].append((doc["doc_id"], k, p.source_text))

    report = {"method": "deterministic rule/template extraction; items matched on (document, locator)", "splits": {}}
    for s, st in stats.items():
        tp, n_exp, n_pred = st["matched"], st["expected"], st["predicted"]
        prec = tp / n_pred if n_pred else 0.0
        rec = tp / n_exp if n_exp else 0.0
        report["splits"][s] = {
            "expected_items": n_exp, "predicted_items": n_pred, "matched": tp, "missing": n_exp - tp, "extra": n_pred - tp,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "field_exact": {f: round(st["field_ok"][f] / tp, 4) if tp else 0.0 for f in FIELDS},
            "field_exact_excluding_gt_gaps": {f: round((st["field_ok"][f] + st["field_gap"][f]) / tp, 4) if tp else 0.0 for f in FIELDS},
        }
    report["documents"] = docs_out
    report["field_mismatch_counts"] = dict(sorted(_count(m[2] for m in misses["field"]).items()))
    gaps = [m for m in misses["field"] if m[5] == "gt_gap"]
    report["ground_truth_gaps"] = {
        "note": "field mismatches caused by incomplete expected_extraction.json, not by the extractor (ground truth left "
                "unchanged): `time` is always null there (Phase 0 wrote it under another key; truth times are in "
                "truth_events.csv); `area` is omitted although stated in the text or the Loc column; two cable rows' "
                "expected cells omit the Pulled? cell",
        "count": len(gaps), "by_field": dict(sorted(_count(m[2] for m in gaps).items()))}
    report["misses"] = {k: [list(map(str, x)) for x in v] for k, v in misses.items()}
    return report


def gt_gap(field: str, expected, got, span: str, exp_span: str) -> bool:
    """Ground truth is null/narrower where the source clearly states the value."""
    if field == "time":
        return expected is None and got is not None and str(int(got[:2])) in span
    if field == "area":
        return expected is None and got is not None
    if field == "source_span":
        return set(exp_span.split(" | ")) < set(span.split(" | "))
    return False


def _count(xs) -> dict:
    out: dict = defaultdict(int)
    for x in xs:
        out[x] += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate Phase 2 extraction against the Phase 0 ground truth.")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "phase2_extraction.json")
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args(argv)
    rep = evaluate(args.data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'split':<6} {'expected':>8} {'predicted':>9} {'matched':>7} {'missing':>7} {'extra':>5} {'P':>7} {'R':>7} {'F1':>7}")
    for s, r in rep["splits"].items():
        print(f"{s:<6} {r['expected_items']:>8} {r['predicted_items']:>9} {r['matched']:>7} {r['missing']:>7} {r['extra']:>5} "
              f"{r['precision']:>7.4f} {r['recall']:>7.4f} {r['f1']:>7.4f}")
    print("\nfield exact-match on matched items      raw (dev  test  all)  |  excluding ground-truth gaps")
    for f in FIELDS:
        raw = "  ".join(f"{rep['splits'][s]['field_exact'][f]:.4f}" for s in ("dev", "test", "all"))
        adj = "  ".join(f"{rep['splits'][s]['field_exact_excluding_gt_gaps'][f]:.4f}" for s in ("dev", "test", "all"))
        print(f"  {f:<15} {raw}  |  {adj}")
    g = rep["ground_truth_gaps"]
    print(f"\nground-truth gaps (not extractor errors): {g['count']} {g['by_field']}")
    d = rep["documents"]
    print(f"\nDPR report date parsed: {d['report_date_ok']}/{d['dpr_docs']}   discipline group: {d['group_ok']}/{d['dpr_docs']}   "
          f"items from non-event lines: {d['noise_line_extractions']}   extraction issues: {d['issues']}")
    for k, v in d["sheets"].items():
        print(f"{k}: header row {'OK' if v['header_row_ok'] else 'WRONG'}, column mapping {'OK' if v['column_mapping_ok'] else 'WRONG'}")
    if args.show:
        for cat, xs in rep["misses"].items():
            print(f"\n{cat} ({len(xs)}):")
            for x in xs[: args.show]:
                print("  ", " | ".join(x))
    print(f"\nwritten: {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
