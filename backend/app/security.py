"""Authentication and research-side access control dependencies."""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, status

from backend.app.audit.store import AuditStore
from backend.app.auth.mailer import ResendMailer
from backend.app.auth.service import AuthService
from backend.app.config import ROOT, load_local_env, runtime_data_root


SESSION_COOKIE = "qz_session"
_AUDIT = AuditStore(runtime_data_root() / "audit.sqlite3")
_AUTH = AuthService(_AUDIT, mailer=ResendMailer())


def auth_service() -> AuthService:
    return _AUTH


def _session_token(
    authorization: str | None = Header(default=None),
    qz_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return qz_session.strip() if qz_session else None


def optional_current_user(token: str | None = Depends(_session_token)) -> dict[str, Any] | None:
    return _AUTH.current_user(token)


def require_current_user(user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to continue.")
    return user


def require_admin_access(user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return user


def require_research_access(
    x_research_token: str | None = Header(default=None),
    user: dict[str, Any] | None = Depends(optional_current_user),
) -> str:
    """Allow an authenticated administrator, while preserving legacy tokens."""

    if isinstance(user, dict) and user.get("role") == "ADMIN":
        return str(user["id"])
    load_local_env()
    expected = os.getenv("RESEARCH_ACCESS_TOKEN", "").strip()
    if expected and x_research_token and secrets.compare_digest(x_research_token, expected):
        return "researcher"
    if not expected and not user:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research access is disabled until an administrator signs in.",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Administrator access required.")
