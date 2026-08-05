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
    max_trades_per_day_enabled: bool = Field(
        description="Manual daily kill switch — not a count. When true, every new trade is "
        "rejected for the rest of the trading day; when false, entries are unlimited."
    )
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


class UpdateMaxTradesPerDayEnabledIn(BaseModel):
    """Body for `PUT /engine/risk-caps/max-trades-per-day-enabled`."""

    enabled: bool = Field(
        description="Turn the manual daily trading kill switch on or off for the running "
        "engine. True rejects every new trade for the rest of the trading day; false lifts "
        "the block."
    )


class VolatilityConfigOut(BaseModel):
    """The live engine's current volatility-guard config — the values
    `TradeEngine`/`PositionManager` are actually classifying regimes and
    scaling SL/TP/exits with right now. Matches `configs/volatility.yaml`
    on disk except for `enabled`, which reflects any call to
    `PUT /engine/volatility-config/enabled` since the last restart (not a
    field of the YAML file itself)."""

    atr_period: int = Field(description="Lookback period (bars) for the ATR the classifier ranks.")
    regime_lookback_bars: int = Field(
        description="How many trailing ATR readings the current one is percentile-ranked against."
    )
    low_percentile: float = Field(
        description="Percentile rank (0-100) below which the regime is classified LOW."
    )
    high_percentile: float = Field(
        description="Percentile rank (0-100) above which the regime is classified HIGH "
        "(below extreme_percentile) instead of NORMAL."
    )
    extreme_percentile: float = Field(
        description="Percentile rank (0-100) above which the regime is classified EXTREME."
    )
    sl_multiplier_low: float = Field(
        description="SL distance multiplier applied to the strategy's base stop in a LOW regime."
    )
    sl_multiplier_normal: float = Field(
        description="SL distance multiplier applied to the strategy's base stop in a NORMAL regime."
    )
    sl_multiplier_high: float = Field(
        description="SL distance multiplier applied to the strategy's base stop in a HIGH regime."
    )
    tp_multiplier_low: float = Field(
        description="TP distance multiplier applied to the strategy's base target in a LOW regime."
    )
    tp_multiplier_normal: float = Field(
        description="TP distance multiplier applied to the strategy's base target in a NORMAL "
        "regime."
    )
    tp_multiplier_high: float = Field(
        description="TP distance multiplier applied to the strategy's base target in a HIGH regime."
    )
    extreme_close_if_losing: bool = Field(
        description="When true, a position open and losing is closed immediately once the "
        "regime flips to EXTREME, instead of waiting for SL."
    )
    extreme_profit_lock_r_mult: float = Field(
        description="When the regime flips to EXTREME while a position is winning, the fraction "
        "of its current unrealized R-multiple locked in by moving the stop."
    )
    chandelier_atr_mult: float = Field(
        description="Chandelier-exit trailing stop: how many ATRs behind the best favorable "
        "price reached since entry the stop trails, once eligible."
    )
    chandelier_min_profit_r: float = Field(
        description="Minimum unrealized profit, in R-multiples, before the chandelier trailing "
        "stop becomes eligible."
    )
    enabled: bool = Field(
        description="Live on/off switch for the whole volatility guard — the EXTREME entry "
        "block and SL/TP regime scaling in the trade loop, plus the EXTREME/HIGH "
        "position-management rules. When false, both behave exactly as if no "
        "volatility_config were supplied at all."
    )


class UpdateVolatilityGuardEnabledIn(BaseModel):
    """Body for `PUT /engine/volatility-config/enabled`."""

    enabled: bool = Field(
        description="Turn the volatility guard on or off for the running engine — the EXTREME "
        "entry block/SL-TP scaling in the trade loop and the EXTREME/HIGH "
        "position-management rules move together as one feature."
    )


class UpdateCoreRiskCapsIn(BaseModel):
    """Body for `PUT /engine/risk-caps/core`. Every field is optional and
    independent — send only the ones you want to change; omitted fields
    (or explicit null) leave that cap untouched. Unlike the per-account
    `risk_override_file` mechanism, this may loosen or tighten freely: it's
    the account owner adjusting their own caps, not an automated override."""

    risk_per_trade_pct: float | None = Field(
        default=None, gt=0, le=100, description="% of balance risked per trade, normally."
    )
    daily_loss_limit_pct: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Circuit breaker: pause the engine once today's realized loss reaches "
        "this.",
    )
    max_open_positions: int | None = Field(
        default=None, gt=0, description="Circuit breaker: cap on simultaneous positions."
    )
    consecutive_loss_pause: int | None = Field(
        default=None,
        gt=0,
        description="Circuit breaker: pause after this many losing trades in a row.",
    )
