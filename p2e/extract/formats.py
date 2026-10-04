"""Upgrade W4: more field-report formats, converted at one boundary so the existing extractors, validation and evidence
apply unchanged. The uploaded original is what is stored (and hashed); conversion happens on every read.

  .docx -> plain text (one paragraph per line)        -> the DPR text extractor
  .csv  -> an in-memory one-sheet workbook ("Sheet1") -> the spreadsheet extractor (cell evidence = CSV row/column)
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime

from defusedxml import ElementTree as SafeET   # untrusted XML
from openpyxl import Workbook

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = SafeET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(f"{W}p"):
        parts = []
        for el in p.iter():
            if el.tag == f"{W}t":
                parts.append(el.text or "")
            elif el.tag == f"{W}tab":
                parts.append("\t")
            elif el.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines) + "\n"


def _cell(v: str):
    v = v.strip()
    if ISO_DATE.match(v):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return v
    if NUMBER.match(v):
        return float(v) if "." in v else int(v)
    return v or None


def csv_workbook(data: bytes) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
        ws.append([_cell(v) for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def normalize(data: bytes, fmt: str) -> tuple[bytes, str]:
    """(stored bytes, stored format) -> (bytes, 'txt' | 'xlsx') for the existing extractors and evidence readers."""
    if fmt == "docx":
        return docx_text(data).encode("utf-8"), "txt"
    if fmt == "csv":
        return csv_workbook(data), "xlsx"
    return data, fmt
