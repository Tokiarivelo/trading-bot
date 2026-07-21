"""Scalping strategy: M5 consolidation-range breakout with a volume-confirmed
break, plus M1 momentum and H1 trend as automatic engine confirmation gates
(declaring M1/H1 in `confirmation_timeframes` makes
`engine/application/mtf_confirm.py` veto any signal whose direction opposes
either timeframe's EMA(20/50) trend, on top of this file's own range+volume
logic).

Tighter and faster than `breakout_v1`: a shorter lookback range, a
volume-confirmed break (the breakout bar's tick_volume must clear the
range's average — filters the low-volume false breaks a tight range
otherwise produces), and an ATR-sized stop instead of the full range width,
so wins/losses resolve in a handful of M5 bars instead of riding the whole
range's height. Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

LOOKBACK = 10  # M5 bars forming the consolidation range (50 min)
ATR_PERIOD = 7
ATR_MULT = 1.0  # SL = ATR_MULT * ATR(7) — tight scalp stop, not the full range height
VOLUME_MULT = 1.3  # breakout bar's tick_volume must clear this * the range's avg volume
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


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float | None:
    if len(highs) < period + 1:
        return None
    tr = highs[1:] - lows[1:]
    gap_high = np.abs(highs[1:] - closes[:-1])
    gap_low = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr, np.maximum(gap_high, gap_low))
    return float(np.mean(tr[-period:]))


class ScalpRangeBreakoutV1:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_range_breakout_v1",
            version=1,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD", "Boom 1000 Index", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=("M1", "H1"),
            params={
                "lookback": LOOKBACK,
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "volume_mult": VOLUME_MULT,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        lookback = int(self.spec.params["lookback"])
        atr_period = int(self.spec.params["atr_period"])
        atr_mult = self.spec.params["atr_mult"]
        volume_mult = self.spec.params["volume_mult"]
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
        sl_distance = atr * atr_mult
        spread_distance = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)

        if last_close > range_high:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.6,
                reason=(
                    f"M5 close {last_close:.5f} broke {lookback}-bar range high "
                    f"{range_high:.5f} on volume {last_volume:.0f} >= "
                    f"{volume_mult}x avg {avg_volume:.0f}; ATR({atr_period})={atr:.5f}"
                ),
            )
        if last_close < range_low:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.6,
                reason=(
                    f"M5 close {last_close:.5f} broke {lookback}-bar range low "
                    f"{range_low:.5f} on volume {last_volume:.0f} >= "
                    f"{volume_mult}x avg {avg_volume:.0f}; ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
