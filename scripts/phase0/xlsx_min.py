"""Minimal deterministic XLSX writer/reader (stdlib only) for the Phase 0 dataset.

Writes inline strings, numbers and real Excel date serials (numFmt 14), plus merged
cells and multiple sheets. Zip entries carry a fixed timestamp and are stored
uncompressed so the same input always gives byte-identical files.
The reader supports exactly what the writer produces (used by the validator);
later phases read these files with openpyxl.
"""
from __future__ import annotations

import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

EXCEL_EPOCH = date(1899, 12, 30)
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_letter(i: int) -> str:
    """0-based column index -> Excel letters."""
    s, n = "", i + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, date):
        return f'<c r="{ref}" s="1"><v>{(v - EXCEL_EPOCH).days}</v></c>'
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _sheet_xml(rows: list[list], merges: list[str]) -> str:
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{_NS}"><sheetData>']
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{col_letter(c)}{r}", v) for c, v in enumerate(row))
        out.append(f'<row r="{r}">{cells}</row>')
    out.append("</sheetData>")
    if merges:
        out.append(f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>")
    out.append("</worksheet>")
    return "".join(out)


_STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{_NS}">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
)


def write(path, sheets: list[tuple[str, list[list], list[str]]]) -> None:
    """sheets: [(name, rows, merge_refs)]; row values: str | int | float | date | None."""
    n = len(sheets)
    ct = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1)
        )
        + "</Types>"
    )
    rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG}">'
        f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    wb = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{_NS}" xmlns:r="{_R}"><sheets>'
        + "".join(f'<sheet name="{escape(s[0])}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
        + "</sheets></workbook>"
    )
    wb_rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG}">'
        + "".join(f'<Relationship Id="rId{i}" Type="{_R}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
        + f'<Relationship Id="rId{n + 1}" Type="{_R}/styles" Target="styles.xml"/></Relationships>'
    )
    parts = [("[Content_Types].xml", ct), ("_rels/.rels", rels), ("xl/workbook.xml", wb),
             ("xl/_rels/workbook.xml.rels", wb_rels), ("xl/styles.xml", _STYLES)]
    parts += [(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows, merges)) for i, (_, rows, merges) in enumerate(sheets, 1)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name, data in parts:
            z.writestr(zipfile.ZipInfo(name, _FIXED_TIME), data.encode("utf-8"))


def read(path) -> dict[str, dict[int, dict[str, object]]]:
    """-> {sheet_name: {row_number: {column_letter: value}}}; date-styled numbers become date."""
    q = lambda t: f"{{{_NS}}}{t}"
    out: dict[str, dict[int, dict[str, object]]] = {}
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sh in enumerate(wb.iter(q("sheet")), 1):
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            rows: dict[int, dict[str, object]] = {}
            for c in root.iter(q("c")):
                col, row = re.match(r"([A-Z]+)(\d+)", c.get("r")).groups()
                if c.get("t") == "inlineStr":
                    val: object = "".join(t.text or "" for t in c.iter(q("t")))
                else:
                    raw = c.find(q("v")).text
                    num = float(raw)
                    val = EXCEL_EPOCH + timedelta(days=int(num)) if c.get("s") == "1" else (int(num) if num.is_integer() else num)
                rows.setdefault(int(row), {})[col] = val
            out[sh.get("name")] = rows
    return out
