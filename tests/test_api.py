"""API tests against a database imported from the Phase 0 schedule."""
from __future__ import annotations

from tests.conftest import MANIFEST

P = "/api/v1/projects/CGS-EXP-01"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] == "ok"


def test_projects(client):
    assert [p["code"] for p in client.get("/api/v1/projects").json()] == ["CGS-EXP-01"]
    p = client.get(P).json()
    assert p["data_date"] == "2026-08-31" and p["timezone"] == "Asia/Kolkata"
    assert p["schedule_sources"][0]["node_count"] == 469


def test_unknown_project_is_404_problem(client):
    r = client.get("/api/v1/projects/NOPE/summary")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Not Found"


def test_schedule_summary(client):
    s = client.get(f"{P}/summary").json()
    assert (s["total_nodes"], s["executable_activities"]) == (469, 317)
    assert s["activities_by_discipline"] == MANIFEST["stats"]["activities_by_discipline"]
    assert s["activities_by_level"] == {"5": 302, "6": 15}
    assert s["nodes_by_level"]["1"] == 1 and sum(s["nodes_by_level"].values()) == 469
    assert (s["planned_start"], s["planned_finish"]) == ("2026-07-10", "2026-10-21")


def test_list_and_filters(client):
    page = client.get(f"{P}/plan").json()
    assert page["total"] == 469 and len(page["items"]) == 100 and page["items"][0]["code"] == "CGS-EXP-01"
    assert client.get(f"{P}/plan", params={"executable": True}).json()["total"] == 317
    assert client.get(f"{P}/plan", params={"executable": False}).json()["total"] == 152
    piping = client.get(f"{P}/plan", params={"executable": True, "discipline": "piping", "limit": 1000}).json()
    assert piping["total"] == 76 and {i["discipline"] for i in piping["items"]} == {"piping"}
    assert all(i["is_executable"] for i in piping["items"])
    assert client.get(f"{P}/plan", params={"level": 6}).json()["total"] == 15
    assert client.get(f"{P}/plan", params={"level": 4, "executable": True}).json()["total"] == 0
    assert client.get(f"{P}/plan", params={"node_type": "summary"}).json()["total"] == 3


def test_text_and_tag_lookup(client):
    ht = client.get(f"{P}/plan", params={"q": "hydrotest", "executable": True}).json()
    assert ht["total"] == 19 and all("hydrotest" in i["name"].lower() for i in ht["items"])   # 17 lines + 2 tanks
    assert client.get(f"{P}/plan", params={"q": "%"}).json()["total"] == 0                   # literal, not a wildcard
    codes = {i["code"] for i in client.get(f"{P}/plan", params={"tag": "line-1203"}).json()["items"]}
    assert codes == {"PIP-A3-1203-ERC", "PIP-A3-1203-WLD", "PIP-A3-1203-HT", "PIP-A3-1203-RST"}


def test_pagination(client):
    a = client.get(f"{P}/plan", params={"executable": True, "limit": 10}).json()["items"]
    b = client.get(f"{P}/plan", params={"executable": True, "limit": 10, "offset": 10}).json()["items"]
    assert len(a) == len(b) == 10 and not {i["code"] for i in a} & {i["code"] for i in b}


def test_invalid_query_params_are_422(client):
    for params in ({"discipline": "plumbing"}, {"level": 9}, {"limit": 5000}, {"node_type": "task"}):
        r = client.get(f"{P}/plan", params=params)
        assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")


def test_activity_by_id(client):
    a = client.get(f"{P}/plan/PIP-A3-1203-HT").json()
    assert a["name"] == 'Hydrotest line 24"-P-1203-A1A (TP-017)'
    assert (a["node_type"], a["level"], a["discipline"], a["area"]) == ("activity", 5, "piping", "A3")
    assert a["tags"] == ["LINE-1203", "TP-017"]
    assert [x["code"] for x in a["ancestors"]] == ["CGS-EXP-01", "CGS-EXP-01.A3", "CGS-EXP-01.A3.PIP", "CGS-EXP-01.A3.PIP.1203"]
    assert a["children"] == [] and a["parent_code"] == "CGS-EXP-01.A3.PIP.1203"
    assert a["predecessors"] == [{"code": "PIP-A3-1203-WLD", "link_type": "FS", "lag_days": 3}]
    assert a["successors"] == [{"code": "PIP-A3-1203-RST", "link_type": "FS", "lag_days": 1}]


def test_l6_activity_and_wbs_node(client):
    l6 = client.get(f"{P}/plan/SEQ-A4-T401-SH1").json()
    assert l6["level"] == 6 and l6["ancestors"][-1]["node_type"] == "summary"
    wbs = client.get(f"{P}/plan/CGS-EXP-01.A3.PIP.1203").json()
    assert wbs["is_executable"] is False and len(wbs["children"]) == 4


def test_unknown_activity_is_404(client):
    r = client.get(f"{P}/plan/PIP-A3-9999-HT")
    assert r.status_code == 404 and "PIP-A3-9999-HT" in r.json()["detail"]


def test_hierarchy(client):
    tree = client.get(f"{P}/hierarchy").json()

    def walk(n):
        return 1 + sum(walk(c) for c in n["children"])

    assert tree["code"] == "CGS-EXP-01" and walk(tree) == 469
    assert [c["code"] for c in tree["children"]] == ["CGS-EXP-01.A1", "CGS-EXP-01.A2", "CGS-EXP-01.A3", "CGS-EXP-01.A4"]
    shallow = client.get(f"{P}/hierarchy", params={"depth": 1}).json()
    assert all(c["children"] == [] and c["child_count"] > 0 for c in shallow["children"])
    sub = client.get(f"{P}/hierarchy", params={"root": "CGS-EXP-01.A3.PIP.1203"}).json()
    assert [c["code"] for c in sub["children"]] == ["PIP-A3-1203-ERC", "PIP-A3-1203-WLD", "PIP-A3-1203-HT", "PIP-A3-1203-RST"]
    assert client.get(f"{P}/hierarchy", params={"root": "NOPE"}).status_code == 404
