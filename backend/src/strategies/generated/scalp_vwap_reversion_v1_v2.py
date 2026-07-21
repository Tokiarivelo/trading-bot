"""Scalping strategy: session-anchored VWAP reversion on M5 — fades a price
stretch away from VWAP once it exceeds a multiple of the recent (close -
VWAP) standard deviation, entering only once the last candle itself has
already started reverting.

Deliberately carries NO `confirmation_timeframes` — see the v1 module
docstring for why: `engine/application/mtf_confirm.py`'s automatic
EMA(20/50) trend veto on a declared confirmation timeframe would oppose most
of a reversion strategy's setups by construction.

v2: revised after the v1 backtest (XAUUSD 2026-05:2026-07, 429 trades, 19%
win rate, PF 0.63, 38% max drawdown — by far the worst of this batch) showed
the strategy was repeatedly fading into sustained trends rather than genuine
short-term overextensions: with no trend context at all, "far from VWAP" was
often just "trend has been running for a while," not a mean-reversion setup.
Three changes: (1) `deviation_mult` 2.0 -> 2.75, only fading more extreme
stretches; (2) a new "freshness" check requires the deviation to have built
up recently (the z-score `fresh_bars` back must have been much smaller) —
rejects a stretch that's actually a multi-bar established trend; (3) a new
internal regime filter (`max_trend_slope_atr`) rejects the trade outright
when a slow EMA's recent slope is large relative to ATR, i.e. a strongly
trending market — computed from M5 data already in hand, not a declared
confirmation timeframe (see the v1 docstring on why that path is closed off
for a reversion strategy). `atr_mult` widened 1.0 -> 1.3 for more room.
Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np
import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

LOOKBACK = 30  # M5 bars used for the rolling (close - VWAP) deviation stdev
DEVIATION_MULT = 2.75  # v2: raised from 2.0 — only fade more extreme stretches
FRESH_BARS = 5  # v2 new: how far back "freshness" is checked
FRESH_MAX_ABS_Z = 1.0  # v2 new: z-score this many bars back must have been under this
SLOW_EMA_PERIOD = 30  # v2 new: regime-filter EMA
SLOPE_LOOKBACK = 10  # v2 new: bars over which the slow EMA's slope is measured
MAX_TREND_SLOPE_ATR = 3.0  # v2 new: reject if |slow EMA slope| exceeds this many ATRs
ATR_PERIOD = 14
ATR_MULT = 1.3  # v2: widened from 1.0
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) with headroom — see breakout_v1.py for the same constraint.
TP_RR = 2.2
MIN_HISTORY = LOOKBACK + ATR_PERIOD + FRESH_BARS + 2


def _session_vwap(m5: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP, reset at each UTC day boundary when `time` is
    available; falls back to a whole-history cumulative VWAP for the
    sandbox smoke test's synthetic frame, which has no `time` column."""
    typical = (m5["high"] + m5["low"] + m5["close"]) / 3.0
    pv = typical * m5["tick_volume"]
    if "time" in m5.columns:
        day = pd.to_datetime(m5["time"]).dt.floor("D")
        cum_pv = pv.groupby(day).cumsum()
        cum_v = m5["tick_volume"].groupby(day).cumsum()
    else:
        cum_pv = pv.cumsum()
        cum_v = m5["tick_volume"].cumsum()
    return cum_pv / cum_v


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float | None:
    if len(highs) < period + 1:
        return None
    tr = highs[1:] - lows[1:]
    gap_high = np.abs(highs[1:] - closes[:-1])
    gap_low = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr, np.maximum(gap_high, gap_low))
    return float(np.mean(tr[-period:]))


class ScalpVwapReversionV2:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_vwap_reversion_v1",
            version=2,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD", "Boom 1000 Index", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={
                "lookback": LOOKBACK,
                "deviation_mult": DEVIATION_MULT,
                "fresh_bars": FRESH_BARS,
                "fresh_max_abs_z": FRESH_MAX_ABS_Z,
                "slow_ema_period": SLOW_EMA_PERIOD,
                "slope_lookback": SLOPE_LOOKBACK,
                "max_trend_slope_atr": MAX_TREND_SLOPE_ATR,
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        lookback = int(self.spec.params["lookback"])
        deviation_mult = self.spec.params["deviation_mult"]
        fresh_bars = int(self.spec.params["fresh_bars"])
        fresh_max_abs_z = self.spec.params["fresh_max_abs_z"]
        slow_ema_period = int(self.spec.params["slow_ema_period"])
        slope_lookback = int(self.spec.params["slope_lookback"])
        max_trend_slope_atr = self.spec.params["max_trend_slope_atr"]
        atr_period = int(self.spec.params["atr_period"])
        atr_mult = self.spec.params["atr_mult"]
        tp_rr = self.spec.params["tp_rr"]
        if m5 is None or len(m5) < MIN_HISTORY:
            return None

        atr = _atr(
            m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy(), atr_period
        )
        if atr is None or atr <= 0:
            return None

        vwap = _session_vwap(m5)
        diff = m5["close"] - vwap
        window = diff.iloc[-(lookback + 1) : -1]
        std = float(window.std())
        if not np.isfinite(std) or std <= 0:
            return None

        last_close = float(m5["close"].iloc[-1])
        last_open = float(m5["open"].iloc[-1])
        last_vwap = float(vwap.iloc[-1])
        if not np.isfinite(last_vwap):
            return None
        z = (last_close - last_vwap) / std

        # Freshness: the stretch must have built up recently, not be a
        # long-running trend that already looked stretched `fresh_bars` ago.
        if len(diff) > fresh_bars:
            prior_diff = float(diff.iloc[-(fresh_bars + 1)])
            prior_z = prior_diff / std
            if abs(prior_z) >= fresh_max_abs_z:
                return None

        # Regime filter: reject if the market is trending strongly (a slow
        # EMA's recent slope, normalized by ATR, is too large) — fading a
        # genuine trend is how this strategy lost money in v1.
        slow_ema = m5["close"].ewm(span=slow_ema_period, adjust=False).mean()
        if len(slow_ema) > slope_lookback:
            slope = float(slow_ema.iloc[-1] - slow_ema.iloc[-(slope_lookback + 1)])
            if abs(slope) / atr > max_trend_slope_atr:
                return None

        sl_distance = atr * atr_mult

        if z > deviation_mult and last_close < last_open:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 close {last_close:.5f} is {z:.2f} stdev above session VWAP "
                    f"{last_vwap:.5f} (fresh stretch, regime not trending) and closed "
                    f"bearish; ATR({atr_period})={atr:.5f}"
                ),
            )
        if z < -deviation_mult and last_close > last_open:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 close {last_close:.5f} is {abs(z):.2f} stdev below session VWAP "
                    f"{last_vwap:.5f} (fresh stretch, regime not trending) and closed "
                    f"bullish; ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
