"""Validate the Phase 0 synthetic dataset (exit code 1 on any failure).

    python scripts/phase0/validate_dataset.py                 # validates data/synthetic/
    python scripts/phase0/validate_dataset.py --skip-regen    # skip the reproducibility re-run

Checks: file integrity vs manifest, schedule structure and dates, MSPDI/CSV agreement,
ground-truth references, report/spreadsheet locators, intended case mix, and that a
fresh generation is byte-identical to what is on disk.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import generate_dataset as gen
import xlsx_min

REQUIRED_HARD_CASES = ["abbreviation", "terminology_variant", "hinglish", "typo", "partial_description", "tag_only",
                       "type_ambiguous", "wrong_area", "granularity_finer", "granularity_coarser", "relative_date",
                       "explicit_date", "multi_item_line", "late_report", "duplicate_cross_source", "conflicting_date",
                       "new_activity", "unknown_reference"]
OUTCOME = {"matched": {"auto_apply", "review"}, "ambiguous": {"review"}, "unmatched": {"unmatched"}}


class Report:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        return ok

    def failed(self) -> list:
        return [r for r in self.results if not r[1]]


def d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


def read_csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate(root: Path, regen: bool = True) -> Report:
    rep = Report()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    # 1. integrity
    bad = [p for p, h in manifest["files"].items() if not (root / p).exists() or hashlib.sha256((root / p).read_bytes()).hexdigest() != h]
    rep.check("files match manifest hashes", not bad, f"{len(manifest['files'])} files" if not bad else f"mismatch: {bad[:5]}")
    rep.check("manifest seed", manifest["seed"] == gen.SEED, str(manifest["seed"]))

    # 2. schedule.csv
    nodes = read_csv(root / "schedule" / "schedule.csv")
    ids = [n["node_id"] for n in nodes]
    by_id = {n["node_id"]: n for n in nodes}
    rep.check("schedule: node IDs unique", len(ids) == len(set(ids)), f"{len(ids)} nodes")
    leaves = [n for n in nodes if n["node_type"] == "activity"]
    leaf_ids = {n["node_id"] for n in leaves}
    lo, hi = gen.LEAF_RANGE
    rep.check("schedule: L5/L6 activity count in range", lo <= len(leaves) <= hi, f"{len(leaves)} (target {lo}-{hi})")
    rep.check("schedule: activities are level 5 or 6", all(n["level"] in ("5", "6") for n in leaves),
              str(Counter(n["level"] for n in leaves)))
    discs = Counter(n["discipline"] for n in leaves)
    rep.check("schedule: >= 6 disciplines", len(discs) >= 6, ", ".join(f"{k}={v}" for k, v in sorted(discs.items())))
    orphans = [n["node_id"] for n in nodes if n["parent_id"] and n["parent_id"] not in by_id]
    lvl = [n["node_id"] for n in nodes if n["parent_id"] and int(n["level"]) != int(by_id[n["parent_id"]]["level"]) + 1]
    rep.check("schedule: parents exist and levels nest", not orphans and not lvl, f"orphans={orphans[:3]} level={lvl[:3]}")
    date_err = []
    root_node = nodes[0]
    p0, p1 = d(root_node["planned_start"]), d(root_node["planned_finish"])
    for n in nodes:
        try:
            s, f = d(n["planned_start"]), d(n["planned_finish"])
            if not (s and f and s <= f and p0 <= s and f <= p1 and (f - s).days + 1 == int(n["planned_duration_days"])):
                date_err.append(n["node_id"])
            a_s, a_f = d(n["actual_start"]), d(n["actual_finish"])
            if (a_s and a_s > gen.DATA_DATE) or (a_f and (not a_s or a_f < a_s or a_f > gen.DATA_DATE)):
                date_err.append(n["node_id"] + " (actuals)")
        except ValueError as e:
            date_err.append(f"{n['node_id']}: {e}")
    rep.check("schedule: dates valid (ISO, start<=finish, within project, actuals <= data date)", not date_err, str(date_err[:5]))
    bad_pred = [n["node_id"] for n in leaves for p in filter(None, n["predecessors"].split(";"))
                if p.split(":")[0] not in leaf_ids or p.split(":")[1][:2] not in ("FS", "SS")]
    rep.check("schedule: predecessors reference existing activities", not bad_pred, str(bad_pred[:5]))

    # 3. MSPDI agrees with CSV
    ns = {"m": gen.MSP_NS}
    xml = ET.parse(root / "schedule" / "schedule.xml").getroot()
    tasks = xml.findall("m:Tasks/m:Task", ns)
    uids = [t.findtext("m:UID", namespaces=ns) for t in tasks]
    text1 = {e.findtext("m:Value", namespaces=ns) for t in tasks for e in t.findall("m:ExtendedAttribute", ns)
             if e.findtext("m:FieldID", namespaces=ns) == "188743731"}
    pred_ok = all(pl.findtext("m:PredecessorUID", namespaces=ns) in set(uids) for t in tasks for pl in t.findall("m:PredecessorLink", ns))
    rep.check("schedule.xml (MSPDI): tasks == CSV nodes, UIDs unique, activity IDs match, links valid",
              len(tasks) == len(nodes) and len(set(uids)) == len(uids) and text1 == leaf_ids and pred_ok,
              f"{len(tasks)} tasks, {len(text1)} activity IDs")

    # 4. ground truth
    gt = root / "ground_truth"
    labels = read_csv(gt / "labels.csv")
    truth = {r["event_key"]: r for r in read_csv(gt / "truth_events.csv")}
    new_work = {r["new_work_key"]: r for r in read_csv(gt / "new_work.csv")}
    act_truth = {r["activity_id"]: r for r in read_csv(gt / "activity_truth.csv")}
    item_ids = [r["item_id"] for r in labels]
    rep.check("labels: item IDs unique", len(item_ids) == len(set(item_ids)), f"{len(item_ids)} items")
    rep.check("activity_truth covers every activity", set(act_truth) == leaf_ids, f"{len(act_truth)} rows")
    errs = []
    window = set(manifest["report_days"])
    for r in labels:
        iid, ml = r["item_id"], r["match_label"]
        cands = [c for c in r["candidate_activity_ids"].split(";") if c]
        if any(c not in leaf_ids for c in cands) or (r["true_activity_id"] and r["true_activity_id"] not in leaf_ids):
            errs.append(f"{iid}: unknown activity reference")
        if ml == "matched" and not (r["true_activity_id"] and cands == [r["true_activity_id"]] and r["event_key"]):
            errs.append(f"{iid}: matched needs true activity + event key")
        if ml == "ambiguous" and (len(cands) < 2 or (r["true_activity_id"] and r["true_activity_id"] not in cands)):
            errs.append(f"{iid}: ambiguous needs >=2 candidates incl. truth")
        if ml == "unmatched" and (r["true_activity_id"] or cands or r["unmatched_type"] not in ("new_activity", "unknown_reference")):
            errs.append(f"{iid}: unmatched must not reference plan activities")
        if r["unmatched_type"] == "new_activity" and (r["new_work_key"] not in new_work or r["suggested_parent_wbs"] not in by_id):
            errs.append(f"{iid}: new work key / suggested WBS parent invalid")
        if r["event_key"]:
            t = truth.get(r["event_key"])
            if not t or t["activity_id"] != r["true_activity_id"] or t["event_date"] != r["truth_date"] or t["event_type"] != r["event_type"]:
                errs.append(f"{iid}: event key disagrees with truth_events")
        if r["expected_outcome"] not in OUTCOME[ml]:
            errs.append(f"{iid}: outcome {r['expected_outcome']} inconsistent with {ml}")
        try:
            sd = d(r["stated_date"])
            if r["truth_date"] and r["truth_date"] not in window:
                errs.append(f"{iid}: truth date outside report window")
            if abs((sd - gen.WINDOW_START).days) > 30:
                errs.append(f"{iid}: stated date implausible")
        except ValueError:
            errs.append(f"{iid}: bad date")
    rep.check("labels: references and label rules consistent", not errs, "; ".join(errs[:5]))
    rep.check("truth_events: activities exist, dates in window",
              all(t["activity_id"] in leaf_ids and t["event_date"] in window for t in truth.values()), f"{len(truth)} events")

    # 5. report / spreadsheet locators
    extraction = json.loads((gt / "expected_extraction.json").read_text(encoding="utf-8"))
    docs = extraction["documents"]
    ex_items = {i["item_id"]: (doc, i) for doc in docs for i in doc["items"]}
    rep.check("expected_extraction items == labels items", set(ex_items) == set(item_ids), f"{len(ex_items)} items in {len(docs)} documents")
    loc_err = []
    cache: dict[str, object] = {}
    for doc in docs:
        p = root / doc["path"]
        if not p.exists():
            loc_err.append(f"missing {doc['path']}")
            continue
        if doc["source_type"] == "dpr":
            lines = p.read_text(encoding="utf-8").split("\n")
            item_lines = {i["locator"]["line"] for i in doc["items"]}
            if item_lines & {n["line"] for n in doc["non_event_lines"]}:
                loc_err.append(f"{doc['doc_id']}: line marked both event and noise")
            for i in doc["items"]:
                ln = i["locator"]["line"]
                if not (1 <= ln <= len(lines) and i["source_span"] in lines[ln - 1] and i["activity_text"] in i["source_span"]):
                    loc_err.append(f"{i['item_id']}: span not found at line {ln}")
        else:
            wb = cache.setdefault(doc["path"], xlsx_min.read(p))
            hdr_row = wb[doc["sheet"]][doc["header_row"]]
            col = {v: k for k, v in hdr_row.items()}
            if set(col) != set(doc["column_mapping"]):
                loc_err.append(f"{doc['doc_id']}: header/column_mapping mismatch")
            for i in doc["items"]:
                row = wb[i["locator"]["sheet"]].get(i["locator"]["row"], {})
                for h, v in i["cells"].items():
                    got = row.get(col.get(h))
                    got = got.isoformat() if isinstance(got, date) else got
                    if got != v:
                        loc_err.append(f"{i['item_id']}: cell {h} = {got!r}, expected {v!r}")
    on_disk = {p.relative_to(root).as_posix() for p in (root / "reports").glob("*.txt")} | \
              {p.relative_to(root).as_posix() for p in (root / "spreadsheets").glob("*.xlsx")}
    rep.check("every report/spreadsheet file is described in expected_extraction", on_disk == {doc["path"] for doc in docs},
              f"{len(on_disk)} source files")
    rep.check("report references valid (line/cell locators, verbatim spans)", not loc_err, "; ".join(loc_err[:5]))

    # 6. intended mix
    n = len(labels)
    rep.check(f"labelled items >= {gen.MIN_ITEMS}", n >= gen.MIN_ITEMS, str(n))
    mix = Counter(r["match_label"] for r in labels)
    for label, (a, b) in gen.TARGET_MIX.items():
        frac = mix[label] / n
        rep.check(f"mix: {label} share in [{a:.0%}, {b:.0%}]", a <= frac <= b, f"{mix[label]} ({frac:.1%})")
    rep.check("mix: easy, medium and hard matched items present",
              {"easy", "medium", "hard"} <= {r["difficulty"] for r in labels if r["match_label"] == "matched"},
              str(Counter(r["difficulty"] for r in labels)))
    hc = Counter(c for r in labels for c in r["hard_cases"].split(";") if c)
    low = {c: hc[c] for c in REQUIRED_HARD_CASES if hc[c] < gen.MIN_PER_HARD_CASE}
    rep.check(f"every hard-case category has >= {gen.MIN_PER_HARD_CASE} items", not low, str(low) if low else f"{len(REQUIRED_HARD_CASES)} categories")
    rep.check("both input kinds labelled (dpr + spreadsheet)", {"dpr", "spreadsheet"} <= {r["source_type"] for r in labels})
    splits = json.loads((gt / "splits.json").read_text(encoding="utf-8"))
    sp = Counter(r["split"] for r in labels)
    rep.check("dev/test splits non-empty and day-disjoint", sp["dev"] > 0 and sp["test"] > 0 and not set(splits["dev_days"]) & set(splits["test_days"]),
              f"dev={sp['dev']} test={sp['test']}")

    # 7. reproducibility
    if regen:
        with tempfile.TemporaryDirectory() as tmp:
            gen.generate(Path(tmp))
            fresh = {p.relative_to(tmp).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in Path(tmp).rglob("*") if p.is_file()}
        disk = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in fresh}
        diff = sorted(p for p in fresh if fresh[p] != disk.get(p))
        rep.check("reproducible: fresh generation is byte-identical", not diff, f"{len(fresh)} files" if not diff else f"differs: {diff[:5]}")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=gen.DEFAULT_OUT)
    ap.add_argument("--skip-regen", action="store_true")
    args = ap.parse_args()
    rep = validate(args.data, regen=not args.skip_regen)
    for name, ok, detail in rep.results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    failed = rep.failed()
    print(f"\n{len(rep.results) - len(failed)}/{len(rep.results)} checks passed")
    sys.exit(1 if failed else 0)
