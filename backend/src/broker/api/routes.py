"""MT5 account endpoints (F11). Passwords transit request bodies only —
never query strings, never logs, never responses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.broker.domain.account import BrokerUnavailable, LoginRejected, Mt5Credentials

router = APIRouter(prefix="/account", tags=["account"])


class ConnectRequest(BaseModel):
    login: int
    password: str = Field(min_length=1)
    server: str = Field(min_length=1)
    remember: bool = True


def _service(request: Request) -> Any:
    return request.app.state.container.account


@router.post("/connect")
async def connect(request: Request, body: ConnectRequest) -> dict:
    credentials = Mt5Credentials(login=body.login, password=body.password, server=body.server)
    try:
        info = await _service(request).connect(credentials, remember=body.remember)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": True, "account": info.__dict__}


class DisconnectRequest(BaseModel):
    forget: bool = False


@router.post("/disconnect")
async def disconnect(request: Request, body: DisconnectRequest | None = None) -> dict:
    try:
        await _service(request).disconnect(forget=body.forget if body else False)
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": False}


@router.get("/status")
async def status(request: Request) -> dict:
    return await _service(request).status()
