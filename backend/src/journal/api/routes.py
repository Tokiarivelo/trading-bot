"""Trade journal endpoints — chart markers + trade history (F7)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from src.journal.api.schemas import TradeHistoryPage, TradeRecordOut
from src.journal.application.trade_journal import TradeJournalService
from src.journal.domain.models import TradeRecord
from src.shared.api.dependencies import AccountRuntimeDep

router = APIRouter(prefix="/accounts/{account_id}/journal", tags=["journal"])


def _service(account: AccountRuntimeDep) -> TradeJournalService:
    return account.trade_journal


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
        "chart range. Pass `skill` (a bot's full id from `GET /skills/normal`, e.g. "
        "'normal/xauusd/breakout_v1') to scope markers to one bot's own trades instead of "
        "every trade (any bot, or manual) on the symbol. Capped to the most recent `limit` "
        "trades by open_time so a long-running chart session doesn't re-fetch the entire "
        "trade history on every poll."
    ),
)
async def get_markers(
    account: AccountRuntimeDep,
    symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'."),
    frm: int | None = Query(
        default=None, alias="from", description="Range start, epoch seconds UTC (inclusive)."
    ),
    to: int | None = Query(default=None, description="Range end, epoch seconds UTC (exclusive)."),
    skill: str | None = Query(
        default=None, description="Scope to one bot's own trades, e.g. 'normal/xauusd/breakout_v1'."
    ),
    limit: int = Query(
        default=1000, ge=1, le=5000, description="Maximum number of most-recent trades to return."
    ),
) -> list[TradeRecordOut]:
    records = await _service(account).get_markers(symbol, frm, to, skill, limit)
    return [_trade_out(r) for r in records]


@router.get(
    "/trades",
    response_model=list[TradeRecordOut],
    summary="Get recent trade history",
    description="Returns the most recent `limit` trades for `symbol`, newest first.",
)
async def get_trades(
    account: AccountRuntimeDep,
    symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'."),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of trades to return."),
) -> list[TradeRecordOut]:
    records = await _service(account).get_last_n(symbol, limit)
    return [_trade_out(r) for r in records]


@router.get(
    "/history",
    response_model=TradeHistoryPage,
    summary="Search and paginate trade history",
    description=(
        "Returns a filtered, paginated page of journaled trades across any symbol. "
        "Unlike `/trades` (single symbol, most-recent-N, no filters), this endpoint "
        "supports filtering by symbol, side, strategy version, skill, outcome, and "
        "open/close time ranges, plus sorting and offset pagination — it backs the "
        "trade history UI's filter and category controls."
    ),
)
async def get_history(
    account: AccountRuntimeDep,
    symbol: str | None = Query(default=None, description="Exact symbol match, e.g. 'XAUUSD'."),
    side: Literal["buy", "sell"] | None = Query(default=None, description="Trade direction."),
    strategy_version: str | None = Query(
        default=None, description="Exact strategy version match, e.g. 'breakout_v1:v1'."
    ),
    skill: str | None = Query(
        default=None, description="Exact bot skill match, e.g. 'normal/xauusd'."
    ),
    outcome: Literal["win", "loss", "breakeven", "open"] | None = Query(
        default=None,
        description=(
            "'open' = not yet closed; 'win'/'loss'/'breakeven' = closed with profit >0 / <0 / ==0."
        ),
    ),
    open_from: int | None = Query(
        default=None, description="Only trades opened at/after this epoch-seconds UTC."
    ),
    open_to: int | None = Query(
        default=None, description="Only trades opened at/before this epoch-seconds UTC."
    ),
    close_from: int | None = Query(
        default=None, description="Only trades closed at/after this epoch-seconds UTC."
    ),
    close_to: int | None = Query(
        default=None, description="Only trades closed at/before this epoch-seconds UTC."
    ),
    order_by: Literal["open_time", "close_time", "profit"] = Query(
        default="open_time", description="Field to sort by."
    ),
    order_dir: Literal["asc", "desc"] = Query(default="desc", description="Sort direction."),
    limit: int = Query(default=50, ge=1, le=500, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Number of matching trades to skip."),
) -> TradeHistoryPage:
    records, total = await _service(account).search_trades(
        symbol=symbol,
        side=side,
        strategy_version=strategy_version,
        skill=skill,
        outcome=outcome,
        open_from=open_from,
        open_to=open_to,
        close_from=close_from,
        close_to=close_to,
        order_by=order_by,
        order_dir=order_dir,
        limit=limit,
        offset=offset,
    )
    return TradeHistoryPage(items=[_trade_out(r) for r in records], total=total)
