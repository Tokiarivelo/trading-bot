"""Scalping strategy: M5 consolidation-range breakout with a volume-confirmed
break, plus M1 momentum and H1 trend as automatic engine confirmation gates
(declaring M1/H1 in `confirmation_timeframes` makes
`engine/application/mtf_confirm.py` veto any signal whose direction opposes
either timeframe's EMA(20/50) trend, on top of this file's own range+volume
logic).

v2: revised after the v1 backtest (XAUUSD 2026-05:2026-07, 276 trades, 27%
win rate, PF 0.94 — just below breakeven, which needs ~31% at TP_RR=2.2) came
back essentially breakeven-negative. Two changes address the likely cause:
(1) `volume_mult` 1.3 -> 1.6, requiring a clearly stronger volume surge on
the breakout bar instead of a marginal one; (2) a new minimum-range-width
filter (`min_range_atr_mult`) skips breakouts of a range that's narrower
than 1.2x ATR — a range that tight is usually noise, not a real
consolidation, and its "breakout" is often just the next random tick.
`atr_mult` (stop sizing) is also widened 1.0 -> 1.3 since a stop this tight
on a genuine breakout gets clipped by ordinary pullback noise before the
move develops. Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

LOOKBACK = 10  # M5 bars forming the consolidation range (50 min)
ATR_PERIOD = 7
ATR_MULT = 1.3  # SL = ATR_MULT * ATR(7) — v2: widened from 1.0, was getting clipped by noise
VOLUME_MULT = 1.6  # v2: raised from 1.3 — require a clearly stronger volume surge
MIN_RANGE_ATR_MULT = 1.2  # v2 new: range must be at least this many ATRs wide to trade
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) with headroom — see breakout_v1.py for the same constraint.
TP_RR = 2.2
MIN_HISTORY = LOOKBACK + ATR_PERIOD + 2


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float | None:
    if len(highs) < period + 1:
        return None
    tr = highs[1:] - lows[1:]
    gap_high = np.abs(highs[1:] - closes[:-1])
    gap_low = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr, np.maximum(gap_high, gap_low))
    return float(np.mean(tr[-period:]))


class ScalpRangeBreakoutV2:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_range_breakout_v1",
            version=2,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD", "Boom 1000 Index", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=("M1", "H1"),
            params={
                "lookback": LOOKBACK,
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "volume_mult": VOLUME_MULT,
                "min_range_atr_mult": MIN_RANGE_ATR_MULT,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        lookback = int(self.spec.params["lookback"])
        atr_period = int(self.spec.params["atr_period"])
        atr_mult = self.spec.params["atr_mult"]
        volume_mult = self.spec.params["volume_mult"]
        min_range_atr_mult = self.spec.params["min_range_atr_mult"]
        tp_rr = self.spec.params["tp_rr"]
        if m5 is None or len(m5) < MIN_HISTORY:
            return None

        window = m5.iloc[-(lookback + 1) : -1]
        last = m5.iloc[-1]
        range_high = float(window["high"].max())
        range_low = float(window["low"].min())
        avg_volume = float(window["tick_volume"].mean())
        last_close = float(last["close"])
        last_volume = float(last["tick_volume"])

        if avg_volume <= 0 or last_volume < volume_mult * avg_volume:
            return None

        atr = _atr(
            m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy(), atr_period
        )
        if atr is None or atr <= 0:
            return None
        if (range_high - range_low) < min_range_atr_mult * atr:
            return None  # range too tight to be a real consolidation -> likely noise
        sl_distance = atr * atr_mult

        if last_close > range_high:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.6,
                reason=(
                    f"M5 close {last_close:.5f} broke {lookback}-bar range high "
                    f"{range_high:.5f} (range width {range_high - range_low:.5f} >= "
                    f"{min_range_atr_mult}x ATR) on volume {last_volume:.0f} >= "
                    f"{volume_mult}x avg {avg_volume:.0f}; ATR({atr_period})={atr:.5f}"
                ),
            )
        if last_close < range_low:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.6,
                reason=(
                    f"M5 close {last_close:.5f} broke {lookback}-bar range low "
                    f"{range_low:.5f} (range width {range_high - range_low:.5f} >= "
                    f"{min_range_atr_mult}x ATR) on volume {last_volume:.0f} >= "
                    f"{volume_mult}x avg {avg_volume:.0f}; ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
