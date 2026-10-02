"""MAG alias memory: learn field wording from planner-confirmed links, and feed it back into retrieval/scoring.

Learning rule (MAG_VERSION):
  - only on a planner confirmation of a specific activity; the linker's own predictions are never learned
  - object alias: the confirmed event named its object without a usable tag ("fire water ring main") -> the phrase is
    stored against the activity's tags (so it generalises to every step of that object) or the activity itself
  - action alias: the event's work wording matched none of the activity's actions ("stand shifting") -> stored against
    the activity's action, if it has exactly one
  - an object phrase that already names more than one object in the schedule ("foundation") is too generic: not learned
  - a phrase already learned for a different target is NOT overwritten (conflict reported, the old one stays)
Trust ladder: an alias confirmed once only surfaces/ranks candidates (the decision stays REVIEW); from
`alias_auto_min_confirmations` (rules.json) independent confirmations it may support an automatic match.
Aliases are project-scoped, visible, and can be revoked; revoked aliases are never used.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from p2e.db.models import Alias, ProgressEvent
from p2e.link.context import ProjectContext
from p2e.link.retrieve import Node, ScheduleIndex, make_query

MAG_VERSION = "1"
MAX_PHRASE_WORDS = 6


def active(session: Session, project_id: int) -> list[Alias]:
    return list(session.scalars(select(Alias).where(Alias.project_id == project_id, Alias.status == "active").order_by(Alias.id)))


def fingerprint(aliases: list[Alias]) -> str:
    """Identifies the alias-memory state a decision used (changes whenever an alias is learned, confirmed again or revoked)."""
    body = "|".join(f"{a.kind}:{a.phrase}>{a.target}" for a in sorted(aliases, key=lambda a: (a.kind, a.phrase)))
    return f"{MAG_VERSION}-{hashlib.sha256(body.encode()).hexdigest()[:10]}"


def for_retrieval(aliases: list[Alias]) -> tuple[list[tuple[int, str, list[str], int]], dict[str, tuple[str, int]]]:
    """-> (object aliases as (id, phrase, tags-or-node targets, confirmations), action aliases {phrase: (action, confirmations)})."""
    objects = [(a.id, a.phrase, a.target.split(","), a.confirmations) for a in aliases if a.kind == "object"]
    return objects, {a.phrase: (a.target, a.confirmations) for a in aliases if a.kind == "action"}


def learn(session: Session, ctx: ProjectContext, index: ScheduleIndex, node: Node, event: ProgressEvent, actor: str) -> dict:
    """Called when a planner confirms `event` -> `node`. Returns what was learned / skipped and why."""
    q = make_query(ctx, event.activity_text, event.tags or [], event.area, event.discipline, event.source_ref, event.unit, {})
    action_words = {w for a in q.actions.values() for w in a.split()}
    object_words = [w for w in q.words if w not in action_words]
    result = {"learned": [], "skipped": []}
    if not set(q.tags) & node.tags:
        phrase = " ".join(dict.fromkeys(w for w in object_words if len(w) > 2))
        target = ",".join(sorted(node.tags)) if node.tags else f"node:{node.code}"
        named = {",".join(sorted(n.tags)) or n.code for n in index.nodes if set(phrase.split()) <= n.words} if phrase else set()
        if len(named) > 1:
            result["skipped"].append({"kind": "object", "phrase": phrase,
                                      "reason": f"too generic: already names {len(named)} objects in the schedule"})
        else:
            _store(session, ctx, result, "object", phrase, target, node, event, actor)
    if not (set(q.actions) & node.actions or any(ctx.equivalent.get(a, set()) & node.actions for a in q.actions)):
        phrase = " ".join(dict.fromkeys(w for w in q.words if w not in node.words and len(w) > 2))
        if len(node.actions) == 1:
            _store(session, ctx, result, "action", phrase, next(iter(node.actions)), node, event, actor)
        else:
            result["skipped"].append({"kind": "action", "phrase": phrase, "reason": "activity has no single work action"})
    return result


def _store(session, ctx, result, kind, phrase, target, node: Node, event, actor) -> None:
    words = phrase.split()
    if not words or len(words) > MAX_PHRASE_WORDS or all(w in ctx.stopwords for w in words):
        result["skipped"].append({"kind": kind, "phrase": phrase, "reason": f"phrase must have 1..{MAX_PHRASE_WORDS} content words"})
        return
    existing = session.scalar(select(Alias).where(Alias.project_id == event.project_id, Alias.kind == kind, Alias.phrase == phrase))
    if existing is not None and existing.target != target:
        result["skipped"].append({"kind": kind, "phrase": phrase, "reason": f"already learned for {existing.target}; not overwritten"})
        return
    if existing is not None:
        existing.confirmations += 1
        existing.status = "active"
        existing.confirmed_by = actor
    else:
        session.add(Alias(project_id=event.project_id, kind=kind, phrase=phrase, target=target, plan_node_id=node.id,
                          source_event_id=event.id, confirmed_by=actor, mag_version=MAG_VERSION))
    result["learned"].append({"kind": kind, "phrase": phrase, "target": target})


def mark_used(session: Session, alias_ids: set[int]) -> None:
    now = datetime.now(timezone.utc)
    for a in session.scalars(select(Alias).where(Alias.id.in_(alias_ids))):
        a.use_count += 1
        a.last_used_at = now


def revoke(alias: Alias) -> None:
    alias.status = "revoked"
