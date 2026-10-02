"""Phase 3: CAG context, RAG retrieval, gated decisions, MAG alias memory, LLM tie-breaker, OKF export, persistence,
idempotency, API and the linking evaluation. Runs on the Phase 0 synthetic project (schedule + 84 field documents)."""
from __future__ import annotations

import io
import json
import shutil
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient
from langchain_core.language_models.fake import FakeListLLM
from sqlalchemy import select

from p2e.db.models import Alias, EventLink, ProgressEvent, Project
from p2e.link import adjudicate, service
from p2e.link.context import RULES_PATH, get_context, refresh_context
from p2e.link.decide import decide
from p2e.link.retrieve import ScheduleIndex, make_query
from p2e.main import create_app
from p2e.memory import okf
from scripts.phase3.evaluate_linking import build_db
from tests.conftest import SYNTH

GLOSSARY = SYNTH / "glossary.json"
KEYS = {"supervisor-key-0123456789": "supervisor", "planner-key-0123456789ab": "planner", "admin-key-0123456789abcd": "admin"}
SUP, PLAN, ADMIN = ({"X-API-Key": k} for k in KEYS)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Fresh DB: schedule imported, all synthetic documents extracted (Phase 2), nothing linked yet."""
    tmp = tmp_path_factory.mktemp("p3")
    refresh_context()
    engine, sm = build_db(SYNTH, tmp)
    yield tmp, sm
    engine.dispose()


@pytest.fixture
def db(world, tmp_path):
    """Per-test copy of the world DB, so tests can confirm/reject without affecting each other."""
    from p2e.db.session import make_engine, make_sessionmaker
    src, _ = world
    shutil.copy(src / "eval.db", tmp_path / "t.db")
    engine = make_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    sm = make_sessionmaker(engine)
    with sm() as session:
        yield session, session.scalar(select(Project))
    engine.dispose()


def ctx_index(session, project):
    ctx = get_context(session, project, GLOSSARY)
    return ctx, ScheduleIndex.build(session, project, ctx)


def run(ctx, index, text, tags=(), area=None, discipline=None, ref=None, unit=None, objects=(), actions=None):
    q = make_query(ctx, text, list(tags), area, discipline, ref or {"line": 1, "index": 0}, unit, actions or {})
    return decide(q, index, ctx, list(objects))


def event_id(session, text):
    return session.scalar(select(ProgressEvent.id).where(ProgressEvent.activity_text == text))


# ----------------------------------------------------------------------------- CAG

def test_context_is_cached_versioned_and_invalidated(db, tmp_path):
    session, project = db
    a = get_context(session, project, GLOSSARY)
    assert get_context(session, project, GLOSSARY) is a                     # cache hit
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules["novelty_markers"].append("snag")
    changed = tmp_path / "rules.json"
    changed.write_text(json.dumps(rules), encoding="utf-8")
    b = get_context(session, project, GLOSSARY, changed)
    assert b.version != a.version and "snag" in b.novelty                    # source change -> new version, rebuilt
    refresh_context(project.id)
    c = get_context(session, project, GLOSSARY)
    assert c is not a and c.version == a.version                             # explicit refresh rebuilds, same sources same version
    d = c.describe()
    assert set(d["sources"]) == {"glossary", "rules", "schedule", "format"} and "progress events" in d["not_cached"]
    assert c.prompt_prefix() == c.prompt_prefix() and c.version in c.prompt_prefix()


def test_normalization_uses_glossary_and_protects_codes(db):
    session, project = db
    ctx, _ = ctx_index(session, project)
    assert "excavation" in ctx.normalize("Exc. for fdn") and "foundation" in ctx.normalize("Exc. for fdn")
    assert "hydrotest" not in ctx.normalize("Erection of HT-SWBD-1 panel")     # code cut before expansion
    assert ctx.actions_in(ctx.normalize("Piping eretcion line 1217")) == {"erection": "erection"}   # typo corrected
    assert "pulling" in ctx.actions_in(ctx.normalize("cable khinchai MCC-2"))                       # Hinglish
    assert ctx.is_novel("Extra PCC at RC-2") == "extra" and ctx.is_novel("PCC at RC-2") is None


# ----------------------------------------------------------------------------- RAG retrieval + decisions

def test_tag_and_action_give_an_explained_match(db):
    session, project = db
    ctx, index = ctx_index(session, project)
    d = run(ctx, index, "LT-4011 tubing ka kaam chalu kiya", tags=["LT-4011"], discipline="instrumentation")
    assert d.decision == "matched" and index.by_code["INS-A4-LT4011-TUB"].id == d.node_id
    top = d.ranked[0]
    assert top.cand.methods == {"tag"} and top.cand.matched_tags == ["LT-4011"] and not d.used_retrieval
    assert any("action tubing" in r for r in top.reasons) and d.margin >= ctx.thresholds["auto_min_margin"]


def test_stage2_retrieval_for_untagged_reports(db):
    session, project = db
    ctx, index = ctx_index(session, project)
    d = run(ctx, index, "Cable tray erection in Area-1", discipline="electrical")
    assert d.used_retrieval and d.decision == "matched" and d.ranked[0].cand.node.code == "ELE-A1-TRY1-TRY"
    assert d.ranked[0].cand.methods & {"lexical", "attribute"} and "tray" in d.ranked[0].cand.matched_terms
    q = make_query(ctx, "Cable tray erection in Area-1", [], None, "electrical", {"line": 1, "index": 0}, None, {})
    assert decide(q, index, ctx, [], retrieval=False).decision == "unmatched"     # deterministic layer alone finds nothing


@pytest.mark.parametrize("text,tags,area,discipline,decision,why", [
    ("GD302 completed", ["GD-302"], None, "hse", "review", "no work action stated"),
    ("P-101A work", ["P-101A"], None, "civil", "review", "no work action stated"),
    ("Base plate grouting P-101A in Area-4", ["P-101A"], "A4", "rotating_eq", "review", "area conflict"),
    ("Foundation works in Area-3", [], "A3", "civil", "review", "no work action stated"),
    ("RCC T-403 fdn", ["T-403"], None, "civil", "unmatched", "not in the schedule"),
    ("Additional shim plates for K-301 skid", ["K-301"], None, "rotating_eq", "unmatched", "additional"),
])
def test_uncertain_reports_are_never_forced(db, text, tags, area, discipline, decision, why):
    session, project = db
    ctx, index = ctx_index(session, project)
    d = run(ctx, index, text, tags=tags, area=area, discipline=discipline)
    assert d.decision == decision and d.node_id is None and any(why in r for r in d.reasons), d.reasons


def test_close_runner_up_goes_to_review(db):
    session, project = db
    ctx, index = ctx_index(session, project)
    d = run(ctx, index, "Shell crs 1-3 T-401", tags=["T-401"], discipline="static_eq")
    assert d.decision == "review" and any("too close" in r for r in d.reasons)


# ----------------------------------------------------------------------------- persistence, idempotency, MAG

def test_link_run_is_idempotent_and_keeps_planner_decisions(db):
    session, project = db
    first = service.link_events(session, project, GLOSSARY)
    session.commit()
    n = sum(first["counts"].values())
    assert n == len(session.scalars(select(ProgressEvent.id).where(ProgressEvent.validation_status == "valid")).all())
    assert service.link_events(session, project, GLOSSARY)["counts"] == {"unchanged": n}
    link = session.scalar(select(EventLink).where(EventLink.decision == "matched"))
    assert link.candidates and link.candidates[0].plan_node_id == link.plan_node_id and link.state == "auto"
    service.reject(session, project, link, "human:planner", GLOSSARY)
    session.commit()
    again = service.link_events(session, project, GLOSSARY)["counts"]
    assert again["kept_planner_decision"] == 1 and session.get(EventLink, link.id).state == "rejected"
    assert not session.scalars(select(Alias)).all()                         # rejection teaches nothing


def test_mag_learns_only_from_confirmations_with_trust_ladder(db):
    session, project = db
    service.link_events(session, project, GLOSSARY)
    session.commit()
    first = service.get_link(session, project, event_id(session, 'erection of 8" fire water ring main'))
    assert first.decision == "review"
    learned = service.confirm(session, project, first, "PIP-A4-1407-ERC", "human:planner", GLOSSARY)
    assert learned["learned"] == [{"kind": "object", "phrase": "fire water main", "target": "LINE-1407"}]
    coarse = service.get_link(session, project, event_id(session, "Foundation works in Area-3"))
    refused = service.confirm(session, project, coarse, "CIV-A3-E101-BKF", "human:planner", GLOSSARY)
    assert not refused["learned"] and "too generic" in refused["skipped"][0]["reason"]      # poisoning guard
    session.commit()
    service.link_events(session, project, GLOSSARY)
    session.commit()
    weld = service.get_link(session, project, event_id(session, 'welding of 8" fire water ring main'))
    assert weld.decision == "review" and weld.candidates[0].node.code == "PIP-A4-1407-WLD"   # alias surfaces the object...
    assert any("confirmed 1x" in r for r in weld.reasons)                                     # ...but once is not enough
    service.confirm(session, project, weld, "PIP-A4-1407-WLD", "human:planner", GLOSSARY)   # same phrase again
    alias = session.scalar(select(Alias).where(Alias.phrase == "fire water main"))
    assert alias.confirmations == 2
    session.commit()
    ctx, index = ctx_index(session, project)
    objects = [(alias.id, alias.phrase, alias.target.split(","), alias.confirmations)]
    d = run(ctx, index, 'hydrotest of 8" fire water ring main', discipline="piping", objects=objects)
    assert d.decision == "matched" and index.by_code["PIP-A4-1407-HT"].id == d.node_id       # generalises to another step
    alias.status = "revoked"
    session.commit()
    assert service.link_events(session, project, GLOSSARY)["mag_version"] == "1-e3b0c44298"    # revoked = not used


def test_conflicting_alias_is_not_overwritten(db):
    session, project = db
    service.link_events(session, project, GLOSSARY)
    service.confirm(session, project, service.get_link(session, project, event_id(session, 'erection of 8" fire water ring main')),
                    "PIP-A4-1407-ERC", "human:planner", GLOSSARY)
    other = service.get_link(session, project, event_id(session, 'welding of 8" fire water ring main'))
    res = service.confirm(session, project, other, "PIP-A3-1217-WLD", "human:planner", GLOSSARY)
    assert "not overwritten" in res["skipped"][0]["reason"]
    assert session.scalar(select(Alias.target).where(Alias.phrase == "fire water main")) == "LINE-1407"
    with pytest.raises(service.LinkError):
        service.confirm(session, project, other, "CGS-EXP-01.A1", "human:planner", GLOSSARY)   # WBS node, not an activity


# ----------------------------------------------------------------------------- LLM tie-breaker (advisory)

def test_llm_tiebreaker_is_constrained_and_advisory(db):
    session, project = db
    ctx, index = ctx_index(session, project)
    d = run(ctx, index, "MCC-1 outgoing feeders work", tags=["MCC-1"], discipline="electrical")
    assert d.decision == "review" and len(d.ranked) >= 2
    code = d.ranked[1].cand.node.code
    ok = adjudicate.adjudicate(FakeListLLM(responses=[json.dumps({"choice": code, "reason": "feeders"})]), ctx, "x", "x", d.ranked)
    assert ok == {"status": "ok", "choice": code, "reason": "feeders", "context_version": ctx.version}
    bad = adjudicate.adjudicate(FakeListLLM(responses=['{"choice": "MADE-UP-1"}']), ctx, "x", "x", d.ranked)
    assert bad["status"] == "rejected"
    junk = adjudicate.adjudicate(FakeListLLM(responses=["no json here"]), ctx, "x", "x", d.ranked)
    assert junk["status"] == "error"
    assert adjudicate.build_prompt(ctx, "x", "x", d.ranked).startswith(ctx.prompt_prefix())   # CAG prefix first
    llm = FakeListLLM(responses=[json.dumps({"choice": "NONE", "reason": "unclear"})] * 500)
    service.link_events(session, project, GLOSSARY, llm=llm)
    reviewed = session.scalars(select(EventLink).where(EventLink.llm_suggestion.is_not(None))).all()
    assert reviewed and all(l.decision == "review" and l.plan_node_id is None for l in reviewed)   # never auto-applied


def test_llm_endpoint_must_be_private(monkeypatch):
    assert adjudicate.is_private_endpoint("http://localhost:8080") and adjudicate.is_private_endpoint("http://10.1.2.3/generate")
    assert not adjudicate.is_private_endpoint("https://api-inference.huggingface.co/models/x")
    monkeypatch.delenv("P2E_LLM_ENDPOINT", raising=False)
    assert adjudicate.from_env() is None
    monkeypatch.setenv("P2E_LLM_ENDPOINT", "https://example.com/generate")
    with pytest.raises(ValueError):
        adjudicate.from_env()


# ----------------------------------------------------------------------------- OKF

def test_okf_bundle_is_conformant_and_honest(db):
    session, project = db
    service.link_events(session, project, GLOSSARY)
    service.confirm(session, project, service.get_link(session, project, event_id(session, 'erection of 8" fire water ring main')),
                    "PIP-A4-1407-ERC", "human:planner", GLOSSARY)
    session.commit()
    files = okf.build_bundle(session, project, get_context(session, project, GLOSSARY))
    assert okf.conformance_problems(files) == []
    assert yaml.safe_load(files["index.md"].split("---")[1]) == {"okf_version": "0.2"}
    assert files["log.md"].startswith("# Directory Update Log") and "## " in files["log.md"]
    alias = yaml.safe_load(files["aliases/object-fire-water-main.md"].split("---")[1])
    assert alias["type"] == "Terminology Alias" and alias["verified"][0]["by"] == "human:planner"
    glossary = yaml.safe_load(files["project/glossary.md"].split("---")[1])
    assert "verified" not in glossary and glossary["generated"]["by"].startswith("p2e-okf-export/")   # not claimed as verified
    family = yaml.safe_load(files["schedule/hydrotest.md"].split("---")[1])
    assert family["stale_after"] > family["generated"]["at"] and family["sources"]
    assert okf.conformance_problems({"x.md": "# no frontmatter"}) == ["x.md: missing frontmatter `type`"]


# ----------------------------------------------------------------------------- API

@pytest.fixture
def api(db, tmp_path):
    session, project = db
    url = session.get_bind().url.render_as_string()
    app = create_app(url, api_keys={k: r for k, r in KEYS.items()}, upload_dir=tmp_path / "up")
    with TestClient(app) as c:
        yield c, f"/api/v1/projects/{project.code}"
    app.state.engine.dispose()


def test_api_linking_flow(api):
    c, base = api
    assert c.post(f"{base}/links/run").status_code == 401
    r = c.post(f"{base}/links/run", headers=SUP)
    assert r.status_code == 200 and r.json()["llm_tiebreaker"] is False and sum(r.json()["counts"].values()) > 400
    review = c.get(f"{base}/links?decision=review&limit=5", headers=SUP).json()
    assert review["total"] > 0 and all(i["state"] == "pending" and i["plan_node_code"] is None for i in review["items"])
    eid = review["items"][0]["event_id"]
    d = c.get(f"{base}/links/{eid}", headers=SUP).json()
    assert d["candidates"] and {"retrieval_methods", "matched_terms", "features", "reasons"} <= set(d["candidates"][0])
    target = d["candidates"][0]["plan_node_code"]
    assert c.post(f"{base}/links/{eid}/confirm", json={"plan_node_code": target}, headers=SUP).status_code == 403
    ok = c.post(f"{base}/links/{eid}/confirm", json={"plan_node_code": target}, headers=PLAN).json()
    assert ok["link"]["state"] == "confirmed" and ok["link"]["plan_node_code"] == target and ok["link"]["decided_by"] == "human:planner"
    assert c.post(f"{base}/links/{eid}/confirm", json={"plan_node_code": "NOPE"}, headers=PLAN).status_code == 422
    assert c.get(f"{base}/links?state=confirmed", headers=SUP).json()["total"] == 1
    assert c.get(f"{base}/links?plan_node_code={target}", headers=SUP).json()["total"] >= 1
    rej = c.post(f"{base}/links/{review['items'][1]['event_id']}/reject", headers=ADMIN).json()
    assert rej["decision"] == "unmatched" and rej["state"] == "rejected"
    assert c.get(f"{base}/links/999999", headers=SUP).status_code == 404
    assert c.get(f"{base}/links?decision=maybe", headers=SUP).status_code == 422


def test_api_context_aliases_and_okf(api):
    c, base = api
    c.post(f"{base}/links/run", headers=SUP)
    ctx = c.get(f"{base}/context", headers=SUP).json()
    assert ctx["version"] and ctx["cached"]["glossary_terms"] > 50
    assert c.post(f"{base}/context/refresh", headers=PLAN).status_code == 403
    assert c.post(f"{base}/context/refresh", headers=ADMIN).json()["version"] == ctx["version"]
    links = c.get(f"{base}/links?decision=review&limit=1000", headers=SUP).json()["items"]
    eid = next(i["event_id"] for i in links if i["activity_text"] == 'erection of 8" fire water ring main')
    c.post(f"{base}/links/{eid}/confirm", json={"plan_node_code": "PIP-A4-1407-ERC"}, headers=PLAN)
    aliases = c.get(f"{base}/aliases", headers=SUP).json()
    assert [a["phrase"] for a in aliases] == ["fire water main"] and aliases[0]["confirmed_by"] == "human:planner"
    assert c.post(f"{base}/aliases/{aliases[0]['id']}/revoke", headers=SUP).status_code == 403
    assert c.post(f"{base}/aliases/{aliases[0]['id']}/revoke", headers=PLAN).json()["status"] == "revoked"
    assert c.get(f"{base}/aliases?status=active", headers=SUP).json() == []
    assert c.get(f"{base}/knowledge/okf.zip", headers=SUP).status_code == 403
    z = c.get(f"{base}/knowledge/okf.zip", headers=PLAN)
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"index.md", "log.md", "project/glossary.md", "aliases/object-fire-water-main.md"} <= set(names)
    assert c.get("/health").status_code == 200 and c.get(f"{base}/events?limit=1", headers=SUP).status_code == 200


# ----------------------------------------------------------------------------- evaluation

def test_linking_evaluation_gates():
    from scripts.phase3.evaluate_linking import evaluate
    rep = evaluate(SYNTH)
    for s in ("dev", "test", "all"):
        r = rep["splits"][s]
        assert r["auto_matched_wrong_activity"] == 0                       # safety gate: never a wrong automatic link
        assert r["outcome_accuracy"] >= 0.85 and r["top3_activity"] >= 0.9 and r["unmatched_precision"] == 1.0
    abl = rep["ablations_test_split"]
    assert abl["full"]["outcome_accuracy"] > abl["without_stage2_retrieval_RAG"]["outcome_accuracy"]
    assert abl["full"]["outcome_accuracy"] > abl["without_glossary_and_synonyms_CAG"]["outcome_accuracy"]
    c = rep["conflicts"]                                                     # Phase 3.1 gate
    assert c["detected"] >= 8 and c["detected_routed_to_review"] == c["detected"] and c["flagged_auto_matched"] == 0
    m = rep["mag_learning_curve"]
    assert m["aliases_learned"] > 0 and m["test_after"]["auto_matched_wrong_activity"] == 0
    assert m["test_after"]["top1_activity"] >= m["test_before"]["top1_activity"]
