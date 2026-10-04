"""Extraction entry points: pick the extractor for a document, then validate every item.

`extract_bytes` is pure (no DB) and is what the evaluation script runs; `process_document` in
p2e.ingest.service persists the result.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from p2e.db.models import DISCIPLINES
from p2e.extract.dpr import extract_dpr
from p2e.extract.formats import normalize
from p2e.extract.model import DocumentExtraction, ExtractedItem
from p2e.extract.rules import Vocabulary, is_canonical_tag, load_vocabulary
from p2e.extract.xlsx import extract_xlsx

EVENT_TYPES = ("start", "finish", "progress", "hold", "resume")
UNITS = ("spools", "m", "cables", "rings", "cum")
EARLIEST_BEFORE_PLAN = timedelta(days=90)


@dataclass(frozen=True)
class ProjectVocab:
    vocab: Vocabulary
    yes_words: frozenset[str]


@lru_cache(maxsize=8)
def load_project_vocab(glossary_path: Path) -> ProjectVocab:
    g = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
    yes = frozenset(w.strip().lower() for w in g["status_words_in_sheets"]["finish"])
    return ProjectVocab(load_vocabulary(str(glossary_path)), yes)


def extract_bytes(data: bytes, suffix: str, pv: ProjectVocab) -> DocumentExtraction:
    data, fmt = normalize(data, suffix.lstrip("."))      # .docx -> text, .csv -> workbook (upgrade W4)
    suffix = "." + fmt
    if suffix == ".txt":
        return extract_dpr(data.decode("utf-8"), pv.vocab)
    if suffix == ".xlsx":
        return extract_xlsx(data, set(pv.yes_words))
    raise ValueError(f"no extractor for {suffix!r}")


def validate_item(it: ExtractedItem, *, lines: list[str] | None, report_date: date | None,
                  project_start: date | None) -> list[str]:
    """Rules an extracted event must pass to be marked valid. Returns error messages (empty = valid)."""
    errors = list(it.problems)
    if not it.source_text:
        errors.append("no source evidence")
    if lines is not None:      # text document: the evidence must be verbatim on the referenced line
        ln = it.source_ref.get("line")
        a, b = it.span or (0, 0)
        if not isinstance(ln, int) or not 1 <= ln <= len(lines) or lines[ln - 1][a:b] != it.source_text:
            errors.append("source text not found at the referenced line/offsets")
    elif not it.source_cells:
        errors.append("no source cells")
    if not it.activity_text or it.activity_text not in it.source_text:
        errors.append("activity text missing or not part of the evidence")
    if it.event_type not in EVENT_TYPES:
        errors.append(f"event type {it.event_type!r} not one of {EVENT_TYPES}")
    if it.discipline not in DISCIPLINES:
        errors.append(f"discipline {it.discipline!r} not recognised")
    if it.event_date is None:
        if not it.problems:
            errors.append("no event date")
    else:
        if report_date and it.event_date > report_date:
            errors.append(f"event date {it.event_date} is after the report date {report_date}")
        if project_start and it.event_date < project_start - EARLIEST_BEFORE_PLAN:
            errors.append(f"event date {it.event_date} is implausibly early for this project")
        if it.not_before and it.event_date < it.not_before:
            errors.append(f"event date {it.event_date} is before the {it.not_before_label} {it.not_before}")
    if it.event_time is not None and not (len(it.event_time) == 5 and it.event_time[2] == ":"):
        errors.append(f"bad time {it.event_time!r}")
    if it.quantity is not None and (not math.isfinite(it.quantity) or it.quantity <= 0 or it.unit not in UNITS):
        errors.append(f"quantity {it.quantity!r} {it.unit!r} must be a positive number with a known unit")
    if it.quantity is None and it.unit is not None:
        errors.append("unit without quantity")
    bad = [t for t in it.tags if not is_canonical_tag(t)]
    if bad:
        errors.append(f"non-canonical tags {bad}")
    if it.delay_reason and not it.delay_category:
        errors.append("delay reason without category")
    return errors
