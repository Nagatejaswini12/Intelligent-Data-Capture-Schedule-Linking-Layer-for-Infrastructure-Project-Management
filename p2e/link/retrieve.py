"""RAG retrieval step: progress event -> candidate L5/L6 activities, each with score inputs and the evidence behind it.

Two stages, so retrieval is not used blindly:
  1. deterministic: exact canonical tags (plan_tag index) and confirmed MAG object aliases
  2. lexical retrieval over the whole schedule (IDF-weighted overlap of glossary-normalised words), run only when stage 1
     finds no candidate that shares the reported work action
Local, in-memory and reproducible (same schedule + context + aliases -> same candidates). No dense embeddings: the field
vocabulary is mostly codes and abbreviations, which the glossary/tag layer handles; a local embedding model can be added
as a third stage later without changing the decision layer.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from p2e.db.models import PlanNode, Project
from p2e.extract.rules import extract_tags
from p2e.link.context import AREA_RE, ProjectContext

# What a Phase 2 structured item already says about the work (spreadsheet field / reported unit).
FIELD_ACTIONS = {"pull": "pulling", "termination": "termination", "install": "installation", "tubing": "tubing"}
UNIT_ACTIONS = {"spools": "erection", "rings": "shell", "cables": "termination", "m": "pulling"}


@dataclass
class Node:
    id: int
    code: str
    name: str
    discipline: str | None
    area: str | None
    activity_type: str | None
    tags: frozenset[str]
    actions: frozenset[str]
    words: frozenset[str]


@dataclass
class Query:
    text: str                      # activity text as reported
    normalized: str
    words: list[str]
    actions: dict[str, str]        # action -> evidence term
    tags: list[str]
    area: str | None
    discipline: str | None
    novelty: str | None
    weak_actions: set[str] = field(default_factory=set)   # actions known only from an alias below the trust threshold


@dataclass
class Candidate:
    node: Node
    methods: set[str] = field(default_factory=set)        # tag | alias | lexical | attribute
    matched_tags: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    alias_ids: list[int] = field(default_factory=list)
    alias_confirmations: int = 0                           # strongest confirming alias (MAG trust ladder)
    lexical: float = 0.0


class ScheduleIndex:
    def __init__(self, nodes: list[Node]):
        self.nodes = nodes
        self.by_tag: dict[str, list[Node]] = {}
        self.by_code = {n.code: n for n in nodes}
        for n in nodes:
            for t in n.tags:
                self.by_tag.setdefault(t, []).append(n)
        df = Counter(w for n in nodes for w in n.words)
        self.idf = {w: math.log(1 + len(nodes) / c) for w, c in df.items()}

    @classmethod
    def build(cls, session: Session, project: Project, ctx: ProjectContext) -> ScheduleIndex:
        rows = session.scalars(select(PlanNode).options(selectinload(PlanNode.tags))
                               .where(PlanNode.project_id == project.id, PlanNode.node_type == "activity").order_by(PlanNode.seq))
        nodes = []
        for n in rows:
            norm = ctx.normalize(n.name)
            tags = {t.tag for t in n.tags} | set(extract_tags(n.name))   # same canonical forms the field extractor emits
            nodes.append(Node(n.id, n.code, n.name, n.discipline, n.area, n.activity_type, frozenset(tags),
                              frozenset(ctx.actions_in(norm)), frozenset(ctx.content_words(norm))))
        return cls(nodes)

    def overlap(self, q: Query, n: Node) -> tuple[float, list[str]]:
        """IDF-weighted share of the query's schedule words that the activity name contains."""
        qw = [w for w in dict.fromkeys(q.words) if w in self.idf]
        total = sum(self.idf[w] for w in qw)
        hit = [w for w in qw if w in n.words]
        return (sum(self.idf[w] for w in hit) / total if total else 0.0), hit

    def lexical(self, q: Query, k: int) -> list[tuple[Node, float, list[str]]]:
        scored = []
        for n in self.nodes:
            score, hit = self.overlap(q, n)
            if hit:
                scored.append((n, score, hit))
        scored.sort(key=lambda x: (-x[1], x[0].code))
        return scored[:k]


def make_query(ctx: ProjectContext, activity_text: str, tags: list[str], area: str | None, discipline: str | None,
               source_ref: dict, unit: str | None, action_aliases: dict[str, tuple[str, int]], min_confirmations: int = 2) -> Query:
    norm = ctx.normalize(activity_text)
    actions = ctx.actions_in(norm)
    implied = FIELD_ACTIONS.get(source_ref.get("field")) or (UNIT_ACTIONS.get(unit) if unit else None)
    if implied and implied not in actions:
        actions[implied] = f"[{source_ref.get('field') or unit}]"
    words = ctx.content_words(norm)
    weak = set()
    for phrase, (action, confirmations) in action_aliases.items():   # MAG: learned wording for an action (all words present)
        if action not in actions and set(phrase.split()) <= set(words):
            actions[action] = f"alias:{phrase}"
            if confirmations < min_confirmations:
                weak.add(action)
    if area is None and (m := AREA_RE.search(activity_text.lower())):
        area = f"A{m.group(1)}"
    return Query(activity_text, norm, words, actions, tags, area, discipline, ctx.is_novel(activity_text), weak)


def deterministic(index: ScheduleIndex, q: Query, object_aliases: list[tuple[int, str, list[str], int]]) -> dict[int, Candidate]:
    out: dict[int, Candidate] = {}
    for t in q.tags:
        for n in index.by_tag.get(t, []):
            c = out.setdefault(n.id, Candidate(n))
            c.methods.add("tag")
            c.matched_tags.append(t)
    for alias_id, phrase, targets, confirmations in object_aliases:        # MAG: learned name for an object (all its words in the report)
        if set(phrase.split()) <= set(q.words):
            for t in targets:
                for n in ([index.by_code[t[5:]]] if t.startswith("node:") and t[5:] in index.by_code else index.by_tag.get(t, [])):
                    c = out.setdefault(n.id, Candidate(n))
                    c.methods.add("alias")
                    c.matched_terms.append(phrase)
                    c.alias_ids.append(alias_id)
                    c.alias_confirmations = max(c.alias_confirmations, confirmations)
    return out


def compatible(a: str | None, b: str | None) -> bool:
    return not a or not b or a == b or {a, b} == {"static_eq", "rotating_eq"}


def attribute_matches(index: ScheduleIndex, q: Query) -> list[Node]:
    """Activities agreeing with every known attribute of the report: discipline + (area) + (an exact work action).
    Needs the discipline and at least one of area / action, otherwise it is not a retrieval filter."""
    if not q.discipline or not (q.area or q.actions):
        return []
    return [n for n in index.nodes if n.discipline and compatible(q.discipline, n.discipline)
            and (not q.area or n.area == q.area) and (not q.actions or n.actions & set(q.actions))]


def add_retrieved(index: ScheduleIndex, q: Query, cands: dict[int, Candidate], k: int) -> None:
    """Stage 2: lexical top-k + activities matching the report's attributes (top-k of those by word overlap)."""
    for n, score, hit in index.lexical(q, k):
        c = cands.setdefault(n.id, Candidate(n))
        c.methods.add("lexical")
        c.lexical = max(c.lexical, score)
        c.matched_terms.extend(w for w in hit if w not in c.matched_terms)
    attr = sorted(attribute_matches(index, q), key=lambda n: (-index.overlap(q, n)[0], n.code))
    for n in attr[:k]:
        c = cands.setdefault(n.id, Candidate(n))
        c.methods.add("attribute")
