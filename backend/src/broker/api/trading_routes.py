"""Manual order control (F3 plumbing, extended for chart-driven manual
trading). The engine drives `order_service` from the trade loop; these
endpoints let the same plumbing be exercised directly from the UI for manual
trades and position management. Market and pending-order *placement* go
through `manual_trade_gate` instead of `order_service` directly, so a manual
order is subject to the same `RiskManager` caps (max open positions, max
trades/day, pause/kill-switch) as an automated one — everything else
(close/modify/list) talks to `order_service` since those aren't gated."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.broker.api.schemas import (
    CloseOrderRequest,
    ExecutionResultOut,
    ModifyOrderRequest,
    ModifyOrderResponse,
    ModifyPendingOrderRequest,
    OpenOrderRequest,
    PendingOrderOut,
    PlacePendingOrderRequest,
    PositionOut,
    SymbolSpreadConfigOut,
    UpdateMinRrIn,
)
from src.broker.domain.account import BrokerUnavailable
from src.broker.domain.trading import (
    ExecutionResult,
    OrderRejected,
    OrderType,
    PendingOrder,
    Position,
    Side,
)
from src.market_data.domain.models import MarketDataUnavailable

router = APIRouter(prefix="/broker", tags=["broker"])

_UNAVAILABLE = {503: {"description": "The MT5 gateway or market data feed is unreachable."}}
_REJECTED = {
    422: {
        "description": (
            "The order was rejected (spread gate, RR gate, risk cap, "
            "engine pause/kill-switch, or broker refusal)."
        )
    }
}


def _service(request: Request) -> Any:
    return request.app.state.container.order_service


def _gate(request: Request) -> Any:
    return request.app.state.container.manual_trade_gate


def _spread_gate(request: Request) -> Any:
    return request.app.state.container.spread_gate


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


def _pending_order_out(order: PendingOrder) -> PendingOrderOut:
    return PendingOrderOut(
        ticket=order.ticket,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        volume=order.volume,
        price=order.price,
        sl=order.sl,
        tp=order.tp,
        placed_time=order.placed_time.isoformat(),
        comment=order.comment,
    )


@router.post(
    "/orders",
    response_model=ExecutionResultOut,
    summary="Open a market order",
    description=(
        "Places a market order through the active broker adapter (paper or live, "
        "per `configs/app.yaml: mode`). Before reaching the broker the order must "
        "clear the account-level risk gate (`configs/risk.yaml`: not paused/killed, "
        "under `max_open_positions` and `max_trades_per_day` — the same caps that "
        "gate automated entries) and the per-symbol spread gate "
        "(`configs/symbols/*.yaml`). `sl`/`tp` are optional; when both are set, "
        "the minimum risk/reward ratio also applies to them. A symbol with no "
        "`configs/symbols/*.yaml` (e.g. one browsed from the broker's catalog "
        "rather than engine-traded) still gets a default RR floor but no spread "
        "cap, rather than being rejected outright. A successful fill is "
        "published as `PositionOpened` on the event bus, which the trade "
        "journal picks up automatically."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def open_order(request: Request, body: OpenOrderRequest) -> ExecutionResultOut:
    try:
        side = Side(body.side)
    except ValueError:
        raise HTTPException(status_code=422, detail="side must be 'buy' or 'sell'") from None
    try:
        result = await _gate(request).open_position(
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


@router.post(
    "/orders/pending",
    response_model=PendingOrderOut,
    summary="Place a pending limit or stop order",
    description=(
        "Places a resting order that fills once price reaches `price`, instead "
        "of immediately. Only the engine's pause/kill-switch state is checked at "
        "placement — `max_open_positions`/`max_trades_per_day` describe open "
        "trades, and a resting order isn't one yet, so those are re-checked when "
        "it actually fills. In paper mode the fill is simulated on each M5 close; "
        "in live mode MT5 triggers it server-side and the backend detects and "
        "journals the fill afterward, publishing `PositionOpened` either way."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def place_pending_order(request: Request, body: PlacePendingOrderRequest) -> PendingOrderOut:
    try:
        side = Side(body.side)
    except ValueError:
        raise HTTPException(status_code=422, detail="side must be 'buy' or 'sell'") from None
    try:
        order_type = OrderType(body.order_type)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="order_type must be 'limit' or 'stop'"
        ) from None
    try:
        result = await _gate(request).place_pending_order(
            body.symbol, side, order_type, body.volume, body.price, body.sl, body.tp, body.comment
        )
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _pending_order_out(result)


@router.get(
    "/orders/pending",
    response_model=list[PendingOrderOut],
    summary="List pending (unfilled) orders",
    description="Returns all resting limit/stop orders, optionally filtered to one symbol.",
    responses=_UNAVAILABLE,
)
async def get_pending_orders(
    request: Request,
    symbol: str | None = Query(default=None, description="Restrict results to this symbol."),
) -> list[PendingOrderOut]:
    try:
        orders = await _service(request).get_pending_orders(symbol)
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_pending_order_out(o) for o in orders]


@router.post(
    "/orders/pending/{ticket}/modify",
    response_model=ModifyOrderResponse,
    summary="Modify a pending order's trigger price, stop loss, or take profit",
    description=(
        "Updates `price`, `sl`, and/or `tp` on a resting order in place; pass "
        "null to leave a field unchanged. Used for dragging a pending order's "
        "trigger/SL/TP lines on the chart."
    ),
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def modify_pending_order(
    request: Request, ticket: int, body: ModifyPendingOrderRequest
) -> ModifyOrderResponse:
    try:
        await _service(request).modify_pending_order(ticket, body.price, body.sl, body.tp)
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ModifyOrderResponse(status="ok")


@router.delete(
    "/orders/pending/{ticket}",
    response_model=ModifyOrderResponse,
    summary="Cancel a pending order",
    description="Removes a resting order before it fills.",
    responses={**_REJECTED, **_UNAVAILABLE},
)
async def cancel_pending_order(request: Request, ticket: int) -> ModifyOrderResponse:
    try:
        await _service(request).cancel_pending_order(ticket)
    except OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BrokerUnavailable, MarketDataUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ModifyOrderResponse(status="ok")


@router.get(
    "/symbols/{symbol}/spread-config",
    response_model=SymbolSpreadConfigOut,
    summary="Get a symbol's live spread/RR gate config",
    description=(
        "Returns the spread cap and minimum RR the running `SpreadGate` is enforcing for "
        "`symbol` right now. Matches `configs/symbols/<symbol>.yaml` on disk unless "
        "`PUT .../min-rr` has been called since the last backend restart."
    ),
    responses={404: {"description": "No spread/RR config for this symbol yet."}},
)
async def get_symbol_spread_config(
    request: Request, symbol: str
) -> SymbolSpreadConfigOut:
    config = _spread_gate(request).get_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"no spread/RR config for {symbol!r}")
    return SymbolSpreadConfigOut(
        symbol=symbol, max_spread_points=config.max_spread_points, min_rr=config.min_rr
    )


@router.put(
    "/symbols/{symbol}/min-rr",
    response_model=SymbolSpreadConfigOut,
    summary="Update a symbol's minimum RR, live",
    description=(
        "Updates, on the running engine, the minimum spread-adjusted reward:risk ratio "
        "`SpreadGate.check()` requires to open a position on `symbol` — the gate a tighter-"
        "stop strategy (e.g. a scalping variant) can fail even with a valid signal, since a "
        "fixed-points spread eats a bigger share of a smaller take-profit. Takes effect on "
        "the very next order for this symbol, live and paper alike. Only `min_rr` changes — "
        "`max_spread_points` and broker facts are untouched. **Not persisted** — a backend "
        "restart reverts to `configs/symbols/<symbol>.yaml`, which the human edits directly "
        "to change the default."
    ),
    responses={404: {"description": "No spread/RR config for this symbol yet."}},
)
async def update_symbol_min_rr(
    request: Request, symbol: str, body: UpdateMinRrIn
) -> SymbolSpreadConfigOut:
    try:
        config = _spread_gate(request).update_min_rr(symbol, body.min_rr)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no spread/RR config for {symbol!r}") from exc
    return SymbolSpreadConfigOut(
        symbol=symbol, max_spread_points=config.max_spread_points, min_rr=config.min_rr
    )
