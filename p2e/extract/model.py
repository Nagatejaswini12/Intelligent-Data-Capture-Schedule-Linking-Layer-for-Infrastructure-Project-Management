"""Extractor output contract (pure data, no DB). One ExtractedItem = one reported progress fact with its evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ExtractedItem:
    source_ref: dict                 # DPR: {"line", "index"}; sheet: {"sheet", "row", "field"?}
    source_text: str                 # verbatim span (DPR) or " | "-joined evidence cells (sheet)
    activity_text: str               # reported activity description as written
    event_type: str | None           # start | finish | progress | hold | resume
    event_date: date | None
    date_text: str | None            # how the date was written ("yesterday", "12/9", Excel date ...)
    event_time: str | None = None    # HH:MM
    quantity: float | None = None
    unit: str | None = None
    discipline: str | None = None
    area: str | None = None
    tags: list[str] = field(default_factory=list)
    delay_reason: str | None = None
    delay_category: str | None = None
    span: tuple[int, int] | None = None      # text evidence: (start, end) character offsets in the referenced line
    source_cells: list[dict] | None = None   # sheet evidence: [{"header", "column", "cell", "value"}]
    not_before: date | None = None           # e.g. termination must not precede the same row's pull date
    not_before_label: str | None = None
    problems: list[str] = field(default_factory=list)   # extraction-time problems (become validation errors)

    @property
    def locator_key(self) -> str:
        return ";".join(f"{k}={v}" for k, v in self.source_ref.items())


@dataclass
class Issue:
    source_ref: dict
    source_text: str
    message: str


@dataclass
class DocumentExtraction:
    extractor: str
    parser_version: str
    report_date: date | None
    discipline_group: str | None
    items: list[ExtractedItem]
    issues: list[Issue]
    non_event_lines: int = 0
    meta: dict = field(default_factory=dict)
