"""Scoring + decision: candidates -> MATCHED | REVIEW | UNMATCHED with confidence, margin and reasons.

An event is only auto-matched when the object (tag / confirmed alias / the one activity agreeing with the reported
discipline + area + action) AND the reported work action agree, the area/discipline do not conflict and no other
candidate is about as good. Everything uncertain goes to REVIEW; nothing is ever forced onto an activity.
The score is a fixed, documented weighting (not a trained model); the evaluation reports how precise each band is.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from p2e.link.context import ProjectContext
from p2e.link.retrieve import Candidate, Query, ScheduleIndex, add_retrieved, attribute_matches, compatible, deterministic

LINKER_VERSION = "1.0.0"
WEIGHTS = {"object": 0.40, "action": 0.35, "lexical": 0.15, "area_match": 0.05, "discipline_match": 0.05,
           "area_conflict": -0.25, "discipline_conflict": -0.15}
OBJECT_EVIDENCE = {"tag": 1.0, "alias": 1.0, "attribute": 0.75}   # how strongly each method identifies the object


@dataclass
class Scored:
    cand: Candidate
    score: float
    features: dict
    reasons: list[str]


@dataclass
class Decision:
    decision: str                        # matched | review | unmatched
    node_id: int | None
    confidence: float                    # top candidate score
    margin: float                        # top - runner-up
    unmatched_type: str | None           # new_activity | unknown_reference | no_candidate
    method: str                          # tag | alias | attribute | lexical | none (how the top candidate was found)
    reasons: list[str]
    ranked: list[Scored] = field(default_factory=list)
    used_retrieval: bool = False         # True when stage-2 retrieval (lexical / attribute) ran


def _relation(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 0
    return 1 if compatible(a, b) else -1


def score(c: Candidate, q: Query, index: ScheduleIndex, ctx: ProjectContext, unique_attr: int | None) -> Scored:
    n = c.node
    exact = [a for a in q.actions if a in n.actions]
    near = [a for a in q.actions if a not in exact and ctx.equivalent.get(a, set()) & n.actions]
    action = 1.0 if exact else 0.5 if near else 0.0
    lexical, hit = index.overlap(q, n)
    lexical = max(lexical, c.lexical)
    area, disc = _relation(q.area, n.area), _relation(q.discipline, n.discipline)
    obj_by = [m for m in ("tag", "alias") if m in c.methods] + (["attribute"] if n.id == unique_attr else [])
    obj = max((OBJECT_EVIDENCE[m] for m in obj_by), default=0.0)
    f = {"object": obj, "object_by": obj_by, "action": action, "action_by": exact or near, "lexical": round(lexical, 4),
         "area": area, "discipline": disc}
    s = (WEIGHTS["object"] * obj + WEIGHTS["action"] * action + WEIGHTS["lexical"] * lexical
         + WEIGHTS["area_match"] * (area == 1) + WEIGHTS["discipline_match"] * (disc == 1)
         + WEIGHTS["area_conflict"] * (area == -1) + WEIGHTS["discipline_conflict"] * (disc == -1))
    reasons = ([f"tag {', '.join(c.matched_tags)}"] if c.matched_tags else []) + \
              ([f"confirmed alias '{', '.join(dict.fromkeys(c.matched_terms))}'"] if "alias" in c.methods else []) + \
              (["only activity with this discipline/area/action"] if "attribute" in obj_by else []) + \
              [f"action {a} ('{q.actions[a]}')" for a in exact] + [f"related action {a} ('{q.actions[a]}')" for a in near] + \
              ([f"words {', '.join(hit)}"] if hit else []) + \
              ([f"area {q.area} vs activity {n.area}"] if area == -1 else []) + \
              ([f"discipline {q.discipline} vs activity {n.discipline}"] if disc == -1 else [])
    return Scored(c, round(min(max(s, 0.0), 1.0), 4), f, reasons)


def decide(q: Query, index: ScheduleIndex, ctx: ProjectContext, object_aliases: list, retrieval: bool = True) -> Decision:
    """retrieval=False disables stage-2 retrieval (used only by the evaluation ablation)."""
    th = ctx.thresholds
    attr = attribute_matches(index, q) if q.actions else []
    unique_attr = attr[0].id if len(attr) == 1 else None
    cands = deterministic(index, q, object_aliases)
    used_retrieval = not any(score(c, q, index, ctx, unique_attr).features["action"] for c in cands.values())
    used_retrieval = used_retrieval and retrieval
    if used_retrieval:                                        # deterministic evidence not enough -> stage-2 retrieval
        add_retrieved(index, q, cands, th["lexical_top_k"])
    ranked = sorted((score(c, q, index, ctx, unique_attr) for c in cands.values()), key=lambda s: (-s.score, s.cand.node.code))
    ranked = ranked[: max(th["lexical_top_k"], sum("tag" in s.cand.methods for s in ranked))]
    top = ranked[0] if ranked else None
    margin = round(top.score - (ranked[1].score if len(ranked) > 1 else 0.0), 4) if top else 0.0

    def out(decision: str, reasons: list[str], unmatched: str | None = None) -> Decision:
        method = "none" if top is None else (top.features["object_by"] or
                                             [m for m in ("lexical", "attribute") if m in top.cand.methods] or ["none"])[0]
        return Decision(decision, top.cand.node.id if decision == "matched" else None, top.score if top else 0.0, margin,
                        unmatched, method, reasons, ranked, used_retrieval)

    if q.novelty:
        return out("unmatched", [f"reported as additional / unplanned work ('{q.novelty}')"], "new_activity")
    if q.tags and not any(t in index.by_tag for t in q.tags) and not any("alias" in s.cand.methods for s in ranked):
        return out("unmatched", [f"tag(s) {', '.join(q.tags)} not in the schedule"], "unknown_reference")
    if top is None:
        return out("unmatched", ["no schedule activity shares any evidence"], "no_candidate")
    gates = []
    if not top.features["action"]:
        gates.append("the reported work action matches no candidate" if q.actions else "no work action stated")
    if not top.features["object"] and not (top.features["lexical"] >= 0.6 and top.features["area"] == 1):
        gates.append("object not identified (no tag, alias, unique discipline/area/action match or strong name + area match)")
    if top.features["object_by"] == ["alias"] and top.cand.alias_confirmations < th["alias_auto_min_confirmations"]:
        gates.append(f"object known only from an alias confirmed {top.cand.alias_confirmations}x "
                     f"(auto needs {th['alias_auto_min_confirmations']})")
    if top.features["action_by"] and set(top.features["action_by"]) <= q.weak_actions:
        gates.append(f"work action known only from an alias confirmed fewer than {th['alias_auto_min_confirmations']}x")
    if top.features["area"] == -1:
        gates.append(f"area conflict ({q.area} vs {top.cand.node.area})")
    if top.features["discipline"] == -1:
        gates.append(f"discipline conflict ({q.discipline} vs {top.cand.node.discipline})")
    if margin < th["auto_min_margin"]:
        gates.append(f"runner-up {ranked[1].cand.node.code} too close (margin {margin})")
    if top.score < th["auto_min_score"]:
        gates.append(f"score {top.score} below {th['auto_min_score']}")
    if gates:
        return out("review", gates)
    return out("matched", top.reasons)
