"""MT5 account endpoints (F11). Passwords transit request bodies only —
never query strings, never logs, never responses."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.broker.api.schemas import (
    AccountInfoOut,
    AccountStatusOut,
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    DisconnectResponse,
)
from src.broker.application.account_service import AccountService
from src.broker.domain.account import BrokerUnavailable, LoginRejected, Mt5Credentials
from src.shared.api.dependencies import AccountRuntimeDep

router = APIRouter(prefix="/accounts/{account_id}/account", tags=["account"])

_ERROR_RESPONSES = {
    401: {"description": "The broker rejected the login/password/server combination."},
    503: {"description": "The MT5 gateway is unreachable (down or misconfigured)."},
}


def _service(account: AccountRuntimeDep) -> AccountService:
    return account.account


@router.post(
    "/connect",
    response_model=ConnectResponse,
    summary="Log in to MT5",
    description=(
        "Authenticates against the broker through the MT5 gateway. On success the "
        "account snapshot (balance, equity, leverage, ...) is returned; if "
        "`remember` is true the credentials are encrypted and persisted so the "
        "backend can silently reconnect on the next restart (see "
        "`AccountService.reconnect_from_stored`)."
    ),
    responses={401: _ERROR_RESPONSES[401], 503: _ERROR_RESPONSES[503]},
)
async def connect(account: AccountRuntimeDep, body: ConnectRequest) -> ConnectResponse:
    credentials = Mt5Credentials(login=body.login, password=body.password, server=body.server)
    try:
        info = await _service(account).connect(credentials, remember=body.remember)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ConnectResponse(connected=True, account=AccountInfoOut(**info.__dict__))


@router.post(
    "/disconnect",
    response_model=DisconnectResponse,
    summary="Log out of MT5",
    description=(
        "Logs out of the current MT5 session through the gateway. Pass "
        '`{"forget": true}` to also erase any persisted credentials — otherwise '
        "they remain for the next auto-reconnect."
    ),
    responses={503: _ERROR_RESPONSES[503]},
)
async def disconnect(
    account: AccountRuntimeDep, body: DisconnectRequest | None = None
) -> DisconnectResponse:
    try:
        await _service(account).disconnect(forget=body.forget if body else False)
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DisconnectResponse(connected=False)


@router.get(
    "/status",
    response_model=AccountStatusOut,
    summary="Get current MT5 connection status",
    description=(
        "Reports gateway reachability, terminal login state, the live account "
        "snapshot when connected, and whether credentials are on file for "
        "auto-reconnect. Never raises — an unreachable gateway is reported as "
        "`gateway_up: false` rather than an HTTP error, so the UI can poll this "
        "endpoint unconditionally."
    ),
)
async def status(account: AccountRuntimeDep) -> AccountStatusOut:
    return AccountStatusOut(**await _service(account).status())
