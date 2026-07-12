"""Order execution: open/modify/close positions, list open positions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..mt5_client import Mt5Error, client
from ..schemas import (
    VALID_ORDER_TYPES,
    VALID_SIDES,
    CloseRequest,
    ModifyPendingOrderRequest,
    ModifyRequest,
    OrderRequest,
    OrderResultOut,
    PendingOrderOut,
    PendingOrderRequest,
    PositionCloseInfoOut,
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


@router.get("/positions/{ticket}/history", response_model=PositionCloseInfoOut)
def position_history(ticket: int) -> PositionCloseInfoOut:
    try:
        info = client.position_close_info(ticket)
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if info is None:
        raise HTTPException(status_code=404, detail=f"no close history for ticket {ticket}")
    return PositionCloseInfoOut(**info)


@router.post("/orders/pending", response_model=PendingOrderOut)
def place_pending_order(body: PendingOrderRequest) -> PendingOrderOut:
    if body.side not in VALID_SIDES:
        raise HTTPException(status_code=422, detail=f"side must be one of {VALID_SIDES}")
    if body.order_type not in VALID_ORDER_TYPES:
        raise HTTPException(
            status_code=422, detail=f"order_type must be one of {VALID_ORDER_TYPES}"
        )
    try:
        return PendingOrderOut(
            **client.place_pending_order(
                body.symbol,
                body.side,
                body.order_type,
                body.volume,
                body.price,
                body.sl,
                body.tp,
                body.comment,
            )
        )
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/orders/pending", response_model=list[PendingOrderOut])
def pending_orders(symbol: str | None = None) -> list[PendingOrderOut]:
    try:
        return [PendingOrderOut(**o) for o in client.pending_orders(symbol)]
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/orders/pending/{ticket}/modify")
def modify_pending_order(ticket: int, body: ModifyPendingOrderRequest) -> dict[str, str]:
    try:
        client.modify_pending_order(ticket, body.price, body.sl, body.tp)
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok"}


@router.delete("/orders/pending/{ticket}")
def cancel_pending_order(ticket: int) -> dict[str, str]:
    try:
        client.cancel_pending_order(ticket)
    except Mt5Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok"}
