"""Wire schemas for the `/market-data` HTTP API.

Mirrors `market_data/domain/models.py`. Candle/tick times are always epoch
seconds UTC on the wire (matching MT5 and `lightweight-charts` conventions) —
see `application/candle_stream.py:candle_message` for the REST/WS shared shape.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.market_data.domain.models import Timeframe


class CandleOut(BaseModel):
    """One OHLC bar. Identical shape over REST (`GET /candles`) and the
    `candle_closed` Socket.IO event."""

    symbol: str
    timeframe: str = Field(
        description="One of 'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN'."
    )
    time: int = Field(description="Bar open time, epoch seconds UTC.")
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = Field(description="Number of ticks during the bar.")
    spread_points: int = Field(description="Spread in points, as recorded on the bar.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "time": 1_732_000_800,
                "open": 2400.12,
                "high": 2401.50,
                "low": 2399.80,
                "close": 2400.90,
                "tick_volume": 842,
                "spread_points": 25,
            }
        }
    }


class SymbolInfoOut(BaseModel):
    """Live tradable-instrument spec, as reported by the broker terminal."""

    symbol: str
    bid: float
    ask: float
    spread_points: int = Field(description="Live spread in points.")
    point: float = Field(description="Smallest price increment for this symbol.")
    digits: int = Field(description="Number of decimal digits in the quoted price.")
    stops_level: int = Field(description="Broker's minimum SL/TP distance, in points.")
    contract_size: float
    volume_min: float = Field(description="Minimum order volume in lots.")
    volume_max: float = Field(description="Maximum order volume in lots.")
    volume_step: float = Field(description="Volume increment step in lots.")


class BrokerSymbolOut(BaseModel):
    """One entry in the broker's tradable-symbol catalog — for browsing/
    charting only. Adding one to the chart does not configure it for the
    automated engine; that's a separate, deliberate step (`configs/app.yaml:
    symbols` + `configs/symbols/<sym>.yaml`, currently XAUUSD/XAGUSD/BTCUSD)."""

    name: str
    description: str = Field(description="Broker's human-readable name for the instrument.")
    path: str = Field(description="Broker's Market Watch group, e.g. 'Forex\\\\Majors'.")
    visible: bool = Field(description="Whether the symbol is already in Market Watch.")


class BrokerSymbolPageOut(BaseModel):
    """One page of the broker's symbol catalog, for paging through the full
    list in the chart's symbol picker (as well as filtering it by `search`)."""

    items: list[BrokerSymbolOut]
    total: int = Field(
        description=(
            "Count of symbols matching `search` (or the full catalog if unset), "
            "before `limit`/`offset` are applied — use it to know whether more "
            "pages remain."
        )
    )


class BackfillRequest(BaseModel):
    symbols: list[str] | None = Field(
        default=None, description="Symbols to backfill; defaults to `configs/app.yaml: symbols`."
    )
    timeframes: list[Timeframe] | None = Field(
        default=None,
        description="Timeframes to backfill; defaults to all of M1/M5/M15/M30/H1/H4/D1/W1/MN.",
    )
    count: int = Field(
        default=1000,
        ge=1,
        le=5000,
        description=(
            "Number of bars per symbol/timeframe. Without `start`, this is the "
            "total fetched (most recent bars). With `start`, this is the page "
            "size used while paging backward — a single gateway call is capped "
            "at 5000 bars."
        ),
    )
    start: datetime | None = Field(
        default=None,
        description=(
            "If set, pages backward from now in `count`-sized chunks until "
            "candle history reaches this date (or the broker's history runs "
            "out), instead of only fetching the most recent `count` bars — use "
            "this to seed a full date range (e.g. a year of M5 bars) for "
            "`POST /backtest/run`. Can take a while for a large range/fine "
            "timeframe combination."
        ),
    )


class BackfillResponse(BaseModel):
    stored: dict[str, int] = Field(
        description="Bars written per '<symbol>:<timeframe>' key, e.g. {'XAUUSD:M5': 1000}."
    )
