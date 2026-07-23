"""Market data REST endpoints (chart + tooling). Live streaming is Socket.IO —
see `src.market_data.api.ws`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.market_data.api.schemas import (
    BackfillRequest,
    BackfillResponse,
    BrokerSymbolOut,
    BrokerSymbolPageOut,
    CandleOut,
    SymbolInfoOut,
)
from src.market_data.application.candle_stream import candle_message
from src.market_data.domain.models import MarketDataUnavailable, Timeframe
from src.shared.api.dependencies import AccountRuntimeDep

router = APIRouter(prefix="/accounts/{account_id}/market-data", tags=["market-data"])

TimeframeParam = Annotated[
    Timeframe, Query(description="Bar size: M1, M5, M15, M30, H1, H4, D1, W1, or MN.")
]

_UNAVAILABLE = {503: {"description": "The MT5 gateway is unreachable or not logged in."}}


@router.get(
    "/candles",
    response_model=list[CandleOut],
    summary="Get historical candles",
    description=(
        "Returns up to `count` closed bars for `symbol`/`timeframe`, newest last. "
        "Serves from the live gateway when connected; falls back to the local "
        "database (populated by the background candle stream and `/backfill`) "
        "when the gateway is unreachable, so the chart keeps working across "
        "MT5 disconnects. Pass `before` to page further back than the most "
        "recent `count` bars, e.g. when the chart is panned to the left edge "
        "of its currently loaded history."
    ),
)
async def get_candles(
    account: AccountRuntimeDep,
    symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'."),
    timeframe: TimeframeParam = Timeframe.M5,
    count: Annotated[int, Query(ge=1, le=5000, description="Number of bars to return.")] = 300,
    before: Annotated[
        int | None,
        Query(
            description=(
                "Epoch seconds UTC. When set, returns `count` bars with open "
                "time strictly before this instant instead of the most recent "
                "ones — for loading older history on demand."
            )
        ),
    ] = None,
) -> list[CandleOut]:
    before_dt = datetime.fromtimestamp(before, tz=UTC) if before is not None else None
    candles = await account.candle_history.get_candles(symbol, timeframe, count, before_dt)
    return [CandleOut(**candle_message(c)) for c in candles]


@router.get(
    "/symbol-info",
    response_model=SymbolInfoOut,
    summary="Get live symbol spec",
    description="Live bid/ask, spread, and broker-side volume/price constraints for a symbol.",
    responses=_UNAVAILABLE,
)
async def get_symbol_info(
    account: AccountRuntimeDep, symbol: str = Query(description="Trading symbol, e.g. 'XAUUSD'.")
) -> SymbolInfoOut:
    try:
        info = await account.market_data.get_symbol_info(symbol)
    except MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SymbolInfoOut(
        symbol=info.symbol,
        bid=info.bid,
        ask=info.ask,
        spread_points=info.spread_points,
        point=info.point,
        digits=info.digits,
        stops_level=info.stops_level,
        contract_size=info.contract_size,
        volume_min=info.volume_min,
        volume_max=info.volume_max,
        volume_step=info.volume_step,
    )


@router.get(
    "/broker-symbols",
    response_model=BrokerSymbolPageOut,
    summary="Browse the connected broker's tradable symbols",
    description=(
        "A page of the symbols the broker offers (optionally filtered by a "
        "case-insensitive substring match on name/description), for the chart's "
        "symbol picker — pass `offset` to page through the full catalog when no "
        "`search` is given. This is browsing only — it never modifies "
        "`configs/app.yaml` or `configs/symbols/`, so picking one shows its chart "
        "on demand (including live `candle_closed` WebSocket updates for as long "
        "as a client has it open) but does not add it to the automated engine's "
        "traded universe (currently XAUUSD/XAGUSD/BTCUSD)."
    ),
    responses=_UNAVAILABLE,
)
async def get_broker_symbols(
    account: AccountRuntimeDep,
    search: str | None = Query(
        default=None,
        max_length=64,
        description="Case-insensitive substring match on name/description.",
    ),
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum symbols to return.")] = 200,
    offset: Annotated[
        int, Query(ge=0, description="Number of matching symbols to skip, for paging.")
    ] = 0,
) -> BrokerSymbolPageOut:
    try:
        page = await account.market_data.list_symbols(search, limit, offset)
    except MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return BrokerSymbolPageOut(
        items=[
            BrokerSymbolOut(name=s.name, description=s.description, path=s.path, visible=s.visible)
            for s in page.items
        ],
        total=page.total,
    )


@router.post(
    "/backfill",
    response_model=BackfillResponse,
    summary="Backfill candle history into the local database",
    description=(
        "Fetches bars per symbol/timeframe from the gateway and upserts them "
        "into the local database, so `GET /candles` has data to fall back to "
        "when the gateway later goes offline, and so `POST /backtest/run` has "
        "history to replay. Without `start`, fetches only the most recent "
        "`count` bars. With `start`, pages backward until history reaches "
        "that date — use this before backtesting a multi-month/year period, "
        "since a backtest can only replay candles already in the database. "
        "Safe to call repeatedly — existing bars are overwritten in place, "
        "not duplicated. Also snapshots "
        "each symbol's broker facts (point, digits, stops_level, contract_size, "
        "volume min/max/step) from the gateway's live `symbol_info` into the "
        "`symbol_specs` table — this is what lets `POST /backtest/run` replay "
        "any symbol offline afterward without a hand-authored "
        "`configs/symbols/<symbol>.yaml`."
    ),
    responses=_UNAVAILABLE,
)
async def backfill(account: AccountRuntimeDep, body: BackfillRequest) -> BackfillResponse:
    symbols = body.symbols or account.symbols
    timeframes = body.timeframes or list(Timeframe)
    stored: dict[str, int] = {}
    try:
        for symbol in symbols:
            await account.candle_history.sync_symbol_spec(symbol)
            for timeframe in timeframes:
                bars = await account.candle_history.backfill(
                    symbol, timeframe, body.count, body.start
                )
                stored[f"{symbol}:{timeframe.value}"] = bars
    except MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return BackfillResponse(stored=stored)
