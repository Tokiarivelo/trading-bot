"""Manual order control (F3 plumbing). The engine drives this service from
the trade loop; these endpoints let the same plumbing be exercised directly
from the UI/tooling for manual trades and position management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.broker.api.schemas import (
    CloseOrderRequest,
    ExecutionResultOut,
    ModifyOrderRequest,
    ModifyOrderResponse,
    OpenOrderRequest,
    PositionOut,
)
from src.broker.domain.account import BrokerUnavailable
from src.broker.domain.trading import ExecutionResult, OrderRejected, Position, Side
from src.market_data.domain.models import MarketDataUnavailable

router = APIRouter(prefix="/broker", tags=["broker"])

_UNAVAILABLE = {503: {"description": "The MT5 gateway or market data feed is unreachable."}}
_REJECTED = {
    422: {"description": "The order was rejected (spread gate, RR gate, or broker refusal)."}
}


def _service(request: Request) -> Any:
    return request.app.state.container.order_service


def _execution_out(result: ExecutionResult) -> ExecutionResultOut:
    return ExecutionResultOut(
        ticket=result.ticket,
        symbol=result.symbol,
        side=result.side.value,
        volume=result.volume,
        price=result.price,
        sl=result.sl,
        tp=result.tp,
        time=result.time.isoformat(),
        spread_points=result.spread_points,
        comment=result.comment,
        profit=result.profit,
    )


def _position_out(position: Position) -> PositionOut:
    return PositionOut(
        ticket=position.ticket,
        symbol=position.symbol,
        side=position.side.value,
        volume=position.volume,
        open_price=position.open_price,
        sl=position.sl,
        tp=position.tp,
        open_time=position.open_time.isoformat(),
        profit=position.profit,
        comment=position.comment,
    )


@router.post(
    "/orders",
    response_model=ExecutionResultOut,
    summary="Open a market order",
    description=(
        "Places a market order through the active broker adapter (paper or live, "
        "per `configs/app.yaml: mode`). Before reaching the broker the order must "
        "clear the per-symbol spread gate and minimum risk/reward ratio "
        "(`configs/symbols/*.yaml`) — both `sl` and `tp` are required for the RR "
        "check to run. A successful fill is published as `PositionOpened` on the "
        "event bus, which the trade journal picks up automatically."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def open_order(request: Request, body: OpenOrderRequest) -> ExecutionResultOut:
    try:
        side = Side(body.side)
    except ValueError:
        raise HTTPException(status_code=422, detail="side must be 'buy' or 'sell'") from None
    try:
        result = await _service(request).open_position(
            body.symbol, side, body.volume, body.sl, body.tp, body.comment
        )
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _execution_out(result)


@router.post(
    "/positions/{ticket}/close",
    response_model=ExecutionResultOut,
    summary="Close an open position",
    description=(
        "Closes the position fully, or partially when `volume` is given. A "
        "successful close is published as `PositionClosed` on the event bus, "
        "which finalizes the journal record and may trigger the ten-trade AI "
        "review."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def close_position(
    request: Request, ticket: int, body: CloseOrderRequest | None = None
) -> ExecutionResultOut:
    try:
        result = await _service(request).close_position(ticket, body.volume if body else None)
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _execution_out(result)


@router.post(
    "/positions/{ticket}/modify",
    response_model=ModifyOrderResponse,
    summary="Modify an open position's stop loss / take profit",
    description=(
        "Updates `sl` and/or `tp` on an existing position in place; pass null to "
        "leave a field unchanged."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def modify_position(
    request: Request, ticket: int, body: ModifyOrderRequest
) -> ModifyOrderResponse:
    try:
        await _service(request).modify_position(ticket, body.sl, body.tp)
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ModifyOrderResponse(status="ok")


@router.get(
    "/positions",
    response_model=list[PositionOut],
    summary="List open positions",
    description="Returns all currently open positions, optionally filtered to one symbol.",
    responses=_UNAVAILABLE,
)
async def get_positions(
    request: Request,
    symbol: str | None = Query(default=None, description="Restrict results to this symbol."),
) -> list[PositionOut]:
    try:
        positions = await _service(request).get_positions(symbol)
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_position_out(p) for p in positions]
