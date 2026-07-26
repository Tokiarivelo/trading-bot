"""Trend-structure v7: v2's exact entry/SL trigger (unchanged), plus an
additive RSI(14)/ADX(14)/EMA(20,50) confluence score that only ever widens
TP — never gates the entry and never shrinks TP below v2's own 2.2x floor.

`trend_structure_v3` through `v6` all tried to improve on `trend_structure_v2`
(561 trades, XAUUSD 2026-04:2026-07, 90.4% win, PF 2.60, avg_r +0.164, ending
balance $14,912 from a $10k start) and every one of them made things worse on
the metric that matters most here — trade count — because each added a hard
gate:

  - v3 (zone-anchored SL + structural TP): 101 trades, PF 0.95 (net losing)
  - v4 (zone-anchored SL, fixed TP=2.2): 226 trades, PF 1.48, avg_r +0.108
  - v5 (v4 + RSI(14) veto gate): 221 trades, PF 1.57, avg_r +0.122
  - v6 (v4 + EMA(20/50) veto gate): 213 trades, PF 1.58, avg_r +0.125

Every zone-anchored-SL variant (v3-v6) has a *lower* avg_r than plain v2
despite a "more honestly placed" stop — the tighter, zone-precise SL gets
clipped by ordinary noise before a genuine leg develops often enough to
outweigh the theoretical improvement. And every hard veto gate (v5, v6)
necessarily trades less often than the entries it's filtering, which is
exactly backwards when the un-gated baseline (v2) already dominates on every
axis except drawdown. v7 does not repeat that mistake: it reuses v2's entry
trigger, structural-alignment filter, min-swing-ATR filter, and SL anchor
byte-for-byte, so it cannot signal on fewer bars than v2 did — anything v2
would have taken, v7 takes too.

A fresh feature-correlation study against v2's own 561-trade backtest (not
v4's smaller 226-trade sample used for v5/v6) reproduces and strengthens the
RSI finding at 2.5x the sample size, using v2's real SL/TP mechanics and the
engine's own bot-agnostic PositionManager (breakeven-at-+1R, secure-on-
base-clear, time-stop — unmodified, untouched, still fully in effect here):

  - RSI(14) alignment (>50 for a buy / <50 for a sell) at the entry bar:
    455 "aligned" trades won 98.2% of the time, +123.53R total (avg +0.272R);
    106 "unaligned" trades won only 56.6% of the time and were net *negative*
    at -31.72R total (avg -0.299R) -- a large, real losing bucket, not noise.
  - ADX(14) > 25 at the entry bar: 337 trades won 95.0% (+68.27R, avg
    +0.203R) vs 224 trades at 83.5% (+23.54R, avg +0.105R) -- a real but
    weaker signal; both buckets stayed net positive alone, unlike RSI's.
  - EMA(20)/EMA(50) trend alignment: 516/561 trades were already aligned
    (v2's own structural-alignment filter mostly guarantees this, echoing
    the same near-redundancy `trend_structure_v6` found on v4's sample) and
    the 45 misaligned trades still won 84.4% -- weak on its own, kept here
    only as a third confluence vote alongside RSI/ADX.
  - MACD(12,26,9) histogram alignment showed a similar split to RSI (311
    trades 98.1% win / +77.57R vs 250 at 80.8% / +14.24R) but is the same
    momentum family as RSI and highly redundant with it -- left out in favor
    of ADX as an independent trend-*strength* axis instead of a second
    momentum-*direction* vote.
  - Tick-volume ratio / z-score vs its own 20-bar average: *inversely*
    correlated with outcome (above-average-volume entries: 86.1% win,
    avg +0.108R; below-average: 93.9% win, avg +0.209R; corr(r_multiple)
    -0.10 to -0.12) -- confirms `trend_structure_v5`'s docstring, which
    tested and dropped the same thing on v4's sample. Not used here either.

Because this task's constraint is "do not regress the number of positions",
RSI/ADX/EMA confluence is used *additively only*: it raises `tp_rr` for
higher-conviction entries, never lowers it below v2's own proven 2.2, and
never vetoes a signal:

  - all 3 confirm (RSI, ADX>25, EMA all aligned with the trade direction):
    tp_rr = 3.0
  - exactly 2 of 3 confirm: tp_rr = 2.6
  - 0 or 1 of 3 confirm (including the -31.72R RSI-unaligned bucket):
    tp_rr = 2.2, i.e. identical to v2 -- unchanged, not shrunk

A wider tp_rr can only make `SpreadGate`'s `min_rr` floor easier to clear
than v2's already-proven 2.2 margin, never harder, so this cannot introduce
a new veto path either. Indicator math failing to warm up (NaN) degrades to
"not confirmed" for that vote, never to skipping the trade. Most trades still
close via the engine's breakeven/secure-base/time-stop rules before ever
reaching the nominal TP (that's most of why v2's realized avg_r of +0.164 is
so far under its 2.2 nominal ceiling already) -- the wider tier just gives
the highest-conviction trades more room inside that same downstream
management, it does not override it.

A first v7 draft copied the TP formula from the plain `trend_structure_v2.py`
file (`tp_points = sl_points * tp_rr`) and, on the first real backtest,
landed at 556 trades against v2's 561 -- a real 5-trade shortfall despite an
identical entry trigger, traced (by diffing every SIGNAL/ENTRY log line
between the two runs for the missing trades) to the fact that the DB's
*active* `trend_structure_v2` version (`trend_structure_v2_v1.py`, what
`/backtest/run` and the live engine actually execute — the plain
`trend_structure_v2.py` this repo also ships is an older, unused sibling)
had since been refined to a spread-inclusive TP: `tp_points = (sl_points +
spread_price) * tp_rr`, matching the same formula `SpreadGate` itself checks.
The wider effective TP that formula produces is what let those 5 borderline
setups clear the spread-adjusted `min_rr` floor; the naive `sl_points *
tp_rr` version was, for those setups, actually *narrower* than v2's real
TP despite a >=2.2 tp_rr, because it omitted the spread term entirely. v7
below reuses that same spread-inclusive formula (same `POINT_VALUES` map),
so it inherits the exact TP width v2 gets for the 0-1-vote tier and only
widens it from there for 2-3-vote confluence.

No live/backtest track record yet for v7 itself -- validate with
`/backtest/run` before activating. Sandbox-safe: only `numpy`/`pandas` -- no
I/O, no broker access.
"""

import numpy as np
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
ATR_PERIOD = 14
MIN_SWING_ATR_MULT = 0.5  # new swing must beat the prior same-kind swing by this much ATR
RSI_PERIOD = 14
ADX_PERIOD = 14
ADX_STRONG = 25.0
EMA_FAST = 20
EMA_SLOW = 50
MIN_HISTORY = 60  # room for ATR/RSI/ADX(14) and EMA(50) warmup plus 5 alternating swing pivots
# tp_rr floor matches v2 exactly -- never shrunk. Must clear every symbol's
# configs/symbols/<sym>.yaml min_rr (highest: XAGUSD at 1.8) with headroom.
TP_RR_BASE = 2.2
TP_RR_TIER2 = 2.6  # exactly 2 of 3 confluence votes aligned
TP_RR_TIER3 = 3.0  # all 3 confluence votes aligned
# Point size per traded symbol (configs/symbols/*.yaml) -- converts
# ctx.spread_points (raw broker points) into a price distance. Same map and
# same spread-inclusive TP formula as the DB-active trend_structure_v2
# (trend_structure_v2_v1.py), which SpreadGate's own min_rr check uses too.
POINT_VALUES = {"XAUUSD": 0.01, "XAGUSD": 0.001, "BTCUSD": 0.01}


def _swing_flags(highs: np.ndarray, lows: np.ndarray, wing: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows: a bar whose high (low) is the max (min) of
    the `wing`-bar window on each side."""
    n = len(highs)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    window = 2 * wing + 1
    if n >= window:
        window_max = np.lib.stride_tricks.sliding_window_view(highs, window).max(axis=1)
        window_min = np.lib.stride_tricks.sliding_window_view(lows, window).min(axis=1)
        is_high[wing : n - wing] = highs[wing : n - wing] == window_max
        is_low[wing : n - wing] = lows[wing : n - wing] == window_min
    return is_high, is_low


def _push_swing(swings: list[tuple[int, float, str]], index: int, price: float, kind: str) -> None:
    if swings and swings[-1][2] == kind:
        _, prev_price, _ = swings[-1]
        if (kind == "high" and price > prev_price) or (kind == "low" and price < prev_price):
            swings[-1] = (index, price, kind)
        return
    swings.append((index, price, kind))


def _zigzag_swings(highs: np.ndarray, lows: np.ndarray, wing: int) -> list[tuple[int, float, str]]:
    is_high, is_low = _swing_flags(highs, lows, wing)
    swings: list[tuple[int, float, str]] = []
    for i in np.flatnonzero(is_high | is_low):
        index = int(i)
        if is_high[index]:
            _push_swing(swings, index, float(highs[index]), "high")
        if is_low[index]:
            _push_swing(swings, index, float(lows[index]), "low")
    return swings


def _true_range_values(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    tr = highs - lows
    if len(tr) > 1:
        gap_high = np.abs(highs[1:] - closes[:-1])
        gap_low = np.abs(lows[1:] - closes[:-1])
        tr[1:] = np.maximum(tr[1:], np.maximum(gap_high, gap_low))
    return tr


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> pd.Series:
    tr = pd.Series(_true_range_values(highs, lows, closes))
    return tr.rolling(period, min_periods=period).mean()


def _rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # avg_loss == 0 with avg_gain > 0 is a real "no losses in the window"
    # case (rs -> inf, rsi -> 100), not a warmup gap -- only avg_gain ==
    # avg_loss == 0 (flat series) is genuinely indeterminate (NaN).
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _adx(highs: pd.Series, lows: pd.Series, tr: pd.Series, period: int) -> pd.Series:
    up_move = highs.diff()
    down_move = -lows.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_dm_ewm = pd.Series(plus_dm, index=highs.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False
    )
    minus_dm_ewm = pd.Series(minus_dm, index=highs.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False
    )
    plus_di = 100 * plus_dm_ewm.mean() / atr
    minus_di = 100 * minus_dm_ewm.mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _confluence_votes(
    closes: pd.Series,
    highs: pd.Series,
    lows: pd.Series,
    tr: pd.Series,
    direction: Direction,
) -> tuple[bool, bool, bool]:
    """RSI/ADX/EMA confluence votes at the last bar. NaN (not enough warmup)
    degrades to "not confirmed" for that vote -- never raises, never skips
    the trade, since this whole path is additive-only."""
    is_buy = direction == Direction.BUY

    rsi_val = _rsi(closes, RSI_PERIOD).iloc[-1]
    rsi_ok = bool(rsi_val > 50) if is_buy else bool(rsi_val < 50)
    rsi_ok = rsi_ok if pd.notna(rsi_val) else False

    adx_val = _adx(highs, lows, tr, ADX_PERIOD).iloc[-1]
    adx_ok = bool(pd.notna(adx_val) and adx_val > ADX_STRONG)

    ema_fast = closes.ewm(span=EMA_FAST, adjust=False).mean().iloc[-1]
    ema_slow = closes.ewm(span=EMA_SLOW, adjust=False).mean().iloc[-1]
    ema_ok = bool(ema_fast > ema_slow) if is_buy else bool(ema_fast < ema_slow)
    ema_ok = ema_ok if pd.notna(ema_fast) and pd.notna(ema_slow) else False

    return rsi_ok, adx_ok, ema_ok


class TrendStructureV7:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="trend_structure_v7",
            version=7,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={
                "pivot_wing": PIVOT_WING,
                "atr_period": ATR_PERIOD,
                "min_swing_atr_mult": MIN_SWING_ATR_MULT,
                "rsi_period": RSI_PERIOD,
                "adx_period": ADX_PERIOD,
                "adx_strong": ADX_STRONG,
                "ema_fast": EMA_FAST,
                "ema_slow": EMA_SLOW,
                "tp_rr_base": TP_RR_BASE,
                "tp_rr_tier2": TP_RR_TIER2,
                "tp_rr_tier3": TP_RR_TIER3,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        m5 = ctx.candles.get("M5")
        wing = int(self.spec.params["pivot_wing"])
        atr_period = int(self.spec.params["atr_period"])
        min_swing_atr_mult = self.spec.params["min_swing_atr_mult"]
        if m5 is None or len(m5) < MIN_HISTORY:
            return None

        highs = m5["high"].to_numpy()
        lows = m5["low"].to_numpy()

        swings = _zigzag_swings(highs, lows, wing)
        if len(swings) < 5:
            return None

        last_index, last_price, last_kind = swings[-1]
        if last_index != len(m5) - 1 - wing:
            return None

        prior_index, prior_price, prior_kind = swings[-3]
        if prior_kind != last_kind:
            return None
        _, sl_reference, _ = swings[-2]
        _, context_reference, context_kind = swings[-4]
        if context_kind != swings[-2][2]:
            return None

        if last_kind == "high" and last_price > prior_price:
            if sl_reference <= context_reference:
                return None
            direction, label = Direction.BUY, StructureLabel.HH
        elif last_kind == "low" and last_price < prior_price:
            if sl_reference >= context_reference:
                return None
            direction, label = Direction.SELL, StructureLabel.LL
        else:
            return None

        closes = m5["close"].to_numpy()
        atr = _atr(highs, lows, closes, atr_period)
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        if abs(last_price - prior_price) < atr_val * min_swing_atr_mult:
            return None

        entry_price = float(closes[-1])
        sl_points = abs(entry_price - sl_reference)
        if sl_points <= 0:
            return None

        closes_s = m5["close"]
        highs_s = m5["high"]
        lows_s = m5["low"]
        tr = pd.Series(_true_range_values(highs, lows, closes))
        rsi_ok, adx_ok, ema_ok = _confluence_votes(closes_s, highs_s, lows_s, tr, direction)
        votes = sum((rsi_ok, adx_ok, ema_ok))
        if votes == 3:
            tp_rr = self.spec.params["tp_rr_tier3"]
        elif votes == 2:
            tp_rr = self.spec.params["tp_rr_tier2"]
        else:
            tp_rr = self.spec.params["tp_rr_base"]
        # Spread-inclusive, same formula as the DB-active trend_structure_v2
        # and the one SpreadGate itself checks -- omitting the spread term
        # here would make v7's TP *narrower* than v2's real TP for the same
        # tp_rr, which is what caused v7's first draft to trade less often
        # than v2 despite an identical entry trigger (see module docstring).
        spread_price = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)
        tp_points = (sl_points + spread_price) * tp_rr

        confidence = min(0.6 + 0.1 * votes, 0.9)

        structure: tuple[StructurePoint, ...] = ()
        if "time" in m5.columns:
            structure = (
                StructurePoint(time=m5["time"].iloc[last_index], price=last_price, label=label),
            )

        return Signal(
            direction=direction,
            sl_points=sl_points,
            tp_points=tp_points,
            confidence=confidence,
            reason=(
                f"{label.value} at {last_price:.5f} (bar {last_index}) beat prior swing "
                f"{prior_price:.5f} (bar {prior_index}) by >= {min_swing_atr_mult}xATR, "
                f"aligned with prior {'HL' if label is StructureLabel.HH else 'LH'}; "
                f"SL anchored to swing {sl_reference:.5f}; "
                f"confluence rsi={rsi_ok} adx={adx_ok} ema={ema_ok} ({votes}/3) -> tp_rr={tp_rr}"
            ),
            structure=structure,
        )
