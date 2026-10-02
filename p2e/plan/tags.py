"""Deterministic tag extraction from planned activity names (regex only — no fuzzy logic).

Canonical forms (see data/synthetic/glossary.json `tag_conventions`):
  piping line  24"-P-1203-A1A  -> LINE-1203
  tags         P-101A, TP-017, MCC-2, HT-SWBD-1, FT-2031, JB-301, PR-3 -> as written, upper-case
"""
from __future__ import annotations

import re

LINE_RE = re.compile(r'\d{1,2}"-[A-Z]-(\d{4})-[A-Z0-9]{2,4}')
TAG_RE = re.compile(r"\b([A-Z]{1,4}(?:-[A-Z]{2,5})?-\d{1,4}[A-Z]?)\b")


def extract_tags(name: str) -> list[str]:
    tags = {f"LINE-{m}" for m in LINE_RE.findall(name)}
    rest = LINE_RE.sub(" ", name)      # the line spec contains "P-1203", which is not an equipment tag
    tags |= {t.upper() for t in TAG_RE.findall(rest)}
    return sorted(tags)
