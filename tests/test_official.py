"""Official resources: BHASHINI speech/translation (cloud + on-prem AIKosh models, network faked here) and
official-only company facts."""
from __future__ import annotations

import io
import json
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from p2e import assistant
from p2e.integrations import bhashini
from p2e.main import create_app

KEYS = {"planner-key-0123456789ab": "planner"}
H = {"X-API-Key": "planner-key-0123456789ab"}


class FakeUrlopen:
    """Records requests and answers like BHASHINI: config call -> endpoint + serviceId; compute -> pipelineResponse."""
    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        self.calls.append((req.full_url, dict(req.header_items()), body))
        if req.full_url == bhashini.CONFIG_URL:
            out = {"pipelineResponseConfig": [{"config": [{"serviceId": "svc-1"}]}],
                   "pipelineInferenceAPIEndPoint": {"callbackUrl": "https://dhruva.example/infer",
                                                    "inferenceApiKey": {"name": "Authorization", "value": "inf-key"}}}
        else:
            task = body["pipelineTasks"][0]["taskType"]
            out = {"pipelineResponse": [{"asr": {"output": [{"source": "LT-4011 loop check நேற்று முடிந்தது"}]},
                                         "translation": {"output": [{"source": "x", "target": "loop check finished yesterday"}]},
                                         "tts": {"audio": [{"audioContent": "UklGRg=="}]}}[task]]}
        return io.BytesIO(json.dumps(out).encode("utf-8"))


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("BHASHINI_USER_ID", "user-1")
    monkeypatch.setenv("BHASHINI_ULCA_API_KEY", "ulca-key")
    monkeypatch.delenv("BHASHINI_INFERENCE_URL", raising=False)
    bhashini._cache.clear()
    fake = FakeUrlopen()
    monkeypatch.setattr(bhashini.urllib.request, "urlopen", fake)
    return fake


def test_cloud_asr_translate_tts(cloud):
    assert bhashini.status() == {"provider": "bhashini", "mode": "cloud", "languages": ["en", "hi", "ta", "as"]}
    assert bhashini.asr("AAAA" * 8, "ta") == "LT-4011 loop check நேற்று முடிந்தது"
    url, headers, body = cloud.calls[0]
    assert url == bhashini.CONFIG_URL and headers.get("Ulcaapikey") == "ulca-key" and headers.get("Userid") == "user-1"
    assert body["pipelineTasks"][0] == {"taskType": "asr", "config": {"language": {"sourceLanguage": "ta"}}}
    url, headers, body = cloud.calls[1]
    assert url == "https://dhruva.example/infer" and headers.get("Authorization") == "inf-key"
    assert body["pipelineTasks"][0]["config"]["serviceId"] == "svc-1" and body["inputData"]["audio"][0]["audioContent"]
    bhashini.asr("AAAA" * 8, "ta")
    assert len(cloud.calls) == 3                                    # config call cached: only one more compute call
    assert bhashini.translate("x", "as", "en") == "loop check finished yesterday"
    assert bhashini.translate("same", "en", "en") == "same"
    assert bhashini.tts("hello", "as") == "UklGRg=="


def test_on_prem_aikosh_models_skip_the_cloud(monkeypatch):
    monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
    monkeypatch.setenv("BHASHINI_INFERENCE_URL", "http://10.0.0.5:8000/services/inference/pipeline")
    monkeypatch.setenv("BHASHINI_SERVICE_ASR", "ai4bharat/indicconformer")
    monkeypatch.delenv("BHASHINI_SERVICE_TTS", raising=False)
    fake = FakeUrlopen()
    monkeypatch.setattr(bhashini.urllib.request, "urlopen", fake)
    assert bhashini.status()["mode"] == "on-prem"
    assert bhashini.asr("AAAA" * 8, "as")
    assert [c[0] for c in fake.calls] == ["http://10.0.0.5:8000/services/inference/pipeline"]   # never the cloud config
    with pytest.raises(bhashini.BhashiniError) as e:
        bhashini.tts("x", "as")                                      # no TTS service id configured
    assert e.value.status == 503


def test_unconfigured_and_bad_input(monkeypatch):
    for k in ("BHASHINI_USER_ID", "BHASHINI_ULCA_API_KEY", "BHASHINI_API_KEY", "BHASHINI_INFERENCE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert bhashini.status() == {"provider": "browser", "mode": None, "languages": []}
    with pytest.raises(bhashini.BhashiniError) as e:
        bhashini.asr("AAAA", "ta")
    assert e.value.status == 503
    with pytest.raises(bhashini.BhashiniError):
        bhashini._lang("fr")


def test_speech_api(cloud, tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'a.db').as_posix()}", api_keys=dict(KEYS), upload_dir=tmp_path / "up")
    with TestClient(app) as c:
        assert c.get("/api/v1/speech/status").status_code == 401
        assert c.get("/api/v1/speech/status", headers=H).json()["provider"] == "bhashini"
        assert c.post("/api/v1/speech/asr", headers=H, json={"audio_b64": "A" * 32, "lang": "as"}).json()["text"]
        assert c.post("/api/v1/speech/tts", headers=H, json={"text": "hi", "lang": "hi"}).json()["format"] == "wav"
        assert c.post("/api/v1/speech/translate", headers=H, json={"text": "x", "source": "as", "target": "en"}).json()["text"]
        assert c.post("/api/v1/speech/tts", headers=H, json={"text": "hi", "lang": "fr"}).status_code == 422
    app.state.engine.dispose()


def test_company_facts_are_official_only():
    kb = assistant.company()
    allowed = tuple(kb["official_domains"])
    for e in kb["entries"]:
        assert e["sources"], e["id"]
        for s in e["sources"]:
            host = urlparse(s["url"]).hostname
            assert any(host == d or host.endswith("." + d) for d in allowed), (e["id"], host)
    text = json.dumps(kb, ensure_ascii=False).lower()
    assert "glassdoor.com" not in text and "wikipedia.org" not in text


def test_profit_figures_match_the_annual_report():
    fin = next(e for e in assistant.company()["entries"] if e["id"] == "financials")["text"]["en"]
    assert "₹6,114.19 crore standalone and ₹7,039.63 crore consolidated" in fin


# ----------------------------------------------------------------------------- sign-in, demo account, request access

ACCOUNT_KEYS = {"planner-key-0123456789ab": "planner", "admin-key-0123456789abcd": "admin"}


def test_login_demo_and_access_requests(tmp_path, monkeypatch):
    app = create_app(f"sqlite:///{(tmp_path / 'b.db').as_posix()}", api_keys=dict(ACCOUNT_KEYS), upload_dir=tmp_path / "up")
    with TestClient(app) as c:
        ok = c.post("/api/v1/auth/login", json={"username": "Planner", "password": "planner-key-0123456789ab"})
        assert ok.status_code == 200 and ok.json() == {"role": "planner", "token": "planner-key-0123456789ab"}
        assert c.post("/api/v1/auth/login", json={"username": "admin", "password": "planner-key-0123456789ab"}).status_code == 401
        assert c.post("/api/v1/auth/login", json={"username": "planner", "password": "nope"}).status_code == 401
        monkeypatch.delenv("P2E_DEMO_ACCOUNT", raising=False)
        assert c.get("/api/v1/auth/demo").status_code == 404                          # production: no demo account
        monkeypatch.setenv("P2E_DEMO_ACCOUNT", "admin")
        assert c.get("/api/v1/auth/demo").json() == {"username": "admin", "password": "admin-key-0123456789abcd"}
        form = {"name": "R. Gogoi", "email": "r.gogoi@example.in", "organisation": "Oil India Limited",
                "role_requested": "planner", "reason": "Pilot on Area 3"}
        made = c.post("/api/v1/access-requests", json=form)
        assert made.status_code == 201 and made.json()["status"] == "pending"
        assert c.post("/api/v1/access-requests", json=form | {"email": "not-an-email"}).status_code == 422
        assert c.get("/api/v1/access-requests", headers={"X-API-Key": "planner-key-0123456789ab"}).status_code == 403
        rows = c.get("/api/v1/access-requests", headers={"X-API-Key": "admin-key-0123456789abcd"}).json()
        assert rows[0]["email"] == "r.gogoi@example.in" and rows[0]["status"] == "pending"
        admin = {"X-API-Key": "admin-key-0123456789abcd"}
        url = f"/api/v1/access-requests/{rows[0]['id']}"
        assert c.patch(url, json={"status": "approved"}, headers={"X-API-Key": "planner-key-0123456789ab"}).status_code == 403
        assert c.patch(url, json={"status": "maybe"}, headers=admin).status_code == 422
        assert c.patch(url, json={"status": "approved"}, headers=admin).json()["status"] == "approved"
        assert c.patch("/api/v1/access-requests/9999", json={"status": "rejected"}, headers=admin).status_code == 404
    app.state.engine.dispose()
