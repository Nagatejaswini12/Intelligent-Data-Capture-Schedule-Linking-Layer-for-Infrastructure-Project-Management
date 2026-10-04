"""Deterministic extractor for free-text daily progress reports (structured and informal layouts).

Item grammar (one reported fact):
    <activity text> <event verb>[ (<n> cum)][ at|from|@ <time>][ today|yesterday|yday| on <date>][ –|due to|, <delay reason>]
    <activity text> – <n> spools erected | <n> m pulled | <n> cables terminated | ring(s) <n>[ & <n>] erected[ <date>]
Several items may share a line, joined by "; ", ", " or " & "; the splitter only splits where every
part is itself a complete item, so "&" inside an activity ("Rebar & shutt.") is never split.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from p2e.extract.model import DocumentExtraction, ExtractedItem, Issue
from p2e.extract.rules import Vocabulary, extract_area, extract_tags, parse_date, parse_time

EXTRACTOR = "dpr-grammar"
PARSER_VERSION = "1.0.0"
GROUP_DISCIPLINE = {"civil": "civil", "piping": "piping", "electrical": "electrical", "instrumentation": "instrumentation", "hse": "hse"}
ROTATING_HINT = re.compile(r"\b(?:pump|compressor|motor|skid|lube)\b|\b[PK]-?\d{3}", re.IGNORECASE)
SEP = re.compile(r"; |, | & ")
NIL = re.compile(r"^(?:nil\b|no major activity)", re.IGNORECASE)
HEADER_KEYS = re.compile(r"^(?:project|discipline|date|weather|manpower|safety|prepared by|report no)\b", re.IGNORECASE)


def _grammar(vocab: Vocabulary) -> tuple[re.Pattern, re.Pattern]:
    alt = lambda xs: "|".join(re.escape(x) for x in sorted(xs, key=len, reverse=True))
    date_tail = r"(?: (?P<rel>today|yesterday|yday)| on (?P<dt>[^\s;,]+))?"
    verb_item = re.compile(
        rf"^(?P<obj>.+?) (?P<verb>{alt(vocab.verbs)})(?: \((?P<cum>\d+(?:\.\d+)?) cum\))?"
        rf"(?: (?P<time>(?:at|from|@) \d{{1,2}}(?:[:.]\d{{2}})?(?: ?[ap]m)?))?{date_tail}"
        rf"(?:(?: – | due to |, )(?P<reason>{alt(vocab.reasons)}))?$", re.IGNORECASE)
    qty_item = re.compile(
        rf"^(?P<obj>.+?) – (?:(?P<spools>\d+) spools? erected|(?P<m>\d+) m pulled|(?P<cables>\d+) cables? terminated|"
        rf"rings? (?P<rings>\d+(?: & \d+)*) erected){date_tail}$", re.IGNORECASE)
    return verb_item, qty_item


def _split(body: str, start: int, match) -> list[tuple[int, int, re.Match]] | None:
    """Split body[start:] into complete items (shortest-first, all-or-nothing)."""
    for m in SEP.finditer(body, start):
        head = match(body[start:m.start()])
        if head:
            rest = _split(body, m.end(), match)
            if rest is not None:
                return [(start, m.start(), head)] + rest
    whole = match(body[start:])
    return [(start, len(body), whole)] if whole else None


def _header(lines: list[str]) -> tuple[date | None, str | None, str]:
    first = lines[0] if lines else ""
    if first.lower().startswith("cgs site update"):
        parts = first.split(" - ")
        return parse_date(parts[-1]) if len(parts) >= 3 else None, (parts[1].split()[0].lower() if len(parts) >= 3 else None), "informal"
    report_date = group = None
    for ln in lines[:8]:
        if ln.startswith("Date:"):
            report_date = parse_date(re.split(r"\s{2,}", ln[5:].strip())[0])
        elif ln.startswith("Discipline:"):
            group = ln[11:].strip().split()[0].lower()
    return report_date, group, "structured"


def _resolve(m: re.Match, report_date: date | None) -> tuple[date | None, str | None, list[str]]:
    rel, dt = m.group("rel"), m.group("dt")
    if report_date is None:
        return None, rel or dt, ["report date unknown, cannot resolve event date"]
    if dt:
        d = parse_date(dt, report_date)
        return d, dt, ([] if d else [f"unparseable date {dt!r}"])
    if rel and rel.lower() in ("yesterday", "yday"):
        return report_date - timedelta(days=1), rel, []
    return report_date, rel, []


def text_lines(text: str) -> list[str]:
    """The one line split used for parsing, evidence offsets and evidence display (Windows/Notepad uploads are CRLF)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def extract_dpr(text: str, vocab: Vocabulary) -> DocumentExtraction:
    lines = text_lines(text)
    if lines and lines[-1] == "":
        lines.pop()
    report_date, group, layout = _header(lines)
    verb_item, qty_item = _grammar(vocab)
    match = lambda s: verb_item.fullmatch(s) or qty_item.fullmatch(s)
    items, issues, noise = [], [], 0
    section = None
    for ln_no, line in enumerate(lines, 1):
        stripped = line.strip()
        body_at = None
        if layout == "structured":
            low = stripped.lower()
            if low in ("work done today:", "hold / constraints:", "plan for tomorrow:"):
                section, noise = low, noise + 1
                continue
            if section in ("work done today:", "hold / constraints:") and (m := re.match(r"^(?:\d+\. |- )", line)):
                body_at = m.end()
        else:
            if m := re.match(r"^(?:Today|Also|Hold): ", line, re.IGNORECASE):
                body_at = m.end()
        if body_at is None:
            noise += bool(stripped)
            continue
        body = line[body_at:]
        if NIL.match(body):
            noise += 1
            continue
        parts = _split(body, 0, match)
        if parts is None:
            issues.append(Issue({"line": ln_no}, line, "line in an item section does not follow the report grammar"))
            continue
        for idx, (a, b, m) in enumerate(parts):
            items.append(_item(m, line, body_at + a, body_at + b, ln_no, idx, report_date, group, vocab))
    return DocumentExtraction(EXTRACTOR, PARSER_VERSION, report_date, group, items, issues, noise, {"layout": layout})


def _item(m: re.Match, line: str, a: int, b: int, ln_no: int, idx: int, report_date, group, vocab: Vocabulary) -> ExtractedItem:
    span, obj = line[a:b], m.group("obj")
    gd = m.groupdict()
    event_date, date_text, problems = _resolve(m, report_date)
    qty = unit = None
    if "verb" in gd:
        event_type = vocab.verbs[gd["verb"].lower()]
        if gd["cum"]:
            qty, unit = float(gd["cum"]), "cum"
    else:
        event_type = "progress"
        for u in ("spools", "m", "cables"):
            if gd[u]:
                qty, unit = float(gd[u]), u
        if gd["rings"]:
            qty, unit = float(len(gd["rings"].split("&"))), "rings"
    reason = gd.get("reason")
    tags = extract_tags(obj, piping_context=group == "piping")
    discipline = GROUP_DISCIPLINE.get(group or "")
    if group == "mechanical":
        discipline = "rotating_eq" if ROTATING_HINT.search(obj) else "static_eq"
    return ExtractedItem(
        source_ref={"line": ln_no, "index": idx}, source_text=span, span=(a, b), activity_text=obj, event_type=event_type,
        event_date=event_date, date_text=date_text, event_time=parse_time(gd["time"].split(" ", 1)[1]) if gd.get("time") else None,
        quantity=qty, unit=unit, discipline=discipline, area=extract_area(obj), tags=tags,
        delay_reason=reason, delay_category=vocab.reasons.get(reason.lower()) if reason else None, problems=problems)
