"""BHASHINI speech and translation routes (official Government of India language AI). Keys stay on the server.
Without configuration, /speech/status reports provider "browser" and the web app uses the browser's speech engine."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from p2e.api import schemas as s
from p2e.api.auth import AnyRole
from p2e.integrations import bhashini

router = APIRouter(prefix="/api/v1/speech", tags=["speech (BHASHINI)"])
P = {"model": s.ProblemOut}
ERR = {401: P, 403: P, 422: P, 502: P, 503: P}
Lang = Literal["en", "hi", "ta", "as"]


class AsrIn(BaseModel):
    audio_b64: str = Field(min_length=16, max_length=8_000_000, description="base64 WAV, 16 kHz mono")
    lang: Lang


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    lang: Lang
    gender: Literal["female", "male"] = "female"


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    source: Lang
    target: Lang


def _call(fn, *args):
    try:
        return fn(*args)
    except bhashini.BhashiniError as e:
        raise HTTPException(e.status, e.detail) from None


@router.get("/status")
def speech_status(_: AnyRole) -> dict:
    """Which speech provider is active: "bhashini" (cloud or on-premise) or "browser" (fallback)."""
    return bhashini.status()


@router.post("/asr", responses=ERR)
def speech_asr(body: AsrIn, _: AnyRole) -> dict:
    """Speech to text with BHASHINI ASR."""
    return {"text": _call(bhashini.asr, body.audio_b64, body.lang)}


@router.post("/tts", responses=ERR)
def speech_tts(body: TtsIn, _: AnyRole) -> dict:
    """Text to speech with BHASHINI TTS; returns base64 WAV."""
    return {"audio_b64": _call(bhashini.tts, body.text, body.lang, body.gender), "format": "wav"}


@router.post("/translate", responses=ERR)
def speech_translate(body: TranslateIn, _: AnyRole) -> dict:
    """Translation between English, Hindi, Tamil and Assamese with BHASHINI NMT."""
    return {"text": _call(bhashini.translate, body.text, body.source, body.target)}
