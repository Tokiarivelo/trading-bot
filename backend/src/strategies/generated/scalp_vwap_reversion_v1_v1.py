"""Scalping strategy: session-anchored VWAP reversion on M5 — fades a price
stretch away from VWAP once it exceeds a multiple of the recent (close -
VWAP) standard deviation, entering only once the last candle itself has
already started reverting (closes back toward VWAP vs. its own open), so the
strategy isn't fighting a still-expanding move.

Deliberately carries NO `confirmation_timeframes` (unlike the continuation
strategies in this batch): `engine/application/mtf_confirm.py` auto-vetoes a
signal whose direction opposes a declared confirmation timeframe's EMA(20/50)
trend, but a reversion entry is by definition taken against the immediate
short-term trend — declaring M1 (or even H1, on a fast enough stretch) would
veto most of this strategy's setups, exactly the "mysteriously trade-free
backtest" failure mode called out in `.claude/skills/new-strategy/SKILL.md`.
The band-width-free deviation z-score plus the reversal-candle requirement
serve as this strategy's own trend/range filter instead.

Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np
import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

LOOKBACK = 30  # M5 bars used for the rolling (close - VWAP) deviation stdev
DEVIATION_MULT = 2.0  # entry threshold: |close - VWAP| > this * rolling stdev
ATR_PERIOD = 14
ATR_MULT = 1.0
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) — enforced explicitly below via POINT_VALUES + ctx.spread_points
# (tp_points = (sl_distance + spread) * TP_RR), the same formula SpreadGate
# applies at the broker gate.
TP_RR = 2.2
MIN_HISTORY = LOOKBACK + ATR_PERIOD + 2
# Point size per traded symbol (configs/symbols/*.yaml) — converts
# ctx.spread_points (raw broker points) into a price distance.
POINT_VALUES = {
    "XAUUSD": 0.01,
    "XAGUSD": 0.001,
    "BTCUSD": 0.01,
    "Boom 1000 Index": 0.0001,
    "Volatility 75 Index": 0.01,
}


def _session_vwap(m5: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP, reset at each UTC day boundary when `time` is
    available (real trading/backtest data always includes it); falls back to
    a whole-history cumulative VWAP for the sandbox smoke test's synthetic
    frame, which has no `time` column."""
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


class ScalpVwapReversionV1:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_vwap_reversion_v1",
            version=1,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD", "Boom 1000 Index", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={
                "lookback": LOOKBACK,
                "deviation_mult": DEVIATION_MULT,
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        lookback = int(self.spec.params["lookback"])
        deviation_mult = self.spec.params["deviation_mult"]
        atr_period = int(self.spec.params["atr_period"])
        atr_mult = self.spec.params["atr_mult"]
        tp_rr = self.spec.params["tp_rr"]
        if m5 is None or len(m5) < MIN_HISTORY:
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

        atr = _atr(
            m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy(), atr_period
        )
        if atr is None or atr <= 0:
            return None
        sl_distance = atr * atr_mult
        spread_distance = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)

        # Stretched above VWAP and the last candle already closed bearish
        # (reversion under way) -> fade it, sell.
        if z > deviation_mult and last_close < last_open:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 close {last_close:.5f} is {z:.2f} stdev above session VWAP "
                    f"{last_vwap:.5f} and closed bearish; ATR({atr_period})={atr:.5f}"
                ),
            )
        # Stretched below VWAP and the last candle already closed bullish.
        if z < -deviation_mult and last_close > last_open:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 close {last_close:.5f} is {abs(z):.2f} stdev below session VWAP "
                    f"{last_vwap:.5f} and closed bullish; ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
