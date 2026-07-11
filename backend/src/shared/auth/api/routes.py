"""Login/logout for the single-user app password (§11).

Every other router requires the session this issues (see
`shared/auth/dependencies.py: require_session`, wired per-router in
`src.main`) — this router itself, and `/health`, are the only public routes.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request

from src.shared.auth.api.schemas import (
    AuthStatusOut,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from src.shared.auth.dependencies import SESSION_TTL_SECONDS

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Log in with the shared app password",
    description=(
        "Verifies `password` against `TB_APP_PASSWORD` and issues a session token. "
        "The bot can place live trades, so this guards every other route — see the "
        "`auth` tag description."
    ),
    responses={401: {"description": "Wrong password."}},
)
async def login(request: Request, body: LoginRequest) -> LoginResponse:
    container = request.app.state.container
    configured = container.settings.app_password
    if not configured or not hmac.compare_digest(body.password, configured):
        raise HTTPException(status_code=401, detail="wrong password")
    token = container.session_issuer.issue()
    return LoginResponse(token=token, expires_in_seconds=SESSION_TTL_SECONDS)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Log out",
    description="Stateless — there is no server-side session to revoke, the client "
    "just discards its token. Always returns 200.",
)
async def logout() -> LogoutResponse:
    return LogoutResponse(ok=True)


@router.get(
    "/status",
    response_model=AuthStatusOut,
    summary="Check whether a login is required",
    description="Public (no session needed) — the frontend calls this before deciding "
    "whether to show the login screen.",
)
async def status(request: Request) -> AuthStatusOut:
    return AuthStatusOut(auth_required=bool(request.app.state.container.settings.app_password))
