"""Role API keys (hackathon auth per BACKEND_API.md): header `X-API-Key`, keys supplied via P2E_API_KEYS, never in code.

Fails closed: if no keys are configured, protected endpoints answer 503 instead of becoming public.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

ROLES = ("supervisor", "planner", "admin")
MIN_KEY_LENGTH = 16
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="role API key (supervisor | planner | admin)")


def parse_api_keys(spec: str | None) -> dict[str, str]:
    """'role:key,role:key' -> {key: role}."""
    keys: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in (spec or "").split(","))):
        role, sep, key = part.partition(":")
        if not sep or role not in ROLES or len(key) < MIN_KEY_LENGTH:
            raise ValueError(f"P2E_API_KEYS entries must look like role:key with role in {ROLES} and keys of "
                             f">= {MIN_KEY_LENGTH} characters")
        keys[key] = role
    return keys


def require_role(*allowed: str):
    def dependency(request: Request, key: Annotated[str | None, Depends(api_key_header)]) -> str:
        keys: dict[str, str] = request.app.state.api_keys
        if not keys:
            raise HTTPException(503, "authentication is not configured (set P2E_API_KEYS)")
        role = next((r for k, r in keys.items() if key and hmac.compare_digest(k.encode(), key.encode())), None)
        if role is None:
            raise HTTPException(401, "missing or invalid API key", headers={"WWW-Authenticate": "ApiKey"})
        if role not in allowed:
            raise HTTPException(403, f"role {role!r} may not perform this action")
        return role
    return dependency


AnyRole = Annotated[str, Depends(require_role(*ROLES))]
Uploader = Annotated[str, Depends(require_role("supervisor", "planner", "admin"))]
