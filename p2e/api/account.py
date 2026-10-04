"""Sign-in with username + password, the evaluator demo account, and sign-up as a request for access.

Username = role (supervisor | planner | admin), password = that role's access key from P2E_API_KEYS, so security is the
same as the key header. The demo account is offered only when P2E_DEMO_ACCOUNT names a role that has a key (demo
deployments such as start_demo.bat); production leaves it unset and /auth/demo answers 404.
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from p2e.api import schemas as s
from p2e.api.auth import ROLES, require_role
from p2e.api.routes import SessionDep
from p2e.db.models import AccessRequest

router = APIRouter(prefix="/api/v1", tags=["account"])
P = {"model": s.ProblemOut}
Admin = Annotated[str, Depends(require_role("admin"))]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class AccessIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    organisation: str = Field(min_length=2, max_length=200)
    role_requested: Literal["supervisor", "planner", "admin"]
    reason: str = Field("", max_length=1000)


class AccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    organisation: str
    role_requested: str
    reason: str
    status: str
    created_at: datetime


@router.post("/auth/login", responses={401: P, 503: P})
def login(body: LoginIn, request: Request) -> dict:
    """Username (role) + password (that role's key) -> the key to send as X-API-Key."""
    keys: dict[str, str] = request.app.state.api_keys
    if not keys:
        raise HTTPException(503, "authentication is not configured (set P2E_API_KEYS)")
    role = next((r for k, r in keys.items() if hmac.compare_digest(k.encode(), body.password.encode())), None)
    if role is None or role.partition("@")[0] != body.username.strip().lower().partition("@")[0]:
        raise HTTPException(401, "wrong username or password")
    return {"role": role, "token": body.password}


@router.get("/auth/demo", responses={404: P})
def demo_account(request: Request) -> dict:
    """Evaluator demo credentials, only on demo deployments (P2E_DEMO_ACCOUNT=planner|admin|supervisor)."""
    want = (os.environ.get("P2E_DEMO_ACCOUNT") or "").strip().lower()
    key = next((k for k, r in request.app.state.api_keys.items() if r == want), None) if want in ROLES else None
    if key is None:
        raise HTTPException(404, "no demo account on this deployment")
    return {"username": want, "password": key}


@router.post("/access-requests", status_code=201, responses={422: P})
def request_access(body: AccessIn, session: SessionDep) -> dict:
    """Public sign-up form: stores the request for an administrator to review; no key is issued automatically."""
    req = AccessRequest(name=body.name.strip(), email=body.email.strip(), organisation=body.organisation.strip(),
                        role_requested=body.role_requested, reason=body.reason.strip())
    session.add(req)
    session.commit()
    return {"id": req.id, "status": req.status}


@router.get("/access-requests", response_model=list[AccessOut], responses={401: P, 403: P})
def list_access_requests(session: SessionDep, _: Admin) -> list:
    """Admin: review pending access requests (newest first)."""
    return list(session.scalars(select(AccessRequest).order_by(AccessRequest.id.desc())))


class DecideIn(BaseModel):
    status: Literal["approved", "rejected"]


@router.patch("/access-requests/{request_id}", response_model=AccessOut, responses={401: P, 403: P, 404: P})
def decide_access_request(request_id: int, body: DecideIn, session: SessionDep, _: Admin) -> AccessRequest:
    """Admin: approve or reject. Approval only records the decision; the role key is still issued out of band."""
    req = session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(404, "access request not found")
    req.status = body.status
    session.commit()
    return req
