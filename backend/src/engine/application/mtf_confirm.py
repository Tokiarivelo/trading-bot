"""Higher-timeframe confirmation (§7.1): a signal is only taken if the
confirmation timeframes' trend agrees with its direction.

Trend is EMA(fast) vs EMA(slow) on closes — a lightweight proxy for
"EMA200 slope / structure" from the plan. A true 200-period read needs
~8+ days of H1 history the engine won't have right after Phase 1 backfill,
so confirmation is skipped (not vetoed) until a timeframe has enough bars —
otherwise the bot could never take a single trade until history fills in.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.domain.models import Direction, MarketContext

DEFAULT_FAST_PERIOD = 20
DEFAULT_SLOW_PERIOD = 50


def confirm(
    direction: Direction,
    ctx: MarketContext,
    confirmation_timeframes: tuple[str, ...],
    fast_period: int = DEFAULT_FAST_PERIOD,
    slow_period: int = DEFAULT_SLOW_PERIOD,
) -> tuple[bool, str]:
    """Returns (confirmed, reason). `reason` explains a veto, or is empty."""
    for timeframe in confirmation_timeframes:
        frame: pd.DataFrame | None = ctx.candles.get(timeframe)
        if frame is None or len(frame) < slow_period + 1:
            continue  # insufficient history — don't block on it
        trend = _trend(frame, fast_period, slow_period)
        if trend == "flat":
            continue
        if (trend == "up" and direction is Direction.SELL) or (
            trend == "down" and direction is Direction.BUY
        ):
            return False, f"{timeframe} trend ({trend}) opposes {direction.value} signal"
    return True, ""


def _trend(frame: pd.DataFrame, fast_period: int, slow_period: int) -> str:
    fast_ema = frame["close"].ewm(span=fast_period, adjust=False).mean().iloc[-1]
    slow_ema = frame["close"].ewm(span=slow_period, adjust=False).mean().iloc[-1]
    if fast_ema > slow_ema:
        return "up"
    if fast_ema < slow_ema:
        return "down"
    return "flat"
