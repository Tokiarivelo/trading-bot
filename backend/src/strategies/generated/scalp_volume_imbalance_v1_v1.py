"""Scalping strategy: tick-volume buy/sell pressure imbalance on M5 — a
retail-accessible proxy for order-flow/DOM reading (this codebase's MT5
gateway exposes no Level-2 book data; see
`gateway/src/gateway/mt5_client.py` and `broker/adapters/mt5_gateway.py`,
neither of which has a depth-of-market port). Each M5 bar's `tick_volume` is
attributed entirely to "buy pressure" if it closed bullish or "sell
pressure" if bearish; a rolling window's buy/sell split forms an imbalance
oscillator, and a signal fires only when the imbalance is lopsided AND the
current bar's own direction agrees with it (continuation, not a fade).

Confirmation timeframes: M1 (fresh momentum should still be running in the
signal's direction one timeframe down) and H1 (broader trend must not
oppose) — both continuation-style checks, so the automatic EMA-trend veto in
`engine/application/mtf_confirm.py` is a feature here, not a footgun (unlike
the two reversion strategies in this batch).

Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

IMBALANCE_WINDOW = 10  # M5 bars
IMBALANCE_THRESHOLD = 0.35  # |buy - sell| / (buy + sell) must clear this to signal
ATR_PERIOD = 10
ATR_MULT = 1.0
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) — enforced explicitly below via POINT_VALUES + ctx.spread_points
# (tp_points = (sl_distance + spread) * TP_RR), the same formula SpreadGate
# applies at the broker gate.
TP_RR = 2.2
MIN_HISTORY = IMBALANCE_WINDOW + ATR_PERIOD + 5
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


class ScalpVolumeImbalanceV1:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_volume_imbalance_v1",
            version=1,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD", "Boom 1000 Index", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=("M1", "H1"),
            params={
                "imbalance_window": IMBALANCE_WINDOW,
                "imbalance_threshold": IMBALANCE_THRESHOLD,
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        window_size = int(self.spec.params["imbalance_window"])
        threshold = self.spec.params["imbalance_threshold"]
        atr_period = int(self.spec.params["atr_period"])
        atr_mult = self.spec.params["atr_mult"]
        tp_rr = self.spec.params["tp_rr"]
        if m5 is None or len(m5) < MIN_HISTORY:
            return None

        opens = m5["open"].to_numpy()[-window_size:]
        closes_w = m5["close"].to_numpy()[-window_size:]
        volumes = m5["tick_volume"].to_numpy()[-window_size:]

        bullish = closes_w > opens
        bearish = closes_w < opens
        buy_volume = float(volumes[bullish].sum())
        sell_volume = float(volumes[bearish].sum())
        total_volume = buy_volume + sell_volume
        if total_volume <= 0:
            return None
        imbalance = (buy_volume - sell_volume) / total_volume

        last_open = float(m5["open"].iloc[-1])
        last_close = float(m5["close"].iloc[-1])

        atr = _atr(
            m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy(), atr_period
        )
        if atr is None or atr <= 0:
            return None
        sl_distance = atr * atr_mult
        spread_distance = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)

        if imbalance > threshold and last_close > last_open:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 volume imbalance {imbalance:.2f} over last {window_size} bars "
                    f"(buy={buy_volume:.0f} sell={sell_volume:.0f}), last bar bullish; "
                    f"ATR({atr_period})={atr:.5f}"
                ),
            )
        if imbalance < -threshold and last_close < last_open:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=(sl_distance + spread_distance) * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 volume imbalance {imbalance:.2f} over last {window_size} bars "
                    f"(buy={buy_volume:.0f} sell={sell_volume:.0f}), last bar bearish; "
                    f"ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
