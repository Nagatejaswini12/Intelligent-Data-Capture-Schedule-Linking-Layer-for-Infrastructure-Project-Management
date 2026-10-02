"""CAG layer: the stable project context, built once and cached, used by every linking decision and as the fixed prompt
prefix for the optional LLM tie-breaker.

What is cached (slow-changing knowledge only; progress events are never cached here):
  - project glossary: abbreviations + Hinglish terms (data/synthetic/glossary.json, P2E_GLOSSARY)
  - matching rules: action lexicon, equivalent actions, synonyms, novelty markers, stopwords, thresholds (p2e/link/rules.json)
  - schedule terminology: the word vocabulary of the imported L5/L6 activity names (typo correction) + project metadata
Version = hash of the glossary file, the rules file, the imported schedule's SHA-256 and CONTEXT_FORMAT, so any change to a
source gives a new version and the cached context is rebuilt on next use (`refresh_context` forces it).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from p2e.db.models import PlanNode, Project, SourceDocument

CONTEXT_FORMAT = "1"
RULES_PATH = Path(__file__).with_name("rules.json")
# Identifier-like codes (P-101A, ht-swbd-1, lt4011, 1205-w12, 24"-p-1203-a1a): tags are matched separately, so they are cut
# out before the words are expanded (otherwise "HT" in HT-SWBD-1 would read as "hydrotest").
CODE_RE = re.compile(r"\b\d*\"?-?(?:[a-z]{1,6}-?)*\d+[a-z]?(?:-[a-z0-9]+)*\b")
AREA_RE = re.compile(r"\b(?:area[- ]?|a-?)([1-4])\b")
_cache: dict[int, ProjectContext] = {}


@dataclass
class ProjectContext:
    version: str
    sources: dict                    # what the version was computed from
    project_code: str
    data_date: str | None
    expansions: dict[str, str]       # glossary key -> expansion
    actions: dict[str, list[str]]    # canonical action -> field terms
    equivalent: dict[str, set[str]]  # action -> actions that count half
    synonyms: dict[str, str]
    novelty: list[str]
    stopwords: frozenset[str]
    thresholds: dict
    vocabulary: frozenset[str]       # schedule + rule words (typo correction targets)
    disciplines: list[str]
    areas: list[str]
    _typo: dict[str, str] = field(default_factory=dict, repr=False)

    @cached_property
    def _phrase_res(self) -> list[tuple[re.Pattern, str]]:
        subs = {**self.expansions, **self.synonyms}
        return [(re.compile(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])"), v) for k, v in sorted(subs.items(), key=lambda kv: -len(kv[0]))]

    @cached_property
    def _action_res(self) -> list[tuple[str, re.Pattern]]:
        return [(a, re.compile(rf"(?<![a-z0-9])(?:{'|'.join(re.escape(t) for t in sorted(ts, key=len, reverse=True))})(?![a-z0-9])"))
                for a, ts in self.actions.items()]

    def normalize(self, text: str) -> str:
        """lower-case, cut identifier codes, fix typos, expand glossary abbreviations / Hinglish / synonyms."""
        t = AREA_RE.sub(" ", CODE_RE.sub(" ", text.lower().replace("–", " ").replace("&", " and ")))
        t = " ".join(self._fix(w) for w in re.findall(r"[a-z][a-z./&-]*[a-z.]|[a-z]", t))
        for pat, rep in self._phrase_res:
            t = pat.sub(f" {rep} ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _fix(self, w: str) -> str:
        if len(w) < 5 or w in self.vocabulary or w in self.stopwords or w in self.expansions:
            return w
        if w not in self._typo:
            close = difflib.get_close_matches(w, self.vocabulary, n=1, cutoff=0.8)
            self._typo[w] = close[0] if close else w
        return self._typo[w]

    def actions_in(self, normalized: str) -> dict[str, str]:
        """canonical action -> the term that evidenced it."""
        return {a: m.group(0) for a, pat in self._action_res if (m := pat.search(normalized))}

    def content_words(self, normalized: str) -> list[str]:
        return [w for w in re.findall(r"[a-z]+", normalized) if w not in self.stopwords and len(w) > 1]

    def is_novel(self, text: str) -> str | None:
        low = text.lower()
        return next((m for m in self.novelty if re.search(rf"(?<![a-z]){re.escape(m)}(?![a-z])", low)), None)

    def prompt_prefix(self) -> str:
        """Deterministic, versioned text placed first in every LLM prompt so serving-side prefix caching applies."""
        abbr = "\n".join(f"- {k}: {v}" for k, v in sorted(self.expansions.items()))
        acts = "\n".join(f"- {a}: {', '.join(ts)}" for a, ts in self.actions.items())
        return (f"PROJECT CONTEXT {self.project_code} (context version {self.version})\n"
                f"You link construction site progress reports to schedule activities. Disciplines: {', '.join(self.disciplines)}. "
                f"Areas: {', '.join(self.areas)}.\nField abbreviations:\n{abbr}\nWork actions and the words used for them:\n{acts}\n"
                "Rules: choose only from the candidate activity codes given; answer NONE if no candidate is clearly the reported "
                "work; never invent codes.\n")

    def describe(self) -> dict:
        return {"version": self.version, "sources": self.sources, "project_code": self.project_code, "data_date": self.data_date,
                "cached": {"glossary_terms": len(self.expansions), "actions": len(self.actions), "synonyms": len(self.synonyms),
                           "novelty_markers": len(self.novelty), "schedule_vocabulary": len(self.vocabulary)},
                "thresholds": self.thresholds, "not_cached": "progress events, link decisions, aliases (MAG) - all dynamic"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _schedule_sha(session: Session, project: Project) -> str:
    shas = session.scalars(select(SourceDocument.sha256).where(SourceDocument.project_id == project.id,
                                                              SourceDocument.kind == "schedule_import").order_by(SourceDocument.id))
    return _sha("".join(shas).encode())


def get_context(session: Session, project: Project, glossary_path: Path, rules_path: Path = RULES_PATH) -> ProjectContext:
    """Cached per project; rebuilt only when a source changed (cheap fingerprint check on every call)."""
    g_bytes, r_bytes = Path(glossary_path).read_bytes(), Path(rules_path).read_bytes()
    sources = {"glossary": {"path": str(glossary_path), "sha256": _sha(g_bytes)},
               "rules": {"path": str(rules_path), "sha256": _sha(r_bytes)},
               "schedule": {"sha256": _schedule_sha(session, project)}, "format": CONTEXT_FORMAT}
    version = _sha(json.dumps(sources, sort_keys=True).encode())[:12]
    hit = _cache.get(project.id)
    if hit is not None and hit.version == version:
        return hit
    ctx = _build(session, project, json.loads(g_bytes), json.loads(r_bytes), version, sources)
    _cache[project.id] = ctx
    return ctx


def refresh_context(project_id: int | None = None) -> None:
    """Explicit invalidation (admin endpoint / tests). The next get_context rebuilds."""
    if project_id is None:
        _cache.clear()
    else:
        _cache.pop(project_id, None)


def _build(session: Session, project: Project, glossary: dict, rules: dict, version: str, sources: dict) -> ProjectContext:
    no_expand = set(rules["no_expand"])
    expansions = {}
    for k, v in {**glossary["abbreviations"], **glossary["hinglish"]}.items():
        k = k.lower()
        if k in no_expand or "/" in k and k.count("/") > 1 or "(" in k:
            continue
        v = re.sub(r"\([^)]*\)", "", v)
        expansions[k] = " ".join(p.strip() for p in v.split("|"))
        if " " not in k and k.endswith("."):                       # "exc." is also written "exc"
            expansions.setdefault(k.rstrip("."), expansions[k])
    equivalent: dict[str, set[str]] = {}
    for group in rules["equivalent_actions"]:
        for a in group:
            equivalent.setdefault(a, set()).update(set(group) - {a})
    names = session.scalars(select(PlanNode.name).where(PlanNode.project_id == project.id, PlanNode.node_type == "activity")).all()
    rows = session.execute(select(PlanNode.discipline, PlanNode.area).where(PlanNode.project_id == project.id)).all()
    vocab = {w for n in names for w in re.findall(r"[a-z]+", n.lower()) if len(w) >= 4}
    vocab |= {w for ts in rules["actions"].values() for t in ts for w in t.split() if len(w) >= 4}
    vocab |= {w for v in rules["synonyms"].values() for w in v.split()}
    return ProjectContext(
        version=version, sources=sources, project_code=project.code,
        data_date=project.data_date.isoformat() if project.data_date else None, expansions=expansions,
        actions=rules["actions"], equivalent=equivalent, synonyms=rules["synonyms"], novelty=rules["novelty_markers"],
        stopwords=frozenset(rules["stopwords"]), thresholds=rules["thresholds"], vocabulary=frozenset(vocab),
        disciplines=sorted({d for d, _ in rows if d}), areas=sorted({a for _, a in rows if a}))
