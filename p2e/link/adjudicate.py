"""Optional LLM tie-breaker for REVIEW decisions with several candidates.

Off unless P2E_LLM_ENDPOINT points at a self-hosted text-generation endpoint (e.g. TGI / vLLM on-premise). Confidential
project text is never sent to a public endpoint by accident: a non-private host is refused unless P2E_LLM_ALLOW_REMOTE=1.
The prompt starts with the cached CAG prefix (stable, so the server's prefix cache applies). The model may only answer one
of the candidate codes or NONE; anything else is discarded. The answer is stored as an advisory suggestion for the
planner; it never turns a REVIEW into an automatic match (no model has been validated for that yet).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from urllib.parse import urlparse

from p2e.link.context import ProjectContext
from p2e.link.decide import Scored

MAX_CANDIDATES = 5


def is_private_endpoint(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def from_env():
    """-> a LangChain language model, or None when no endpoint is configured."""
    url = os.environ.get("P2E_LLM_ENDPOINT")
    if not url:
        return None
    if not is_private_endpoint(url) and os.environ.get("P2E_LLM_ALLOW_REMOTE") != "1":
        raise ValueError("P2E_LLM_ENDPOINT is not a private/on-premise host; set P2E_LLM_ALLOW_REMOTE=1 to allow it explicitly")
    from langchain_huggingface import HuggingFaceEndpoint     # imported only when an endpoint is configured
    return HuggingFaceEndpoint(endpoint_url=url, max_new_tokens=128, temperature=0.01, timeout=60)


def build_prompt(ctx: ProjectContext, activity_text: str, source_text: str, ranked: list[Scored]) -> str:
    cands = "\n".join(f"- {s.cand.node.code}: {s.cand.node.name} (area {s.cand.node.area}, score {s.score})" for s in ranked)
    return (ctx.prompt_prefix() +                              # CAG: identical leading text for every call
            f"\nREPORTED: {activity_text}\nSOURCE TEXT: {source_text}\nCANDIDATES:\n{cands}\n"
            'Answer with JSON only: {"choice": "<candidate code or NONE>", "reason": "<one sentence>"}\n')


def adjudicate(model, ctx: ProjectContext, activity_text: str, source_text: str, ranked: list[Scored]) -> dict:
    ranked = ranked[:MAX_CANDIDATES]
    allowed = {s.cand.node.code for s in ranked} | {"NONE"}
    try:
        out = model.invoke(build_prompt(ctx, activity_text, source_text, ranked))
        text = getattr(out, "content", out)
        data = json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0))
        choice, reason = str(data["choice"]).strip(), str(data.get("reason", ""))[:500]
    except Exception as e:                                     # model/network/format failure: no suggestion, decision unchanged
        return {"status": "error", "error": f"{type(e).__name__}: {e}"[:300], "context_version": ctx.version}
    if choice not in allowed:
        return {"status": "rejected", "error": f"answer {choice!r} is not one of the candidates", "context_version": ctx.version}
    return {"status": "ok", "choice": choice, "reason": reason, "context_version": ctx.version}
