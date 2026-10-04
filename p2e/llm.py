"""Chat model over any OpenAI-compatible endpoint (stdlib only).

Default and recommended: a local model (Ollama / LM Studio / vLLM on the company network), e.g.
    P2E_LLM_ENDPOINT=http://localhost:11434/v1   P2E_LLM_MODEL=qwen3.5:4b
A cloud provider (e.g. Groq, https://api.groq.com/openai/v1) is refused unless P2E_LLM_ALLOW_REMOTE=1, and its key is read
only from P2E_LLM_API_KEY (never stored in the repository).

Guardrails against misuse and runaway cost: a per-minute and a per-day call budget (P2E_LLM_PER_MINUTE, P2E_LLM_PER_DAY),
a hard output-token cap, a request timeout, and "thinking" switched off on local models. When a budget is spent or the
endpoint fails, callers fall back to the deterministic answer; nothing in the application depends on the model.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from collections import deque

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LlmError(Exception):
    pass


class ChatModel:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, *, local: bool = True, timeout: float = 90,
                 max_tokens: int = 400, per_minute: int = 20, per_day: int = 1000):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key, self.local, self.timeout, self.max_tokens = model, api_key, local, timeout, max_tokens
        self.per_minute, self.per_day = per_minute, per_day
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.model

    def _take_budget(self):
        now = time.time()
        with self._lock:
            while self._calls and now - self._calls[0] > 86400:
                self._calls.popleft()
            if len(self._calls) >= self.per_day or sum(now - t < 60 for t in self._calls) >= self.per_minute:
                raise LlmError("AI budget reached; answering without the model")
            self._calls.append(now)

    def chat(self, messages: list[dict], max_tokens: int | None = None, temperature: float = 0.2) -> str:
        self._take_budget()
        body = {"model": self.model, "messages": messages, "temperature": temperature,
                "max_tokens": min(max_tokens or self.max_tokens, self.max_tokens), "stream": False}
        if self.local:
            body["reasoning_effort"] = "none"            # Qwen 3.x: no hidden reasoning, much faster on small GPUs
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, json.dumps(body).encode("utf-8"), headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read().decode("utf-8"))
            text = out["choices"][0]["message"]["content"] or ""
        except Exception as e:                           # network, HTTP, format: the caller falls back
            raise LlmError(f"{type(e).__name__}: {e}"[:300]) from None
        return THINK_RE.sub("", text).strip()

    def invoke(self, prompt: str) -> str:                # the interface the linker tie-breaker and Time Agent use
        return self.chat([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.0)


def from_env(is_private) -> ChatModel | None:
    url, model = os.environ.get("P2E_LLM_ENDPOINT"), os.environ.get("P2E_LLM_MODEL")
    if not url or not model:
        return None
    local = is_private(url)
    if not local and os.environ.get("P2E_LLM_ALLOW_REMOTE") != "1":
        raise ValueError("P2E_LLM_ENDPOINT is not a private/on-premise host; set P2E_LLM_ALLOW_REMOTE=1 to allow it explicitly")
    return ChatModel(url, model, os.environ.get("P2E_LLM_API_KEY"), local=local,
                     per_minute=int(os.environ.get("P2E_LLM_PER_MINUTE", "20")),
                     per_day=int(os.environ.get("P2E_LLM_PER_DAY", "1000")))
