"""Tamper-evident audit chain (Phase 7 hardening): every audit entry stores sha256(previous entry_hash + its own content),
per project in id order. Editing or deleting a stored row breaks every later hash; `verify` reports the first break.
The ORM already refuses updates/deletes (append-only); the chain also catches changes made directly in the database."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from p2e.db.models import AuditLog, Project


def _ts(d: datetime) -> str:
    if d.tzinfo is None:                       # SQLite returns naive datetimes; they are written in UTC
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def entry_digest(e: AuditLog, prev: str) -> str:
    body = {"project_id": e.project_id, "plan_node_id": e.plan_node_id, "action": e.action, "changes": e.changes, "actor": e.actor,
            "rule": e.rule, "confidence": e.confidence, "evidence_event_ids": e.evidence_event_ids or [], "warnings": e.warnings or [],
            "reverts_id": e.reverts_id, "created_at": _ts(e.created_at)}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()


def seal(session: Session, e: AuditLog) -> None:
    """Set created_at and entry_hash on a new entry (call before adding it to the session)."""
    e.created_at = e.created_at or datetime.now(timezone.utc)
    prev = session.scalar(select(AuditLog.entry_hash).where(AuditLog.project_id == e.project_id).order_by(AuditLog.id.desc()).limit(1))
    e.entry_hash = entry_digest(e, prev or "")


def verify(session: Session, project: Project) -> dict:
    prev, first_broken, unhashed, n = "", None, [], 0
    for e in session.scalars(select(AuditLog).where(AuditLog.project_id == project.id).order_by(AuditLog.id)):
        n += 1
        expected = entry_digest(e, prev)
        if e.entry_hash is None:
            unhashed.append(e.id)
        elif e.entry_hash != expected and first_broken is None:
            first_broken = e.id
        prev = e.entry_hash or expected
    return {"entries": n, "ok": first_broken is None and not unhashed, "first_broken_entry": first_broken, "unhashed_entries": unhashed}
