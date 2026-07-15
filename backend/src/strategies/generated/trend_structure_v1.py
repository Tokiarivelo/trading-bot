"""Pure price-structure trend-following strategy: trades HH/LL continuation.

No indicators — only swing-pivot (fractal) detection on the M5 candle series.
Enters long the bar a confirmed swing high prints above the prior confirmed
swing high (HH), short the bar a confirmed swing low prints below the prior
confirmed swing low (LL). Higher lows / lower highs (HL/LH) are structure but
not entries here — this strategy only trades trend continuation, not the
reversal legs. Sandbox-safe: only `pandas` — no I/O, no broker access.
"""

import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    Signal,
    StrategySpec,
    StructureLabel,
    StructurePoint,
)

PIVOT_WING = 3  # bars required on each side of a candidate to confirm a swing
MIN_HISTORY = 30  # enough bars for at least 3 alternating swing pivots to form
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) with headroom — see breakout_v1.py for the same constraint.
TP_RR = 2.2


def _swing_flags(df: pd.DataFrame, wing: int) -> tuple[pd.Series, pd.Series]:
    highs, lows = df["high"], df["low"]
    is_high = pd.Series(False, index=df.index)
    is_low = pd.Series(False, index=df.index)
    for i in range(wing, len(df) - wing):
        window_h = highs.iloc[i - wing : i + wing + 1]
        window_l = lows.iloc[i - wing : i + wing + 1]
        if highs.iloc[i] == window_h.max():
            is_high.iloc[i] = True
        if lows.iloc[i] == window_l.min():
            is_low.iloc[i] = True
    return is_high, is_low


def _push_swing(swings: list[tuple[int, float, str]], index: int, price: float, kind: str) -> None:
    # Collapses runs of same-kind pivots (e.g. two fractal highs in a row
    # before the next low prints) down to the single most extreme one, so the
    # resulting sequence strictly alternates high/low/high/low — a zigzag.
    if swings and swings[-1][2] == kind:
        _, prev_price, _ = swings[-1]
        if (kind == "high" and price > prev_price) or (kind == "low" and price < prev_price):
            swings[-1] = (index, price, kind)
        return
    swings.append((index, price, kind))


def _zigzag_swings(df: pd.DataFrame, wing: int) -> list[tuple[int, float, str]]:
    is_high, is_low = _swing_flags(df, wing)
    swings: list[tuple[int, float, str]] = []
    for i in range(wing, len(df) - wing):
        if is_high.iloc[i]:
            _push_swing(swings, i, float(df["high"].iloc[i]), "high")
        if is_low.iloc[i]:
            _push_swing(swings, i, float(df["low"].iloc[i]), "low")
    return swings


class TrendStructureV1:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="trend_structure_v1",
            version=1,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={"pivot_wing": PIVOT_WING, "tp_rr": TP_RR},
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        wing = int(self.spec.params["pivot_wing"])
        tp_rr = self.spec.params["tp_rr"]
        if m5 is None or len(m5) < MIN_HISTORY:
            return None

        swings = _zigzag_swings(m5, wing)
        if len(swings) < 3:
            return None

        # A fractal at index i only confirms once `wing` bars have closed to
        # its right. Only act on the bar that confirmation lands on, so the
        # same pivot doesn't re-fire a signal on every later bar.
        last_index, last_price, last_kind = swings[-1]
        if last_index != len(m5) - 1 - wing:
            return None

        prior_index, prior_price, prior_kind = swings[-3]
        if prior_kind != last_kind:
            return None
        _, sl_reference, _ = swings[-2]  # opposite-kind pivot between them: structure invalidation

        if last_kind == "high" and last_price > prior_price:
            direction, label = Direction.BUY, StructureLabel.HH
        elif last_kind == "low" and last_price < prior_price:
            direction, label = Direction.SELL, StructureLabel.LL
        else:
            return None

        entry_price = float(m5["close"].iloc[-1])
        sl_points = abs(entry_price - sl_reference)
        if sl_points <= 0:
            return None
        tp_points = sl_points * tp_rr

        structure: tuple[StructurePoint, ...] = ()
        if "time" in m5.columns:
            structure = (
                StructurePoint(time=m5["time"].iloc[last_index], price=last_price, label=label),
            )

        return Signal(
            direction=direction,
            sl_points=sl_points,
            tp_points=tp_points,
            confidence=0.55,
            reason=(
                f"{label.value} at {last_price:.5f} (bar {last_index}) beat prior swing "
                f"{prior_price:.5f} (bar {prior_index}); SL anchored to swing {sl_reference:.5f}"
            ),
            structure=structure,
        )
