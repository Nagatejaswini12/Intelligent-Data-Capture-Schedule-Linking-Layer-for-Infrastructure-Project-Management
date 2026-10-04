"""BHASHINI (Government of India, MeitY) speech and translation: ASR, TTS and NMT for Indian languages.

Two official modes, both optional (without either, the web app falls back to the browser's speech engine):
  cloud    BHASHINI ULCA: a config call (getModelsPipeline, needs BHASHINI_USER_ID + BHASHINI_ULCA_API_KEY) returns the
           inference endpoint, its key and the serviceId per task/language; the compute call does the work.
  on-prem  a self-hosted BHASHINI/Dhruva-compatible inference endpoint serving the AI4Bharat models published on
           AIKosh (IndiaAI), e.g. IndicConformer (ASR) and IndicTrans2 (NMT): set BHASHINI_INFERENCE_URL (+ key and
           service ids) and no audio or text leaves the company network.
Stdlib only (urllib). Config answers are cached for an hour per (task, languages).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
DEFAULT_PIPELINE = "64392f96daac500b55c543cd"          # MeitY public pipeline
LANGS = ("en", "hi", "ta", "as")                       # what P2E Bridge offers by voice (Assamese for OIL's sites)
CACHE_SECONDS = 3600
TIMEOUT = 30


class BhashiniError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class Settings:
    user_id: str | None
    api_key: str | None
    pipeline_id: str
    inference_url: str | None            # on-prem / fixed endpoint: skips the ULCA config call
    inference_key: str | None
    service_ids: dict                    # on-prem: {"asr": "...", "translation": "...", "tts": "..."}

    @property
    def mode(self) -> str | None:
        if self.inference_url:
            return "on-prem"
        return "cloud" if self.user_id and self.api_key else None


def settings() -> Settings:
    e = os.environ.get
    return Settings(e("BHASHINI_USER_ID"), e("BHASHINI_ULCA_API_KEY") or e("BHASHINI_API_KEY"),
                    e("BHASHINI_PIPELINE_ID") or DEFAULT_PIPELINE, e("BHASHINI_INFERENCE_URL"), e("BHASHINI_INFERENCE_KEY"),
                    {t: e(f"BHASHINI_SERVICE_{t.upper()}") for t in ("asr", "translation", "tts")})


def status() -> dict:
    s = settings()
    return {"provider": "bhashini" if s.mode else "browser", "mode": s.mode, "languages": list(LANGS) if s.mode else []}


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:                      # network, HTTP or JSON error: report, never crash the request
        raise BhashiniError(502, f"BHASHINI request failed: {type(e).__name__}") from None


_cache: dict[tuple, tuple[float, dict]] = {}


def _endpoint(task: str, language: dict) -> dict:
    """-> {"url", "headers", "service_id"} for one task + language pair."""
    s = settings()
    if s.mode is None:
        raise BhashiniError(503, "BHASHINI is not configured (set BHASHINI_USER_ID and BHASHINI_ULCA_API_KEY, "
                                 "or BHASHINI_INFERENCE_URL for an on-premise endpoint)")
    if s.mode == "on-prem":
        if not s.service_ids.get(task):
            raise BhashiniError(503, f"set BHASHINI_SERVICE_{task.upper()} for the on-premise endpoint")
        return {"url": s.inference_url, "headers": {"Authorization": s.inference_key} if s.inference_key else {},
                "service_id": s.service_ids[task]}
    key = (task, tuple(sorted(language.items())))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    cfg = _post(CONFIG_URL, {"pipelineTasks": [{"taskType": task, "config": {"language": language}}],
                             "pipelineRequestConfig": {"pipelineId": s.pipeline_id}},
                {"userID": s.user_id, "ulcaApiKey": s.api_key})
    try:
        api = cfg["pipelineInferenceAPIEndPoint"]
        service_id = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        ep = {"url": api["callbackUrl"], "headers": {api["inferenceApiKey"]["name"]: api["inferenceApiKey"]["value"]},
              "service_id": service_id}
    except (KeyError, IndexError, TypeError):
        raise BhashiniError(502, f"BHASHINI has no {task} model for {language}") from None
    _cache[key] = (time.monotonic(), ep)
    return ep


def _compute(task: str, language: dict, extra: dict, input_data: dict) -> dict:
    ep = _endpoint(task, language)
    out = _post(ep["url"], {"pipelineTasks": [{"taskType": task, "config": {"language": language,
                                                                             "serviceId": ep["service_id"], **extra}}],
                            "inputData": input_data}, ep["headers"])
    try:
        return out["pipelineResponse"][0]
    except (KeyError, IndexError, TypeError):
        raise BhashiniError(502, "unexpected BHASHINI response") from None


def _lang(code: str) -> str:
    if code not in LANGS:
        raise BhashiniError(422, f"language {code!r} not offered (use one of {', '.join(LANGS)})")
    return code


def asr(audio_b64: str, lang: str, audio_format: str = "wav", sampling_rate: int = 16000) -> str:
    r = _compute("asr", {"sourceLanguage": _lang(lang)}, {"audioFormat": audio_format, "samplingRate": sampling_rate},
                 {"audio": [{"audioContent": audio_b64}]})
    return r["output"][0]["source"]


def translate(text: str, source: str, target: str) -> str:
    if source == target:
        return text
    r = _compute("translation", {"sourceLanguage": _lang(source), "targetLanguage": _lang(target)}, {},
                 {"input": [{"source": text}]})
    return r["output"][0]["target"]


def tts(text: str, lang: str, gender: str = "female") -> str:
    r = _compute("tts", {"sourceLanguage": _lang(lang)}, {"gender": gender, "samplingRate": 22050, "audioFormat": "wav"},
                 {"input": [{"source": text}]})
    return r["audio"][0]["audioContent"]
