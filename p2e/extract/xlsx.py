"""Spreadsheet extractor: header detection by synonyms -> template -> one ExtractedItem per reported fact.

Templates (by the canonical fields their header row maps to):
  spool tracker      line_tag + sub_item_id + date            -> progress, 1 spool per row
  cable log          sub_item_id + quantity (+ termination)   -> progress, metres pulled; progress, 1 cable terminated
  instrument register tag + date (+ tubing_date)              -> finish (mounted); finish (tubing)
Sheets without a recognisable header (e.g. a Summary sheet) are reported, not parsed.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date, datetime

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from p2e.extract.model import DocumentExtraction, ExtractedItem, Issue
from p2e.extract.rules import cell_date, extract_area, extract_tags

EXTRACTOR = "xlsx-templates"
PARSER_VERSION = "1.0.0"
HEADER_SYNONYMS = {
    "sr": None, "s.no": None, "sr.no": None, "sl no": None, "remarks": "remarks",
    "line no.": "line_tag", "line no": "line_tag", "spool no": "sub_item_id", "dia (in)": "size", "area": "area", "loc": "area",
    "location": "area", "erected dt": "date", "erection date": "date", "status": "status",
    "cable no": "sub_item_id", "frm": "from_location", "from": "from_location", "to": "to_location", "size": "cable_size",
    "len(m)": "quantity", "length (m)": "quantity", "pulled?": "status", "dt": "date", "date": "date",
    "termn": "termination_status", "termination": "termination_status", "termn dt": "termination_date",
    "tag no": "tag", "tag": "tag", "instrument": "description", "mounted on": "date", "tubing": "tubing_date",
}
CABLE_GROUP = re.compile(r"^C-([A-Z]+)(\d+)-\d+$", re.IGNORECASE)


def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h)).strip().lower() if h is not None else ""


def _template(fields: set[str]) -> str | None:
    if {"line_tag", "sub_item_id", "date"} <= fields:
        return "spool_tracker"
    if {"sub_item_id", "quantity", "date"} <= fields:
        return "cable_log"
    if {"tag", "date"} <= fields:
        return "instrument_register"
    return None


def _value(v):
    return v.date() if isinstance(v, datetime) else v


def _shown(v) -> object:
    v = _value(v)
    return v.isoformat() if isinstance(v, date) else v


def extract_xlsx(data: bytes, yes_words: set[str]) -> DocumentExtraction:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)   # cached values only; formulas never evaluated
    items: list[ExtractedItem] = []
    issues: list[Issue] = []
    meta: dict = {"sheets": {}}
    as_of = None
    for ws in wb.worksheets:
        rows = [tuple(_value(c) for c in r) for r in ws.iter_rows(values_only=True)]
        header_at, cols = None, {}
        for i, row in enumerate(rows[:10]):
            mapped = {j: HEADER_SYNONYMS[_norm(h)] for j, h in enumerate(row) if _norm(h) in HEADER_SYNONYMS}
            if len([f for f in mapped.values() if f]) >= 3:
                header_at, cols = i, mapped
                break
        for row in rows[: header_at or 0]:
            for v in row:
                if isinstance(v, str) and v.lower().startswith("updated upto"):
                    as_of = cell_date(v.split(":", 1)[-1].strip())
        if header_at is None:
            meta["sheets"][ws.title] = {"template": None}
            continue
        headers = {j: str(rows[header_at][j]) for j in cols}
        field_col = {f: j for j, f in cols.items() if f}
        template = _template(set(field_col))
        meta["sheets"][ws.title] = {"template": template, "header_row": header_at + 1,
                                    "column_mapping": {headers[j]: f for j, f in sorted(cols.items())}}
        if template is None:
            continue
        years = Counter(v.year for r in rows[header_at + 1:] for v in r if isinstance(v, date))
        ref = date(years.most_common(1)[0][0], 1, 1) if years else None
        for i, row in enumerate(rows[header_at + 1:], start=header_at + 2):
            if not any(v not in (None, "") for v in row):
                continue
            get = lambda f: row[field_col[f]] if f in field_col and field_col[f] < len(row) else None

            def evidence(*fs: str) -> list[dict]:
                return [{"header": headers[field_col[f]], "column": get_column_letter(field_col[f] + 1),
                         "cell": f"{get_column_letter(field_col[f] + 1)}{i}", "value": _shown(get(f))} for f in fs if f in field_col]

            def item(field: str | None, fs: tuple, event_type: str, date_value, **kw) -> ExtractedItem:
                cells = evidence(*fs)
                d = cell_date(date_value, ref)
                problems = [] if d else [f"missing or unparseable date {date_value!r}"]
                ref_ = {"sheet": ws.title, "row": i} | ({"field": field} if field else {})
                return ExtractedItem(ref_, " | ".join(str(c["value"]) for c in cells), str(cells[0]["value"]), event_type, d,
                                     _shown(date_value) if date_value is not None else None, source_cells=cells,
                                     problems=problems + kw.pop("problems", []), **kw)

            yes = lambda v: v is not None and str(v).strip().lower() in yes_words
            if template == "spool_tracker":
                if not yes(get("status")):
                    continue
                ident = f"{get('sub_item_id') or ''} {get('line_tag') or ''}"
                items.append(item(None, ("line_tag", "sub_item_id", "date", "status"), "progress", get("date"), quantity=1.0,
                                  unit="spools", discipline="piping", area=extract_area(str(get("area") or "")),
                                  tags=extract_tags(str(get("sub_item_id") or "")) or extract_tags(ident)))
            elif template == "cable_log":
                cable = str(get("sub_item_id") or "")
                tags, area = [], None
                if g := CABLE_GROUP.match(cable):
                    kind, n = g.group(1).upper(), g.group(2)
                    if kind.startswith("HTTR"):
                        tags = [f"TR-{n}"]
                    elif kind == "LVA":
                        area = f"A{n}"
                    else:
                        tags = [f"{kind}-{n}"]
                qty, problems = get("quantity"), []
                if not isinstance(qty, (int, float)):
                    problems, qty = [f"non-numeric length {qty!r}"], None
                pulled = cell_date(get("date"), ref)
                if yes(get("status")) or get("status") is None and pulled:
                    items.append(item("pull", ("sub_item_id", "from_location", "quantity", "status", "date"), "progress", get("date"),
                                      quantity=float(qty) if qty is not None else None, unit="m", discipline="electrical",
                                      area=area, tags=tags, problems=problems))
                if yes(get("termination_status")):
                    items.append(item("termination", ("sub_item_id", "termination_status", "termination_date"), "progress",
                                      get("termination_date"), quantity=1.0, unit="cables", discipline="electrical", area=area,
                                      tags=tags, not_before=pulled, not_before_label="pull date"))
            else:
                tag_cell = str(get("tag") or "")
                tags, area = extract_tags(tag_cell), extract_area(str(get("area") or ""))
                if get("date") is not None:
                    items.append(item("install", ("tag", "date"), "finish", get("date"), discipline="instrumentation", area=area, tags=tags))
                if cell_date(get("tubing_date"), ref):
                    items.append(item("tubing", ("tag", "tubing_date"), "finish", get("tubing_date"), discipline="instrumentation",
                                      area=area, tags=tags, not_before=cell_date(get("date"), ref), not_before_label="mounting date"))
    wb.close()
    if not any(s.get("template") for s in meta["sheets"].values()):
        issues.append(Issue({}, "", "no sheet with a recognised progress-tracker header (spool tracker, cable log, instrument register)"))
    return DocumentExtraction(EXTRACTOR, PARSER_VERSION, as_of, None, items, issues, meta=meta)
