"""Guard rails around the optional language model: grounding, scope refusal, fallback, budget, remote opt-in."""
from __future__ import annotations

import pytest

from p2e import assistant, llm
from p2e.link import adjudicate


class Fake:
    name = "fake-model"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat(self, messages, max_tokens=None, temperature=0.2):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


FACTS = "3 hold reports: material 2x (spools not delivered); design 1x."


def test_grounded_answer_is_used():
    assert assistant.ai_answer(Fake("குழாய் வேலை 3 முறை நிறுத்தப்பட்டது."), "why?", FACTS, "ta") == "குழாய் வேலை 3 முறை நிறுத்தப்பட்டது."


def test_invented_number_is_rejected():
    assert assistant.ai_answer(Fake("Piping was held 7 times."), "why?", FACTS, "en") is None


def test_out_of_scope_and_failure():
    assert assistant.ai_answer(Fake("OUT_OF_SCOPE"), "write a poem", FACTS, "en") == assistant.OUT_OF_SCOPE
    assert assistant.ai_answer(Fake(llm.LlmError("down")), "why?", FACTS, "en") is None


def test_budget_blocks_runaway_use():
    m = llm.ChatModel("http://localhost:1/v1", "x", per_minute=2, per_day=10)
    m._take_budget(); m._take_budget()
    with pytest.raises(llm.LlmError):
        m._take_budget()


def test_remote_endpoint_needs_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("P2E_LLM_ENDPOINT", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("P2E_LLM_MODEL", "some-model")
    monkeypatch.delenv("P2E_LLM_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError):
        adjudicate.from_env()
    monkeypatch.setenv("P2E_LLM_ALLOW_REMOTE", "1")
    m = adjudicate.from_env()
    assert isinstance(m, llm.ChatModel) and not m.local


def test_prompt_for_browser_model_only_when_asked():
    from datetime import date
    q = "Tell me about Oil India Limited"
    assert "prompt" not in assistant.ask(None, None, q, None, date(2026, 9, 16), "en")
    out = assistant.ask(None, None, q, None, date(2026, 9, 16), "ta", ai=True)
    system, user = out["prompt"]
    assert out["topic"] == "company" and "OUT_OF_SCOPE" in system["content"] and "Tamil" in system["content"]
    assert "<facts>" in user["content"] and q in user["content"]
    poem = assistant.ask(None, None, "Write me a poem about cricket", None, date(2026, 9, 16), "en", ai=True)
    assert poem["topic"] == "out_of_scope" and "prompt" not in poem      # never handed to the browser model
