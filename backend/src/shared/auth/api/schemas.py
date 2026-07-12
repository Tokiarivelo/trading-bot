"""Wire schema for the `/auth` HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str = Field(description="The shared app password (`TB_APP_PASSWORD`).")


class LoginResponse(BaseModel):
    token: str = Field(
        description="Session token — send as `Authorization: Bearer <token>` on every "
        "other request, and as `{token}` in the Socket.IO `auth` handshake payload."
    )
    expires_in_seconds: int = Field(description="How long the token stays valid.")


class LogoutResponse(BaseModel):
    ok: bool = Field(
        description="Always true; logout is stateless — the client just discards the token."
    )


class AuthStatusOut(BaseModel):
    auth_required: bool = Field(
        description="Whether `TB_APP_PASSWORD` is set. When false, every route is open "
        "(bare local dev) and the frontend should skip the login screen."
    )
