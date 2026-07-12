"""Wire schema for the `/journal` HTTP API. Mirrors `journal/domain/models.py`
minus the market-context candle snapshots, which are AI-review-only and never
serialized over this API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TradeRecordOut(BaseModel):
    """One journaled trade — used both as a chart marker (`/markers`) and in
    the trade history list (`/trades`)."""

    id: str = Field(description="Broker position ticket, as a string.")
    symbol: str
    side: str = Field(description="'buy' or 'sell'.")
    volume: float
    open_price: float
    open_time: int = Field(description="Epoch seconds UTC.")
    sl: float | None
    tp: float | None
    close_price: float | None = Field(default=None, description="Null while the trade is open.")
    close_time: int | None = Field(
        default=None, description="Epoch seconds UTC; null while the trade is open."
    )
    profit: float | None = Field(default=None, description="Realized P/L; null while open.")
    comment: str = ""
    strategy_version: str | None = Field(
        default=None, description="e.g. 'breakout_v1:v1'; null for manually placed trades."
    )
    skill: str | None = Field(
        default=None, description="Bot skill that selected this trade, e.g. 'normal/xauusd'."
    )


class TradeHistoryPage(BaseModel):
    """One page of the filtered trade history (`GET /journal/history`)."""

    items: list[TradeRecordOut] = Field(description="Trades matching the filters, one page.")
    total: int = Field(
        description="Total number of trades matching the filters, across all pages."
    )
