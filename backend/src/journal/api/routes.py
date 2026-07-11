"""Trade journal endpoints — chart markers + trade history (F7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from src.journal.api.schemas import TradeRecordOut
from src.journal.domain.models import TradeRecord

router = APIRouter(prefix="/journal", tags=["journal"])


def _service(request: Request) -> Any:
    return request.app.state.container.trade_journal


def _trade_out(record: TradeRecord) -> TradeRecordOut:
    return TradeRecordOut(
        id=record.id,
        symbol=record.symbol,
        side=record.side,
        volume=record.volume,
        open_price=record.open_price,
        open_time=int(record.open_time.timestamp()),
        sl=record.sl,
        tp=record.tp,
        close_price=record.close_price,
        close_time=int(record.close_time.timestamp()) if record.close_time else None,
        profit=record.profit,
        comment=record.comment,
        strategy_version=record.strategy_version,
        skill=record.skill,
    )


@router.get(
    "/markers",
    response_model=list[TradeRecordOut],
    summary="Get trade markers for the chart",
    description=(
        "Returns trades for `symbol` whose open time falls within `[from, to)` "
        "(epoch seconds UTC, both optional). Used to plot entry/exit markers on "
        "the `lightweight-charts` panel — the frontend queries this per visible "
        "chart range."
    ),
)
async def get_markers(
    request: Request,
    symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'."),
    frm: int | None = Query(
        default=None, alias="from", description="Range start, epoch seconds UTC (inclusive)."
    ),
    to: int | None = Query(default=None, description="Range end, epoch seconds UTC (exclusive)."),
) -> list[TradeRecordOut]:
    records = await _service(request).get_markers(symbol, frm, to)
    return [_trade_out(r) for r in records]


@router.get(
    "/trades",
    response_model=list[TradeRecordOut],
    summary="Get recent trade history",
    description="Returns the most recent `limit` trades for `symbol`, newest first.",
)
async def get_trades(
    request: Request,
    symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'."),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of trades to return."),
) -> list[TradeRecordOut]:
    records = await _service(request).get_last_n(symbol, limit)
    return [_trade_out(r) for r in records]
