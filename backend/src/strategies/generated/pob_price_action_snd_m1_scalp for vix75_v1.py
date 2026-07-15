import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
    StructureLabel,
    StructurePoint,
    ZoneKind,
)


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


def _is_pin_bar(
    df: pd.DataFrame, i: int, max_body_ratio: float, min_wick_body_mult: float
) -> tuple[bool, str]:
    """Rejection candle: a small body pinned near one end of the bar's range
    with a long opposite wick — the standard SnD zone-rejection confirmation
    alongside engulfing and body candles."""
    rng = _range(df).iloc[i]
    if rng <= 0:
        return False, ""
    o, h, lo, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
    body = abs(c - o)
    if body / rng > max_body_ratio:
        return False, ""
    body_floor = max(body, rng * 0.05)
    lower_wick = min(o, c) - lo
    upper_wick = h - max(o, c)
    if lower_wick >= min_wick_body_mult * body_floor and lower_wick > upper_wick:
        return True, "up"
    if upper_wick >= min_wick_body_mult * body_floor and upper_wick > lower_wick:
        return True, "down"
    return False, ""


def _classify_pattern(df: pd.DataFrame, i: int, params: dict) -> tuple[str | None, str | None]:
    """The confirming candlestick pattern at bar `i`, strongest match first
    (engulfing > pin bar > plain body/momentum candle), and the side it
    implies. Returns (None, None) when nothing recognized matches."""
    if _is_bullish_engulfing(df, i):
        return "bullish_engulfing", "up"
    if _is_bearish_engulfing(df, i):
        return "bearish_engulfing", "down"
    is_pin, pin_side = _is_pin_bar(
        df, i, params["pin_bar_max_body_ratio"], params["pin_bar_min_wick_mult"]
    )
    if is_pin:
        return f"{'bullish' if pin_side == 'up' else 'bearish'}_pin_bar", pin_side
    strong, side = _body_candle_side(df, i, params["engulf_min_body_ratio"])
    if strong:
        return f"{'bullish' if side == 'up' else 'bearish'}_body_candle", side
    return None, None


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


def _classify_structure(
    sr_slice: pd.DataFrame,
    is_high: pd.Series,
    is_low: pd.Series,
    max_points: int,
    margin: float = 0.0,
) -> tuple[StructurePoint, ...]:
    """Labels each swing point in chronological order against the previous
    swing of the same type (HH/LH for swing highs, HL/LL for swing lows) —
    the reversal-vs-continuation read the strategy's own spec calls for.
    Informational only: exposed for chart drawing, not used to gate entries.

    `margin` (an absolute price distance, e.g. `atr_val * some_fraction`)
    requires a swing to clearly clear the prior one by more than noise before
    it's called "higher" — without it, two swings a fraction of a point apart
    (essentially a retest) flip unpredictably between HH/LH or HL/LL."""
    points: list[tuple[int, float, str]] = []
    for i in range(len(sr_slice)):
        if is_high.iloc[i]:
            points.append((i, float(sr_slice["high"].iloc[i]), "high"))
        elif is_low.iloc[i]:
            points.append((i, float(sr_slice["low"].iloc[i]), "low"))
    points.sort(key=lambda p: p[0])

    structure: list[StructurePoint] = []
    last_high: float | None = None
    last_low: float | None = None
    for idx, price, kind in points:
        if kind == "high":
            if last_high is not None:
                label = StructureLabel.HH if price > last_high + margin else StructureLabel.LH
                point = StructurePoint(time=sr_slice["time"].iloc[idx], price=price, label=label)
                structure.append(point)
            last_high = price
        else:
            if last_low is not None:
                label = StructureLabel.HL if price > last_low + margin else StructureLabel.LL
                point = StructurePoint(time=sr_slice["time"].iloc[idx], price=price, label=label)
                structure.append(point)
            last_low = price
    return tuple(structure[-max_points:])


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
        high_touch = is_high.iloc[i] and abs(df["high"].iloc[i] - mid) <= tolerance
        low_touch = is_low.iloc[i] and abs(df["low"].iloc[i] - mid) <= tolerance
        if high_touch or low_touch:
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
        # Base-bar range vs current ATR: VIX75's bar range tends to track its
        # own ATR(14) closely on any timeframe (unlike calmer FX pairs where a
        # base is visibly tighter than ATR), so a 1.0x cap keeps this a real
        # compression filter while actually firing on this instrument.
        if (_range(base_slice) > current_atr * params["base_range_atr_mult"]).any():
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


class PobPriceActionSndM1Scalp:
    """M1 scalping variant of `pob_price_action_snd for vix75` — same
    supply/demand price-action logic (base compression + impulse, engulfing/
    pin-bar/body-candle confirmation, strong S/R touch count, danger-zone
    invalidation, multi-timeframe confirmation), retimed for M1 entries:

    - entry_timeframe M1 instead of M5, confirmation_timeframes (M5, M15)
      instead of (M15, M30, H1, H4) — H1/H4 would be stale relative to a
      1-minute entry.
    - sl_atr_mult and reward_risk_ratio both cut roughly in half: a tighter
      stop is the whole point of scalping this small a balance — it shrinks
      the $ risk of one broker-minimum-lot trade (see RiskManager's min-lot
      fallback, configs/risk.yaml) so a small account can size a viable lot
      without either rejecting every trade or risking an oversized % of
      balance on the one it does take.
    - min_confirmations dropped from 2 (of 4 HTFs) to 1 (of 2) — requiring
      both of only two available confirmation frames would be a much
      stricter bar than the M5 version's "2 of 4", not an equivalent one.
    - sr_lookback_bars/confirm_lookback scaled down from M5's bar counts to
      cover a similar few-hours wall-clock window on 1-minute bars, not
      M5's literal bar count (which would span multiple days on M1 and defeat
      the point of scalping recent structure).

    NOTE — live trading caveat: the engine's live TradeEngine (see
    src/container.py) is wired to a single global entry_timeframe/
    confirmation_timeframes from configs/app.yaml's `engine:` block (M5 by
    default), shared by every active strategy — it does NOT read this
    class's own spec.entry_timeframe. Activating this strategy live today
    would never see M1 candles and would silently never signal. Backtesting
    (which builds a TradeEngine per run from *this* spec) works correctly.
    Making live per-strategy entry timeframes work is a separate engine
    change, not something a generated strategy file can fix.
    """

    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_price_action_snd_m1_scalp",
            version=1,
            symbols=("Volatility 75 Index",),
            entry_timeframe="M1",
            confirmation_timeframes=("M5", "M15"),
            params={
                "swing_lookback": 3,
                "base_max_bars": 3,
                "impulse_lookback_bars": 3,
                "base_range_atr_mult": 1.0,
                "impulse_min_atr_mult": 1.0,
                "sr_lookback_bars": 180,
                "sr_tolerance_atr_mult": 0.25,
                "sr_min_touches": 2,
                "danger_zone_atr_mult": 0.4,
                "engulf_min_body_ratio": 0.6,
                "mtf_min_body_ratio": 0.4,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "structure_max_points": 8,
                "structure_margin_atr_mult": 0.1,
                "confirm_lookback": 5,
                "min_confirmations": 1,
                "atr_period": 14,
                "sl_atr_mult": 0.7,
                "reward_risk_ratio": 1.3,
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
        pattern, side = _classify_pattern(df, last_i, params)
        if pattern is None:
            return None
        breakout_up = side == "up"
        breakout_down = side == "down"

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
        structure: tuple[StructurePoint, ...] = ()
        if len(sr_slice) > 2 * int(params["swing_lookback"]) + 1:
            is_high, is_low = _swing_flags(sr_slice, int(params["swing_lookback"]))
            touches = _count_sr_touches(sr_slice, base_low, base_high, is_high, is_low, tolerance)
            strong_sr = touches >= int(params["sr_min_touches"])
            max_points = int(params["structure_max_points"])
            structure_margin = atr_val * params["structure_margin_atr_mult"]
            structure = _classify_structure(
                sr_slice, is_high, is_low, max_points, margin=structure_margin
            )
        if not strong_sr:
            return None

        danger_mult = params["danger_zone_atr_mult"]
        if _danger_zone_breached(
            df, base_low, base_high, direction, atr_val, danger_mult, base["base_start"]
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

        entry_price = df["close"].iloc[last_i]
        if direction == Direction.BUY:
            structural_level = base_low - atr_val * params["danger_zone_atr_mult"]
            structural_dist = entry_price - structural_level
        else:
            structural_level = base_high + atr_val * params["danger_zone_atr_mult"]
            structural_dist = structural_level - entry_price

        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        tp_points = sl_points * params["reward_risk_ratio"]

        if direction == Direction.BUY:
            sl_price = entry_price - sl_points
            tp_price = entry_price + tp_points
        else:
            sl_price = entry_price + sl_points
            tp_price = entry_price - tp_points

        zone = PriceZone(
            kind=ZoneKind.DEMAND if direction == Direction.BUY else ZoneKind.SUPPLY,
            price_low=float(base_low),
            price_high=float(base_high),
            time_start=df["time"].iloc[base["base_start"]],
            time_end=df["time"].iloc[last_i],
        )

        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        reason = (
            f"{setup} pattern={pattern} zone_rect=[{base_low:.2f},{base_high:.2f}] "
            f"leg_before={leg_before} strong_sr_touches_ok "
            f"mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"danger_zone_clear lines: entry={entry_price:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )

        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=pattern,
            structure=structure,
        )
