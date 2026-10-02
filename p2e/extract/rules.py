"""Deterministic field rules shared by the DPR and spreadsheet extractors.

Vocabulary (event verbs, delay reasons/categories) comes from the project glossary
(`data/synthetic/glossary.json` for the synthetic project), so another project swaps the
glossary rather than the code. Tag prefixes are the project's tag register conventions.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS["sept"] = 9

# Equipment / instrument / electrical / civil tag prefixes used on this project (glossary `tag_conventions`).
TAG_PREFIXES = ["HT-?SWBD", "MCC", "PCC", "FAP", "TP", "FT", "PT", "LT", "TT", "JB", "GD", "SS", "PR", "TR", "MC", "WS", "AS", "RC",
                "P", "K", "V", "E", "T"]
WORD_TAGS = [  # spelled-out forms used in the field -> tag prefix
    (r"flow transmitter", "FT"), (r"pressure transmitter", "PT"), (r"level transmitter", "LT"),
    (r"temperature transmitter", "TT"), (r"junction box", "JB"), (r"gas detector", "GD"), (r"safety shower", "SS"),
    (r"(?:pipe )?rack", "PR"), (r"tank", "T"),
]
_I = re.IGNORECASE
LINE_PATTERNS = [
    re.compile(r'\b\d{1,2}"-[A-Z]-(\d{4})-[A-Z0-9]{2,4}', _I),     # 24"-P-1203-A1A
    re.compile(r"\b(\d{4})-(?:W\d+|SP-\d+)\b", _I),                # joint 1205-W12, spool 1203-SP-03
    re.compile(r"\bL-?(\d{4})\b", _I),                              # L-1203, L1203
    re.compile(r"\b[PGWF]-(\d{4})\b", _I),                          # P-1203 (service-number)
    re.compile(r"\b(?:\d{1,2} inch )?line (\d{4})\b", _I),          # line 1203, 24 inch line 1203
    re.compile(r"\b(\d{4}) line\b", _I),                            # 1203 line
]
BARE_LINE = re.compile(r"(?<![\d./:-])\b(\d{4})\b(?![./:-]\d)(?! ?(?:m|cum)\b)", _I)   # not a quantity
TAG_RE = re.compile(r"\b(" + "|".join(TAG_PREFIXES) + r")[- ]?(\d{1,4})(?:[- ]?([A-Z])(?![A-Za-z]))?(?![\d])", _I)
WORD_TAG_RE = [(re.compile(rf"\b{w} (\d{{1,4}})\b", _I), p) for w, p in WORD_TAGS]
CT_RE = re.compile(r"\bCT-([NS])\b|\b(north|south) cable trench\b|\bcable trench \((north|south)\)", _I)
DCS_RE = re.compile(r"\bDCS\b", _I)
AREA_RE = re.compile(r"\b(?:area[- ]?|A-?)([1-4])\b", _I)
CANONICAL_TAG = re.compile(r"^(LINE-\d{4}|[A-Z]{1,3}(?:-SWBD)?-\d{1,4}[A-Z]?|CT-[NS]|DCS)$")


@dataclass(frozen=True)
class Vocabulary:
    verbs: dict[str, str]           # verb phrase (lower) -> event type
    reasons: dict[str, str]         # delay reason (lower) -> delay category


@lru_cache(maxsize=8)
def load_vocabulary(glossary_path: str) -> Vocabulary:
    g = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
    verbs = {v.lower(): et for et, vs in g["event_verbs"].items() for v in vs}
    reasons = {r.lower(): cat for cat, rs in g["delay_categories"].items() for r in rs}
    return Vocabulary(verbs, reasons)


def extract_tags(text: str, piping_context: bool = False) -> list[str]:
    """Canonical tags mentioned in field text: LINE-1203, P-101A, FT-2031, TP-017, MCC-2, CT-N, DCS ..."""
    tags: set[str] = set()
    rest = text
    for pat in LINE_PATTERNS:
        for m in pat.finditer(rest):
            tags.add(f"LINE-{m.group(1)}")
        rest = pat.sub(" ", rest)
    for pat, prefix in WORD_TAG_RE:
        for m in pat.finditer(rest):
            tags.add(f"{prefix}-{int(m.group(1)) if prefix == 'PR' else m.group(1)}")
        rest = pat.sub(" ", rest)
    for m in CT_RE.finditer(rest):
        side = (m.group(1) or m.group(2) or m.group(3))[0].upper()
        tags.add(f"CT-{side}")
    rest = CT_RE.sub(" ", rest)
    for m in TAG_RE.finditer(rest):
        prefix, num, suffix = m.group(1).upper().replace("HTSWBD", "HT-SWBD"), m.group(2), (m.group(3) or "").upper()
        if prefix == "P" and len(num) == 4:       # P-1203 without line form: service-number line reference
            tags.add(f"LINE-{num}")
            continue
        tags.add(f"{prefix}-{num}{suffix}")
    rest = TAG_RE.sub(" ", rest)
    if DCS_RE.search(rest):
        tags.add("DCS")
    if piping_context:
        tags |= {f"LINE-{m}" for m in BARE_LINE.findall(rest)}
    return sorted(tags)


def extract_area(text: str) -> str | None:
    found = {f"A{m}" for m in AREA_RE.findall(text)}
    return found.pop() if len(found) == 1 else None


def parse_date(text: str, ref: date | None = None) -> date | None:
    """Dates as written on site: 14/09/2026, 14/09/26, 14.09.2026, 14.09.26, 14-Sep-26, 14-Sep, Sep 14, 2026,
    2026-09-14, 14th Sept 2026, 14/9. Missing year -> year of `ref`."""
    t = text.strip().rstrip(".,")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2}|\d{4}))?", t)
    if m:
        return _mk(_year(m[3], ref), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?[- ]([A-Za-z]{3,4})(?:[- ](\d{2}|\d{4}))?", t)
    if m and m[2].lower() in MONTHS:
        return _mk(_year(m[3], ref), MONTHS[m[2].lower()], int(m[1]))
    m = re.fullmatch(r"([A-Za-z]{3,4}) (\d{1,2}),? (\d{4})", t)
    if m and m[1].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    return None


def _year(y: str | None, ref: date | None) -> int | None:
    if y is None:
        return ref.year if ref else None
    return int(y) + 2000 if len(y) == 2 else int(y)


def _mk(y: int | None, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d) if y else None
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))? ?(am|pm)?$", text.strip(), _I)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    if (m[3] or "").lower() == "pm" and h < 12:
        h += 12
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def cell_date(value, ref: date | None = None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_date(value, ref)
    return None


def is_canonical_tag(tag: str) -> bool:
    return bool(CANONICAL_TAG.match(tag))
