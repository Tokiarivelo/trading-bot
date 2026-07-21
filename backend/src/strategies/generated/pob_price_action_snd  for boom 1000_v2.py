import numpy as np
import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

# Boom 1000 Index point size (configs/symbols/boom 1000 index.yaml) — converts
# ctx.spread_points (raw broker points) into a price distance so
# reward_risk_ratio below is applied to (sl + spread), not sl alone — the
# same floor SpreadGate enforces at the broker gate (tp >= min_rr * (sl + spread)).
POINT_VALUE = 0.0001

# Perf note: helpers below operate on numpy arrays extracted once per
# evaluate() (`df[col].to_numpy()`) instead of per-element `.iloc` reads —
# the math, comparisons, and results are identical, but a backtest calls
# evaluate() on every bar and pandas scalar indexing dominated its runtime.


def _true_range_values(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    tr = highs - lows
    if len(tr) > 1:
        # Bar 0 has no previous close; its TR stays high-low, matching the
        # old concat().max(axis=1) which skipped the NaN gap columns there.
        gap_high = np.abs(highs[1:] - closes[:-1])
        gap_low = np.abs(lows[1:] - closes[:-1])
        tr[1:] = np.maximum(tr[1:], np.maximum(gap_high, gap_low))
    return tr


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> pd.Series:
    # Rolling mean stays in pandas (not a cumsum shortcut) so ATR values are
    # bit-identical to the previous implementation.
    tr = pd.Series(_true_range_values(highs, lows, closes))
    return tr.rolling(period, min_periods=period).mean()


def _is_bullish_engulfing(opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = opens[i - 1], closes[i - 1]
    o, c = opens[i], closes[i]
    if not (prev_c < prev_o and c > o):
        return False
    return bool(o <= prev_c and c >= prev_o)


def _is_bearish_engulfing(opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = opens[i - 1], closes[i - 1]
    o, c = opens[i], closes[i]
    if not (prev_c > prev_o and c < o):
        return False
    return bool(o >= prev_c and c <= prev_o)


def _body_candle_side(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    i: int,
    min_body_ratio: float,
) -> tuple[bool, str]:
    rng = highs[i] - lows[i]
    if rng <= 0:
        return False, ""
    if abs(closes[i] - opens[i]) / rng < min_body_ratio:
        return False, ""
    return True, ("up" if closes[i] > opens[i] else "down")


def _swing_flags(
    highs: np.ndarray, lows: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows: a bar whose high (low) is the max (min) of
    the `lookback`-bar window on each side. Windowed max/min are computed in
    one vector pass; equality against the center bar matches the old
    per-bar scan exactly."""
    n = len(highs)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    window = 2 * lookback + 1
    if n >= window:
        window_max = np.lib.stride_tricks.sliding_window_view(highs, window).max(axis=1)
        window_min = np.lib.stride_tricks.sliding_window_view(lows, window).min(axis=1)
        is_high[lookback : n - lookback] = highs[lookback : n - lookback] == window_max
        is_low[lookback : n - lookback] = lows[lookback : n - lookback] == window_min
    return is_high, is_low


def _count_sr_touches(
    highs: np.ndarray,
    lows: np.ndarray,
    level_low: float,
    level_high: float,
    is_high: np.ndarray,
    is_low: np.ndarray,
    tolerance: float,
) -> int:
    mid = (level_low + level_high) / 2
    high_touch = is_high & (np.abs(highs - mid) <= tolerance)
    low_touch = is_low & (np.abs(lows - mid) <= tolerance)
    return int(np.count_nonzero(high_touch | low_touch))


def _find_base(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: pd.Series,
    params: dict,
) -> dict | None:
    n = len(closes)
    last_idx = n - 1
    current_atr = atr.iloc[last_idx]
    if pd.isna(current_atr) or current_atr <= 0:
        return None

    impulse_bars = int(params["impulse_lookback_bars"])
    for base_len in range(2, int(params["base_max_bars"]) + 1):
        base_start = last_idx - base_len
        base_end = last_idx - 1
        if base_start - impulse_bars < 0:
            continue

        base_range = highs[base_start : base_end + 1] - lows[base_start : base_end + 1]
        if (base_range > current_atr * 0.6).any():
            continue

        pre_move = closes[base_start - 1] - closes[base_start - impulse_bars]
        if abs(pre_move) < current_atr * params["impulse_min_atr_mult"]:
            continue

        return {
            "base_start": base_start,
            "base_high": highs[base_start : base_end + 1].max(),
            "base_low": lows[base_start : base_end + 1].min(),
            "leg_before": "up" if pre_move > 0 else "down",
        }
    return None


def _danger_zone_breached(
    highs: np.ndarray,
    lows: np.ndarray,
    base_low: float,
    base_high: float,
    direction: Direction,
    atr_val: float,
    mult: float,
    from_idx: int,
) -> bool:
    if direction == Direction.BUY:
        return bool((lows[from_idx:] < base_low - atr_val * mult).any())
    return bool((highs[from_idx:] > base_high + atr_val * mult).any())


def _mtf_confirms(ctx: MarketContext, tf: str, direction: Direction, params: dict) -> bool:
    df = ctx.candles.get(tf)
    lookback = int(params["confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return False
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    start_i = len(df) - lookback
    for i in range(start_i, len(df)):
        if direction == Direction.BUY:
            if _is_bullish_engulfing(opens, closes, i):
                return True
            strong, side = _body_candle_side(
                opens, highs, lows, closes, i, params["mtf_min_body_ratio"]
            )
            if strong and side == "up":
                return True
        else:
            if _is_bearish_engulfing(opens, closes, i):
                return True
            strong, side = _body_candle_side(
                opens, highs, lows, closes, i, params["mtf_min_body_ratio"]
            )
            if strong and side == "down":
                return True
    return False


class PobPriceActionSnd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_price_action_snd",
            version=1,
            symbols=("Boom 1000 Index",),
            entry_timeframe="M5",
            confirmation_timeframes=("M15", "M30", "H1", "H4"),
            params={
                "swing_lookback": 3,
                "base_max_bars": 4,
                "impulse_lookback_bars": 3,
                "impulse_min_atr_mult": 1.5,
                "sr_lookback_bars": 100,
                "sr_tolerance_atr_mult": 0.25,
                "sr_min_touches": 2,
                "danger_zone_atr_mult": 0.5,
                "engulf_min_body_ratio": 0.6,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 6,
                "min_confirmations": 2,
                "atr_period": 14,
                "sl_atr_mult": 1.2,
                "reward_risk_ratio": 1.8,
                "min_confidence": 0.5,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        min_bars = int(params["sr_lookback_bars"]) + int(params["base_max_bars"]) + 10
        if df is None or len(df) < min_bars:
            return None

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()

        atr = _atr(highs, lows, closes, int(params["atr_period"]))
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None

        base = _find_base(highs, lows, closes, atr, params)
        if base is None:
            return None

        last_i = len(df) - 1
        breakout_up = _is_bullish_engulfing(opens, closes, last_i)
        breakout_down = _is_bearish_engulfing(opens, closes, last_i)
        if not (breakout_up or breakout_down):
            strong, side = _body_candle_side(
                opens, highs, lows, closes, last_i, params["engulf_min_body_ratio"]
            )
            breakout_up = strong and side == "up"
            breakout_down = strong and side == "down"
        if breakout_up == breakout_down:
            return None

        leg_before = base["leg_before"]
        base_high, base_low = base["base_high"], base["base_low"]

        # Reversal-only setups (Hybrid/QM/Blindspot) are the author's high-risk
        # "FAST"-skip category; only structurally confirmed rally/drop-base
        # entries at a tested support/resistance line are traded here.
        if leg_before == "up" and breakout_up:
            direction, setup = Direction.BUY, "SNRC1-RBR"
        elif leg_before == "down" and breakout_down:
            direction, setup = Direction.SELL, "SNRC1-DBD"
        elif leg_before == "up" and breakout_down:
            direction, setup = Direction.SELL, "SNRC2-RBD"
        elif leg_before == "down" and breakout_up:
            direction, setup = Direction.BUY, "SNRC2-DBR"
        else:
            return None

        sr_window_end = base["base_start"]
        sr_window_start = max(0, sr_window_end - int(params["sr_lookback_bars"]))
        sr_highs = highs[sr_window_start:sr_window_end]
        sr_lows = lows[sr_window_start:sr_window_end]
        tolerance = atr_val * params["sr_tolerance_atr_mult"]
        strong_sr = False
        if len(sr_highs) > 2 * int(params["swing_lookback"]) + 1:
            is_high, is_low = _swing_flags(sr_highs, sr_lows, int(params["swing_lookback"]))
            touches = _count_sr_touches(
                sr_highs, sr_lows, base_low, base_high, is_high, is_low, tolerance
            )
            strong_sr = touches >= int(params["sr_min_touches"])
        if not strong_sr:
            return None

        if _danger_zone_breached(
            highs, lows, base_low, base_high, direction, atr_val,
            params["danger_zone_atr_mult"], base["base_start"],
        ):
            return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        confidence = 0.5 if setup.startswith("SNRC1") else 0.45
        confidence += 0.1 * confirmations
        confidence = min(confidence, 0.95)
        if confidence < params["min_confidence"]:
            return None

        entry_price = closes[last_i]
        if direction == Direction.BUY:
            structural_level = base_low - atr_val * params["danger_zone_atr_mult"]
            structural_dist = entry_price - structural_level
        else:
            structural_level = base_high + atr_val * params["danger_zone_atr_mult"]
            structural_dist = structural_level - entry_price

        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        spread_price = float(ctx.spread_points) * POINT_VALUE
        tp_points = (sl_points + spread_price) * params["reward_risk_ratio"]

        if direction == Direction.BUY:
            sl_price = entry_price - sl_points
            tp_price = entry_price + tp_points
        else:
            sl_price = entry_price + sl_points
            tp_price = entry_price - tp_points

        reason = (
            f"{setup} zone_rect=[{base_low:.2f},{base_high:.2f}] leg_before={leg_before} "
            f"strong_sr_touches_ok "
            f"mtf_confirms={confirmations}/{len(self.spec.confirmation_timeframes)} "
            f"danger_zone_clear lines: entry={entry_price:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )

        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
        )
