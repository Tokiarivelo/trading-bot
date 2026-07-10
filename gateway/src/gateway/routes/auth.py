"""Login/logout to the MT5 account. Credentials live in terminal memory only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..mt5_client import Mt5Error, client
from ..schemas import AccountInfoOut, LoginRequest

router = APIRouter()


@router.post("/login", response_model=AccountInfoOut)
def login(request: LoginRequest) -> AccountInfoOut:
    try:
        return AccountInfoOut(**client.login(request.login, request.password, request.server))
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/logout")
def logout() -> dict[str, str]:
    client.logout()
    return {"status": "ok"}
