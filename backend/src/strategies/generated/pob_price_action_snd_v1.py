import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    return _true_range(df).rolling(period, min_periods=period).mean()


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


def _is_bullish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    if not (prev_c < prev_o and c > o):
        return False
    return o <= prev_c and c >= prev_o


def _is_bearish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    if not (prev_c > prev_o and c < o):
        return False
    return o >= prev_c and c <= prev_o


def _body_candle_side(df: pd.DataFrame, i: int, min_body_ratio: float) -> tuple[bool, str]:
    rng = _range(df).iloc[i]
    if rng <= 0:
        return False, ""
    if _body(df).iloc[i] / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


def _swing_flags(df: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    highs, lows = df["high"], df["low"]
    is_high = pd.Series(False, index=df.index)
    is_low = pd.Series(False, index=df.index)
    n = len(df)
    for i in range(lookback, n - lookback):
        window_h = highs.iloc[i - lookback : i + lookback + 1]
        window_l = lows.iloc[i - lookback : i + lookback + 1]
        if highs.iloc[i] == window_h.max():
            is_high.iloc[i] = True
        if lows.iloc[i] == window_l.min():
            is_low.iloc[i] = True
    return is_high, is_low


def _count_sr_touches(
    df: pd.DataFrame,
    level_low: float,
    level_high: float,
    is_high: pd.Series,
    is_low: pd.Series,
    tolerance: float,
) -> int:
    mid = (level_low + level_high) / 2
    touches = 0
    for i in range(len(df)):
        if is_high.iloc[i] and abs(df["high"].iloc[i] - mid) <= tolerance:
            touches += 1
        elif is_low.iloc[i] and abs(df["low"].iloc[i] - mid) <= tolerance:
            touches += 1
    return touches


def _find_base(df: pd.DataFrame, atr: pd.Series, params: dict) -> dict | None:
    n = len(df)
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

        base_slice = df.iloc[base_start : base_end + 1]
        if (_range(base_slice) > current_atr * 0.6).any():
            continue

        pre_slice = df.iloc[base_start - impulse_bars : base_start]
        pre_move = pre_slice["close"].iloc[-1] - pre_slice["close"].iloc[0]
        if abs(pre_move) < current_atr * params["impulse_min_atr_mult"]:
            continue

        return {
            "base_start": base_start,
            "base_high": base_slice["high"].max(),
            "base_low": base_slice["low"].min(),
            "leg_before": "up" if pre_move > 0 else "down",
        }
    return None


def _danger_zone_breached(
    df: pd.DataFrame,
    base_low: float,
    base_high: float,
    direction: Direction,
    atr_val: float,
    mult: float,
    from_idx: int,
) -> bool:
    if direction == Direction.BUY:
        return bool((df["low"].iloc[from_idx:] < base_low - atr_val * mult).any())
    return bool((df["high"].iloc[from_idx:] > base_high + atr_val * mult).any())


def _mtf_confirms(ctx: MarketContext, tf: str, direction: Direction, params: dict) -> bool:
    df = ctx.candles.get(tf)
    lookback = int(params["confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return False
    start_i = len(df) - lookback
    for i in range(start_i, len(df)):
        if direction == Direction.BUY:
            if _is_bullish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "up":
                return True
        else:
            if _is_bearish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "down":
                return True
    return False


class PobPriceActionSnd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_price_action_snd",
            version=1,
            symbols=("XAUUSD",),
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

        atr = _atr(df, int(params["atr_period"]))
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None

        base = _find_base(df, atr, params)
        if base is None:
            return None

        last_i = len(df) - 1
        breakout_up = _is_bullish_engulfing(df, last_i)
        breakout_down = _is_bearish_engulfing(df, last_i)
        if not (breakout_up or breakout_down):
            strong, side = _body_candle_side(df, last_i, params["engulf_min_body_ratio"])
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
        sr_slice = df.iloc[sr_window_start:sr_window_end].reset_index(drop=True)
        tolerance = atr_val * params["sr_tolerance_atr_mult"]
        strong_sr = False
        if len(sr_slice) > 2 * int(params["swing_lookback"]) + 1:
            is_high, is_low = _swing_flags(sr_slice, int(params["swing_lookback"]))
            touches = _count_sr_touches(sr_slice, base_low, base_high, is_high, is_low, tolerance)
            strong_sr = touches >= int(params["sr_min_touches"])
        if not strong_sr:
            return None

        if _danger_zone_breached(
            df, base_low, base_high, direction, atr_val, params["danger_zone_atr_mult"], base["base_start"]
        ):
            return None

        confirmations = sum(
            1 for tf in self.spec.confirmation_timeframes if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        confidence = 0.5 if setup.startswith("SNRC1") else 0.45
        confidence += 0.1 * confirmations
        confidence = min(confidence, 0.95)
        if confidence < params["min_confidence"]:
            return None

        entry_price = df["close"].iloc[last_i]
        if direction == Direction.BUY:
            structural_level = base_low - atr_val * params["danger_zone_atr_mult"]
            structural_dist = entry_price - structural_level
        else:
            structural_level = base_high + atr_val * params["danger_zone_atr_mult"]
            structural_dist = structural_level - entry_price

        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        tp_points = sl_points * params["reward_risk_ratio"]

        reason = (
            f"{setup} base=[{base_low:.2f},{base_high:.2f}] leg_before={leg_before} "
            f"strong_sr_touches_ok mtf_confirms={confirmations}/{len(self.spec.confirmation_timeframes)} "
            f"danger_zone_clear"
        )

        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
        )