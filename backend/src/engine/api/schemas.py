"""Wire schema for the `/engine` HTTP API. Mirrors `engine/domain/models.EngineStatus`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EngineStatusOut(BaseModel):
    """Current state of the automated trade loop and its circuit breakers."""

    enabled: bool = Field(description="Whether the engine is configured to trade at all.")
    paused: bool = Field(
        description="True after the kill switch or a circuit breaker has fired; no new entries "
        "are taken while paused."
    )
    pause_reason: str = Field(
        default="", description="Why `paused` is true; empty when not paused."
    )
    consecutive_losses: int = Field(
        default=0, description="Current consecutive-loss streak, reset on any win."
    )
    trades_today: int = Field(
        default=0, description="Trades opened since the start of the trading day."
    )
    daily_pnl: float = Field(default=0.0, description="Realized P/L for the current trading day.")


class RiskCapsOut(BaseModel):
    """The live engine's current risk caps — the values `RiskManager` is
    actually enforcing right now, which may differ from `configs/risk.yaml`
    on disk if `PUT /engine/risk-caps/min-lot-fallback` has been called since
    the last restart."""

    risk_per_trade_pct: float = Field(description="% of balance risked per trade, normally.")
    daily_loss_limit_pct: float = Field(
        description="Circuit breaker: pause the engine once today's realized loss reaches this."
    )
    max_open_positions: int = Field(description="Circuit breaker: cap on simultaneous positions.")
    max_trades_per_day: int = Field(description="Circuit breaker: cap on entries per trading day.")
    consecutive_loss_pause: int = Field(
        description="Circuit breaker: pause after this many losing trades in a row."
    )
    min_lot_fallback_enabled: bool = Field(
        description="When true, a balance too small for risk_per_trade_pct to reach the "
        "broker's minimum lot trades that minimum lot anyway, as long as its effective "
        "risk stays under max_risk_per_trade_pct. When false, sizing rejects instead."
    )
    max_risk_per_trade_pct: float | None = Field(
        description="Ceiling (%) for the minimum-lot fallback's effective risk. Null means "
        "the fallback (when enabled) uses risk_per_trade_pct itself as the ceiling."
    )


class UpdateMinLotFallbackIn(BaseModel):
    """Body for `PUT /engine/risk-caps/min-lot-fallback`."""

    enabled: bool = Field(
        description="Turn the broker-minimum-lot fallback on or off for the running engine."
    )
    max_risk_per_trade_pct: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Ceiling (%) for the fallback's effective risk on the minimum lot. "
        "Required to have any effect while enabled=true; null falls back to "
        "risk_per_trade_pct as the ceiling (rarely wide enough to matter).",
    )
