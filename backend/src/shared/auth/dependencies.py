"""FastAPI dependency guarding every route except `/health` and `/auth/*`.

Mirrors `gateway/src/gateway/security.py`'s shared-secret pattern: if no app
password is configured, the check is skipped (bare local dev). Otherwise a
valid `Authorization: Bearer <token>` session token — issued by
`POST /auth/login` — is required.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

SESSION_TTL_SECONDS = 12 * 3600


def require_session(request: Request, authorization: str = Header(default="")) -> None:
    container = request.app.state.container
    if not container.settings.app_password:
        return
    token = authorization.removeprefix("Bearer ").strip()
    if not container.session_issuer.verify(token, SESSION_TTL_SECONDS):
        raise HTTPException(status_code=401, detail="authentication required")
