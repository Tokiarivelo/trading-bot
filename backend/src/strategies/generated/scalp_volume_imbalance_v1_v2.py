"""Scalping strategy: tick-volume buy/sell pressure imbalance on M5 — a
retail-accessible proxy for order-flow/DOM reading (this codebase's MT5
gateway exposes no Level-2 book data). See the v1 module docstring for the
full rationale.

v2: revised after the v1 backtest (XAUUSD 2026-05:2026-07, 409 trades, 22%
win rate, PF 0.69, 36% max drawdown; Volatility 75 Index similarly weak)
showed the binary "whole bar's volume counts as 100% buy or 100% sell"
attribution was too noisy — a bar that barely closed bullish (a near-doji)
got the exact same full weight as a strong trend bar. v2 weights each bar's
volume contribution by its own body conviction (`|close-open| / (high-low)`,
0..1) before summing the rolling buy/sell split, so weak/indecisive bars
barely move the oscillator while strong directional bars dominate it as
intended. `imbalance_threshold` raised 0.35 -> 0.55 (fewer, higher-conviction
signals) and `imbalance_window` widened 10 -> 14 for a smoother read;
`atr_mult` widened 1.0 -> 1.3. Sandbox-safe: only `numpy`/`pandas`.
"""

import numpy as np

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

IMBALANCE_WINDOW = 14  # v2: widened from 10 — smoother read
IMBALANCE_THRESHOLD = 0.55  # v2: raised from 0.35 — fewer, higher-conviction signals
ATR_PERIOD = 10
ATR_MULT = 1.3  # v2: widened from 1.0
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) with headroom — see breakout_v1.py for the same constraint.
TP_RR = 2.2
MIN_HISTORY = IMBALANCE_WINDOW + ATR_PERIOD + 5


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float | None:
    if len(highs) < period + 1:
        return None
    tr = highs[1:] - lows[1:]
    gap_high = np.abs(highs[1:] - closes[:-1])
    gap_low = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr, np.maximum(gap_high, gap_low))
    return float(np.mean(tr[-period:]))


class ScalpVolumeImbalanceV2:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="scalp_volume_imbalance_v1",
            version=2,
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
        highs = m5["high"].to_numpy()[-window_size:]
        lows = m5["low"].to_numpy()[-window_size:]
        closes_w = m5["close"].to_numpy()[-window_size:]
        volumes = m5["tick_volume"].to_numpy()[-window_size:]

        body_range = highs - lows
        body_strength = np.where(
            body_range > 0, np.clip(np.abs(closes_w - opens) / body_range, 0.0, 1.0), 0.0
        )
        weighted_volume = volumes * body_strength

        bullish = closes_w > opens
        bearish = closes_w < opens
        buy_volume = float(weighted_volume[bullish].sum())
        sell_volume = float(weighted_volume[bearish].sum())
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

        if imbalance > threshold and last_close > last_open:
            return Signal(
                direction=Direction.BUY,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 body-weighted volume imbalance {imbalance:.2f} over last "
                    f"{window_size} bars (buy={buy_volume:.0f} sell={sell_volume:.0f}), "
                    f"last bar bullish; ATR({atr_period})={atr:.5f}"
                ),
            )
        if imbalance < -threshold and last_close < last_open:
            return Signal(
                direction=Direction.SELL,
                sl_points=sl_distance,
                tp_points=sl_distance * tp_rr,
                confidence=0.55,
                reason=(
                    f"M5 body-weighted volume imbalance {imbalance:.2f} over last "
                    f"{window_size} bars (buy={buy_volume:.0f} sell={sell_volume:.0f}), "
                    f"last bar bearish; ATR({atr_period})={atr:.5f}"
                ),
            )
        return None
