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
    shadow_mode: bool = False
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


# ----------------------------------------------------------------------------- Phase 3: linking, context (CAG), aliases (MAG)

LinkDecision = Literal["matched", "review", "unmatched"]
LinkState = Literal["auto", "pending", "confirmed", "rejected"]


class LinkRunIn(BaseModel):
    event_ids: list[int] | None = Field(None, max_length=5000, description="omit = every valid event of the project")


class LinkRunOut(Out):
    context_version: str
    mag_version: str
    linker_version: str
    counts: dict[str, int]
    conflicts: dict[str, int]
    llm_tiebreaker: bool


class CandidateOut(Out):
    rank: int
    plan_node_code: str
    activity_name: str
    level: int
    discipline: Discipline | None
    area: str | None
    score: float
    retrieval_methods: list[str]
    matched_tags: list[str]
    matched_terms: list[str]
    features: dict
    reasons: list[str]


class LinkOut(Out):
    event_id: int
    document_id: int
    activity_text: str
    event_type: EventType | None
    event_date: date | None
    decision: LinkDecision
    state: LinkState
    plan_node_code: str | None
    confidence: float
    margin: float
    unmatched_type: str | None
    method: str
    retrieval_used: bool
    reasons: list[str]
    llm_suggestion: dict | None
    linker_version: str
    context_version: str
    mag_version: str
    decided_by: str | None
    decided_at: datetime | None
    conflict: dict | None = None      # cross-source date conflict: activity, both events/documents/dates, rules


class LinkDetailOut(LinkOut):
    source_text: str
    source_ref: dict
    candidates: list[CandidateOut]


class LinkPage(Out):
    items: list[LinkOut]
    total: int
    limit: int
    offset: int


class ConfirmIn(BaseModel):
    plan_node_code: str = Field(min_length=1, max_length=64, description="the L5/L6 activity the event belongs to")


class ConfirmOut(Out):
    link: LinkDetailOut
    learned: list[dict]
    skipped: list[dict]


class AliasOut(Out):
    id: int
    kind: Literal["object", "action"]
    phrase: str
    target: str
    learned_from_activity: str
    source_event_id: int
    confirmed_by: str
    confirmations: int
    use_count: int
    status: Literal["active", "revoked"]
    mag_version: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


# ----------------------------------------------------------------------------- Phase 4: text Time Agent

class AgentAnswers(BaseModel):
    date: str | None = Field(None, max_length=40, description="answer to a date question: today, yesterday or a date")
    discipline: Discipline | None = None


class AgentMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000, pattern=r"^[^\r\n]+$", description="one line, as typed by the supervisor")
    reference_datetime: datetime | None = Field(None, description="resolves today/yesterday; default: now in the project timezone")
    discipline: Discipline | None = Field(None, description="the supervisor's discipline when the message does not say it")
    answers: AgentAnswers | None = Field(None, description="answers to a previous clarification (resend the same message)")
    lang: Literal["en", "ta", "hi"] | None = Field(None, description="reply language; default: the message's script, else English")


class AgentReplyOut(Out):
    status: Literal["recorded", "duplicate", "needs_clarification", "rejected", "checklist"]
    reply: str
    question: str | None
    interpretation: dict
    event_id: int | None
    document_id: int | None
    reference_datetime: datetime
    link: LinkDetailOut | None
    checklist: list[dict] | None = None     # "what should I report today?": expected-active activities


# ----------------------------------------------------------------------------- Phase 5: review queue, apply, audit

class AuditOut(Out):
    id: int
    plan_node_code: str
    action: Literal["apply", "override", "undo", "create_activity"]
    changes: dict
    actor: str
    rule: str
    confidence: float | None
    evidence_event_ids: list[int]
    warnings: list[str]
    reverts_id: int | None
    undone_by: int | None
    created_at: datetime


class ProposalOut(Out):
    plan_node_code: str
    activity_name: str
    proposed: dict
    changes: dict
    evidence_event_ids: list[int]
    confidence: float | None
    basis: Literal["auto", "planner", "mixed"]
    blockers: list[str]
    warnings: list[str]


class ApplyIn(BaseModel):
    as_of: date | None = Field(None, description="latest allowed actual date; default: today in the project timezone")
    dry_run: bool = False


class ApplyOut(Out):
    as_of: date
    dry_run: bool
    shadow: bool = False          # upgrade W5: project in shadow mode, nothing was written
    applied: list[AuditOut]
    would_apply: list[ProposalOut]
    blocked: list[ProposalOut]
    unchanged: int


class ReviewQueueOut(Out):
    as_of: date
    counts: dict[str, int]
    events: list[LinkDetailOut]          # pending link decisions, top-3 candidates
    activities: list[ProposalOut]        # activities whose evidence cannot be applied automatically


class ApproveIn(BaseModel):
    plan_node_code: str | None = Field(None, max_length=64, description="omit = the top candidate")
    as_of: date | None = None


class ApproveOut(Out):
    link: LinkDetailOut
    learned: list[dict]
    apply: ApplyOut


class NewActivityIn(BaseModel):
    parent_code: str = Field(min_length=1, max_length=128, description="L4 WBS node (or L5 summary) to create the activity under")
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=512)
    planned_start: date | None = None
    planned_finish: date | None = None
    as_of: date | None = None


class OverrideIn(BaseModel):
    actual_start: date | None = None
    actual_finish: date | None = None
    percent_complete: float | None = Field(None, ge=0, le=100)
    evidence_event_ids: list[int] = Field(default_factory=list, max_length=1000)
    as_of: date | None = None


class AuditPage(Out):
    items: list[AuditOut]
    total: int
    limit: int
    offset: int


# ----------------------------------------------------------------------------- Silent-activity watch

class WatchItemOut(Out):
    plan_node_code: str
    activity_name: str
    discipline: Discipline | None
    area: str | None
    planned_start: date
    planned_finish: date
    actual_start: date | None
    expectation: str
    last_reported: date | None
    days_silent: int | None = None          # None = never reported
    reported_today: bool | None = None      # checklist only


class WatchOut(Out):
    as_of: date
    days: int | None
    counts: dict[str, int]
    items: list[WatchItemOut]
