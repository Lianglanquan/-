"""Research-side access control.

Participant endpoints intentionally remain token-free. Any endpoint that can
read historical responses, model metrics, review decisions, or full audit
traces must use this dependency.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status

from backend.app.config import load_local_env


def require_research_access(x_research_token: str | None = Header(default=None)) -> str:
    load_local_env()
    expected = os.getenv("RESEARCH_ACCESS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research access is disabled until RESEARCH_ACCESS_TOKEN is configured.",
        )
    if not x_research_token or not secrets.compare_digest(x_research_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid research access token.")
    return "researcher"
