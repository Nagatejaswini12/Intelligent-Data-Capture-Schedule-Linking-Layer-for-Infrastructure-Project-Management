"""Phase 1 schema: project, schedule import provenance, the L1–L6 plan tree, tags and logic links.
Phase 2: extraction runs, progress events, extraction issues. Phase 3: event links, link candidates, alias memory (MAG).
Phase 5: append-only audit log of schedule changes (apply / override / undo / new activity), plan_node.percent_complete.

Portable SQLAlchemy types only, so the same models run on SQLite (prototype) and PostgreSQL (production).
Database constraints mirror the importer's validation so bad data cannot get in by another path.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DISCIPLINES = ("civil", "piping", "static_eq", "rotating_eq", "electrical", "instrumentation", "hse", "other")
NODE_TYPES = ("wbs", "summary", "activity")   # wbs = L1–L4 hierarchy, summary = L5 parent of L6, activity = executable L5/L6
LINK_TYPES = ("FS", "SS", "FF", "SF")
DOC_KINDS = ("schedule_import", "dpr_text", "spreadsheet")
DOC_FORMATS = ("csv", "mspdi", "txt", "xlsx")
DOC_STATUSES = ("imported", "received", "extracted", "failed")
EVENT_TYPES = ("start", "finish", "progress", "hold", "resume")
VALIDATION_STATUSES = ("valid", "invalid")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(Timestamps, Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    data_date: Mapped[date | None] = mapped_column(Date)   # schedule status date

    sources: Mapped[list[SourceDocument]] = relationship(back_populates="project", order_by="SourceDocument.id")


class SourceDocument(Base):
    """Provenance of every file brought into the system: schedule imports (Phase 1), uploaded DPRs and sheets (Phase 2)."""
    __tablename__ = "source_document"
    __table_args__ = (UniqueConstraint("project_id", "sha256"), CheckConstraint(_in("kind", DOC_KINDS)),
                      CheckConstraint(_in("format", DOC_FORMATS)), CheckConstraint(_in("status", DOC_STATUSES)))
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    node_count: Mapped[int | None] = mapped_column(Integer)          # schedule imports
    activity_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="imported")
    storage_uri: Mapped[str | None] = mapped_column(String(255))      # uploads: file name inside the upload store
    uploaded_by: Mapped[str | None] = mapped_column(String(32))       # role of the API key that uploaded it
    report_date: Mapped[date | None] = mapped_column(Date)            # DPR date / sheet "updated upto" (set by extraction)
    discipline_group: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)   # ingestion timestamp

    project: Mapped[Project] = relationship(back_populates="sources")
    runs: Mapped[list[ExtractionRun]] = relationship(back_populates="document", order_by="ExtractionRun.id")


class PlanNode(Timestamps, Base):
    __tablename__ = "plan_node"
    __table_args__ = (
        UniqueConstraint("project_id", "code"),
        CheckConstraint("level BETWEEN 1 AND 6"),
        CheckConstraint(_in("node_type", NODE_TYPES)),
        CheckConstraint("node_type != 'activity' OR level IN (5, 6)"),
        CheckConstraint(f"discipline IS NULL OR {_in('discipline', DISCIPLINES)}"),
        CheckConstraint("planned_start <= planned_finish"),
        CheckConstraint("actual_finish IS NULL OR (actual_start IS NOT NULL AND actual_start <= actual_finish)"),
        Index("ix_plan_node_filter", "project_id", "node_type", "level"),
        Index("ix_plan_node_discipline", "project_id", "discipline"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    seq: Mapped[int] = mapped_column(Integer)            # order in the source file (stable list/tree order)
    code: Mapped[str] = mapped_column(String(64))        # activity ID for activities, WBS code for hierarchy nodes
    node_type: Mapped[str] = mapped_column(String(16))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("plan_node.id"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(512))
    wbs_code: Mapped[str] = mapped_column(String(128))
    discipline: Mapped[str | None] = mapped_column(String(32))
    area: Mapped[str | None] = mapped_column(String(32))
    activity_type: Mapped[str | None] = mapped_column(String(64))
    planned_start: Mapped[date] = mapped_column(Date)
    planned_finish: Mapped[date] = mapped_column(Date)
    planned_duration_days: Mapped[int] = mapped_column(Integer)
    planned_qty: Mapped[float | None] = mapped_column(Float)
    qty_unit: Mapped[str | None] = mapped_column(String(32))
    actual_start: Mapped[date | None] = mapped_column(Date)    # as imported; only the Phase 5 apply engine changes these
    actual_finish: Mapped[date | None] = mapped_column(Date)
    percent_complete: Mapped[float | None] = mapped_column(Float)   # Phase 5 apply engine (None = not known)

    parent: Mapped[PlanNode | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[PlanNode]] = relationship(back_populates="parent", order_by="PlanNode.seq")
    tags: Mapped[list[PlanTag]] = relationship(back_populates="node", cascade="all, delete-orphan", order_by="PlanTag.tag")
    predecessors: Mapped[list[PlanDependency]] = relationship(foreign_keys="PlanDependency.successor_id",
                                                              back_populates="successor", cascade="all, delete-orphan")

    @property
    def is_executable(self) -> bool:
        return self.node_type == "activity"


class PlanTag(Base):
    """Canonical identifiers found in an activity name (P-101A, LINE-1203, TP-017) — exact-lookup index for linking."""
    __tablename__ = "plan_tag"
    node_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"), primary_key=True)
    tag: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)

    node: Mapped[PlanNode] = relationship(back_populates="tags")


class PlanDependency(Base):
    __tablename__ = "plan_dependency"
    __table_args__ = (CheckConstraint(_in("link_type", LINK_TYPES)), CheckConstraint("successor_id != predecessor_id"))
    successor_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"), primary_key=True)
    predecessor_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"), primary_key=True)
    link_type: Mapped[str] = mapped_column(String(2))
    lag_days: Mapped[int] = mapped_column(Integer, default=0)

    successor: Mapped[PlanNode] = relationship(foreign_keys=[successor_id], back_populates="predecessors")
    predecessor: Mapped[PlanNode] = relationship(foreign_keys=[predecessor_id])


class ExtractionRun(Base):
    """One extraction pass over one document with one parser version."""
    __tablename__ = "extraction_run"
    __table_args__ = (CheckConstraint(_in("status", ("succeeded", "failed"))),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"), index=True)
    extractor: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    events_total: Mapped[int] = mapped_column(Integer, default=0)
    events_valid: Mapped[int] = mapped_column(Integer, default=0)
    events_invalid: Mapped[int] = mapped_column(Integer, default=0)
    issues_count: Mapped[int] = mapped_column(Integer, default=0)
    non_event_lines: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[SourceDocument] = relationship(back_populates="runs")
    issues: Mapped[list[ExtractionIssue]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ProgressEvent(Base):
    """Canonical progress event extracted from a field source. Not linked to a plan node in Phase 2."""
    __tablename__ = "progress_event"
    __table_args__ = (
        UniqueConstraint("source_document_id", "locator_key"),          # re-processing can never duplicate an event
        CheckConstraint(f"event_type IS NULL OR {_in('event_type', EVENT_TYPES)}"),
        CheckConstraint(f"discipline IS NULL OR {_in('discipline', DISCIPLINES)}"),
        CheckConstraint(_in("validation_status", VALIDATION_STATUSES)),
        Index("ix_event_filter", "project_id", "validation_status", "event_type"),
        Index("ix_event_date", "project_id", "event_date"),
        Index("ix_event_discipline", "project_id", "discipline"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"), index=True)
    extraction_run_id: Mapped[int] = mapped_column(ForeignKey("extraction_run.id"))
    locator_key: Mapped[str] = mapped_column(String(128))
    source_ref: Mapped[dict] = mapped_column(JSON)                     # {"line","index"} | {"sheet","row","field"}
    source_text: Mapped[str] = mapped_column(Text)                     # verbatim evidence
    span_start: Mapped[int | None] = mapped_column(Integer)            # text documents: character offsets in the line
    span_end: Mapped[int | None] = mapped_column(Integer)
    source_cells: Mapped[list | None] = mapped_column(JSON)            # sheet evidence cells with A1 references
    report_date: Mapped[date | None] = mapped_column(Date)
    discipline: Mapped[str | None] = mapped_column(String(32))
    activity_text: Mapped[str] = mapped_column(Text)                   # reported activity description as written
    event_type: Mapped[str | None] = mapped_column(String(16))
    event_date: Mapped[date | None] = mapped_column(Date)
    date_text: Mapped[str | None] = mapped_column(String(64))          # how the date was written
    event_time: Mapped[str | None] = mapped_column(String(5))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16))
    area: Mapped[str | None] = mapped_column(String(32))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    delay_reason: Mapped[str | None] = mapped_column(String(255))
    delay_category: Mapped[str | None] = mapped_column(String(32))
    extraction_method: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(16))
    validation_status: Mapped[str] = mapped_column(String(16))
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[SourceDocument] = relationship()
    extraction_run: Mapped[ExtractionRun] = relationship()


class ExtractionIssue(Base):
    """Something in an item section that could not be parsed at all (kept for review, never silently dropped)."""
    __tablename__ = "extraction_issue"
    id: Mapped[int] = mapped_column(primary_key=True)
    extraction_run_id: Mapped[int] = mapped_column(ForeignKey("extraction_run.id"), index=True)
    source_ref: Mapped[dict] = mapped_column(JSON)
    source_text: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)

    run: Mapped[ExtractionRun] = relationship(back_populates="issues")


# ----------------------------------------------------------------------------- Phase 3: schedule linking + alias memory

LINK_DECISIONS = ("matched", "review", "unmatched")
LINK_STATES = ("auto", "pending", "confirmed", "rejected")   # auto = linker decided alone; confirmed/rejected = a planner did
ALIAS_KINDS = ("object", "action")
ALIAS_STATUSES = ("active", "revoked")


class EventLink(Base):
    """Current link decision for one progress event (re-linking replaces it unless a planner already decided)."""
    __tablename__ = "event_link"
    __table_args__ = (
        UniqueConstraint("progress_event_id"),
        CheckConstraint(_in("decision", LINK_DECISIONS)),
        CheckConstraint(_in("state", LINK_STATES)),
        CheckConstraint("decision != 'matched' OR plan_node_id IS NOT NULL"),
        CheckConstraint("decision = 'matched' OR plan_node_id IS NULL"),
        CheckConstraint("confidence BETWEEN 0 AND 1"),
        Index("ix_link_filter", "project_id", "decision", "state"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    progress_event_id: Mapped[int] = mapped_column(ForeignKey("progress_event.id"))
    plan_node_id: Mapped[int | None] = mapped_column(ForeignKey("plan_node.id"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    margin: Mapped[float] = mapped_column(Float)
    unmatched_type: Mapped[str | None] = mapped_column(String(32))     # new_activity | unknown_reference | no_candidate | planner
    method: Mapped[str] = mapped_column(String(16))                    # how the top candidate was found
    retrieval_used: Mapped[bool] = mapped_column(default=False)        # stage-2 (RAG) retrieval ran
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    llm_suggestion: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))   # tie-breaker output (advisory only)
    # Phase 3.1: cross-source date conflict (activity, both events/documents/dates, rules) - set => automatic match held for review
    conflict: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    linker_version: Mapped[str] = mapped_column(String(16))
    context_version: Mapped[str] = mapped_column(String(16))           # CAG context the decision used
    mag_version: Mapped[str] = mapped_column(String(16))               # alias-memory state the decision used
    state: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    event: Mapped[ProgressEvent] = relationship()
    node: Mapped[PlanNode | None] = relationship()
    candidates: Mapped[list[LinkCandidate]] = relationship(back_populates="link", cascade="all, delete-orphan",
                                                           order_by="LinkCandidate.rank")


class LinkCandidate(Base):
    """A retrieved activity with its score and the evidence behind it (explainability + evaluation)."""
    __tablename__ = "link_candidate"
    __table_args__ = (UniqueConstraint("link_id", "rank"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("event_link.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    plan_node_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"))
    score: Mapped[float] = mapped_column(Float)
    methods: Mapped[list] = mapped_column(JSON)                        # tag | alias | lexical | attribute
    matched_tags: Mapped[list] = mapped_column(JSON, default=list)
    matched_terms: Mapped[list] = mapped_column(JSON, default=list)
    features: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON, default=list)

    link: Mapped[EventLink] = relationship(back_populates="candidates")
    node: Mapped[PlanNode] = relationship()


class Alias(Base):
    """MAG alias memory: field wording learned from planner-confirmed links only.
    object: phrase -> the object (its tags, or the activity when it has none); action: phrase -> a work action."""
    __tablename__ = "alias"
    __table_args__ = (UniqueConstraint("project_id", "kind", "phrase"), CheckConstraint(_in("kind", ALIAS_KINDS)),
                      CheckConstraint(_in("status", ALIAS_STATUSES)), CheckConstraint("confirmations >= 1"))
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    phrase: Mapped[str] = mapped_column(String(255))                   # normalised field wording
    target: Mapped[str] = mapped_column(String(255))                   # object: "LINE-1407" / "node:CIV-A3-SWD3-SWD"; action: "erection"
    plan_node_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"))   # the confirmed activity it was learned from
    source_event_id: Mapped[int] = mapped_column(ForeignKey("progress_event.id"))
    confirmed_by: Mapped[str] = mapped_column(String(32))
    confirmations: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    mag_version: Mapped[str] = mapped_column(String(16))               # learning-rule version that created it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    node: Mapped[PlanNode] = relationship()
    source_event: Mapped[ProgressEvent] = relationship()


# ----------------------------------------------------------------------------- Phase 5: schedule write-back audit

AUDIT_ACTIONS = ("apply", "override", "undo", "create_activity")


class AuditLog(Base):
    """Append-only record of every schedule change. Undo is a new, compensating entry (`reverts_id`); rows are never edited."""
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(_in("action", AUDIT_ACTIONS)), UniqueConstraint("reverts_id"),
                      Index("ix_audit_node", "project_id", "plan_node_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    plan_node_id: Mapped[int] = mapped_column(ForeignKey("plan_node.id"))
    action: Mapped[str] = mapped_column(String(16))
    changes: Mapped[dict] = mapped_column(JSON)                  # {field: [before, after]} (ISO dates / numbers / null)
    actor: Mapped[str] = mapped_column(String(64))               # human:<role> | process:<id>
    rule: Mapped[str] = mapped_column(String(64))                # auto_evidence | planner_evidence | mixed_evidence | planner_override | undo | new_activity
    confidence: Mapped[float | None] = mapped_column(Float)      # lowest link confidence of the evidence
    evidence_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    reverts_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entry_hash: Mapped[str | None] = mapped_column(String(64))  # Phase 7: sha256(previous entry_hash + this entry), tamper-evident

    node: Mapped[PlanNode] = relationship()


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _append_only(mapper, connection, target):
    raise ValueError("audit_log is append-only; write a compensating entry instead")
