"""Order execution: open/modify/close positions, list open positions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..mt5_client import Mt5Error, client
from ..schemas import (
    VALID_SIDES,
    CloseRequest,
    ModifyRequest,
    OrderRequest,
    OrderResultOut,
    PositionOut,
)

router = APIRouter()


@router.post("/order", response_model=OrderResultOut)
def order(body: OrderRequest) -> OrderResultOut:
    if body.side not in VALID_SIDES:
        raise HTTPException(status_code=422, detail=f"side must be one of {VALID_SIDES}")
    try:
        return OrderResultOut(
            **client.order_send(body.symbol, body.side, body.volume, body.sl, body.tp, body.comment)
        )
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/positions", response_model=list[PositionOut])
def positions(symbol: str | None = None) -> list[PositionOut]:
    try:
        return [PositionOut(**p) for p in client.positions(symbol)]
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/positions/{ticket}/modify")
def modify_position(ticket: int, body: ModifyRequest) -> dict[str, str]:
    try:
        client.position_modify(ticket, body.sl, body.tp)
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/positions/{ticket}/close", response_model=OrderResultOut)
def close_position(ticket: int, body: CloseRequest | None = None) -> OrderResultOut:
    try:
        return OrderResultOut(**client.position_close(ticket, body.volume if body else None))
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
