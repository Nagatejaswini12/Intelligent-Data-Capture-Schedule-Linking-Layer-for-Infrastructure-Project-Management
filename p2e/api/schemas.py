"""API contracts (Pydantic v2). Dates serialize as ISO 8601 (`YYYY-MM-DD`, timestamps with UTC offset)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["wbs", "summary", "activity"]
Discipline = Literal["civil", "piping", "static_eq", "rotating_eq", "electrical", "instrumentation", "hse", "other"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(Out):
    status: Literal["ok"]
    database: Literal["ok"]
    version: str


class ScheduleSourceOut(Out):
    filename: str
    format: str
    sha256: str
    size_bytes: int
    node_count: int
    activity_count: int
    created_at: datetime


class ProjectOut(Out):
    code: str
    name: str
    timezone: str
    data_date: date | None
    created_at: datetime
    updated_at: datetime
    schedule_sources: list[ScheduleSourceOut]


class ScheduleSummaryOut(Out):
    project_code: str
    total_nodes: int
    executable_activities: int
    nodes_by_type: dict[str, int]
    nodes_by_level: dict[str, int]
    activities_by_level: dict[str, int]
    activities_by_discipline: dict[str, int]
    activities_by_area: dict[str, int]
    planned_start: date | None
    planned_finish: date | None
    data_date: date | None


class NodeRef(Out):
    code: str
    node_type: NodeType
    level: int
    name: str


class PlanNodeOut(Out):
    code: str
    node_type: NodeType
    is_executable: bool
    level: int
    name: str
    wbs_code: str
    parent_code: str | None
    discipline: Discipline | None
    area: str | None
    activity_type: str | None
    planned_start: date
    planned_finish: date
    planned_duration_days: int
    planned_qty: float | None
    qty_unit: str | None
    actual_start: date | None
    actual_finish: date | None
    tags: list[str]


class DependencyOut(Out):
    code: str
    link_type: Literal["FS", "SS", "FF", "SF"]
    lag_days: int


class PlanNodeDetailOut(PlanNodeOut):
    ancestors: list[NodeRef]
    children: list[NodeRef]
    predecessors: list[DependencyOut]
    successors: list[DependencyOut]


class PlanNodePage(Out):
    items: list[PlanNodeOut]
    total: int
    limit: int
    offset: int


class TreeNodeOut(Out):
    code: str
    node_type: NodeType
    level: int
    name: str
    discipline: Discipline | None
    area: str | None
    planned_start: date
    planned_finish: date
    child_count: int
    children: list[TreeNodeOut]


class ProblemOut(BaseModel):
    """RFC 9457 problem details."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str | list | dict | None = None


# ----------------------------------------------------------------------------- Phase 2: documents & events

DocKind = Literal["schedule_import", "dpr_text", "spreadsheet"]
DocStatus = Literal["imported", "received", "extracted", "failed"]
EventType = Literal["start", "finish", "progress", "hold", "resume"]
ValidationStatus = Literal["valid", "invalid"]


class RunOut(Out):
    id: int
    extractor: str
    parser_version: str
    status: Literal["succeeded", "failed"]
    events_total: int
    events_valid: int
    events_invalid: int
    issues_count: int
    non_event_lines: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class DocumentOut(Out):
    id: int
    project_code: str
    kind: DocKind
    format: str
    filename: str
    sha256: str
    size_bytes: int
    status: DocStatus
    uploaded_by: str | None
    report_date: date | None
    discipline_group: str | None
    error: str | None
    created_at: datetime
    latest_run: RunOut | None


class DocumentPage(Out):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class IssueOut(Out):
    source_ref: dict
    source_text: str
    message: str


class DocumentStatusOut(Out):
    document_id: int
    status: DocStatus
    error: str | None
    runs: int
    latest_run: RunOut | None
    issues: list[IssueOut]


class ProcessOut(Out):
    document_id: int
    outcome: Literal["processed", "unchanged", "failed"]
    run: RunOut


class BatchProcessIn(BaseModel):
    document_ids: list[int] | None = Field(None, max_length=1000, description="omit = every uploaded report/sheet of the project")


class BatchItemOut(Out):
    document_id: int
    outcome: Literal["processed", "unchanged", "failed", "rejected", "not_found"]
    run: RunOut | None
    error: str | None


class BatchProcessOut(Out):
    items: list[BatchItemOut]
    counts: dict[str, int]


class EventOut(Out):
    id: int
    document_id: int
    document_filename: str
    source_type: DocKind
    source_ref: dict
    source_text: str
    report_date: date | None
    discipline: Discipline | None
    activity_text: str
    event_type: EventType | None
    event_date: date | None
    date_text: str | None
    event_time: str | None
    reported_actual_start: date | None    # = event_date when the field reported a start
    reported_actual_finish: date | None   # = event_date when the field reported a finish
    quantity: float | None
    unit: str | None
    area: str | None
    tags: list[str]
    delay_reason: str | None
    delay_category: str | None
    extraction_method: str
    parser_version: str
    validation_status: ValidationStatus
    validation_errors: list[str]
    created_at: datetime


class EventPage(Out):
    items: list[EventOut]
    total: int
    limit: int
    offset: int


class EvidenceOut(Out):
    document_id: int
    filename: str
    kind: DocKind
    sha256: str
    source_ref: dict
    source_text: str
    found_in_source: bool
    line_number: int | None = None
    line_text: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    context: list[dict] | None = None
    sheet: str | None = None
    row: int | None = None
    cells: list[dict] | None = None
