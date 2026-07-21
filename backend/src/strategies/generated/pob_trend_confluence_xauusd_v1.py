"""PoB trend-confluence strategy for XAUUSD — structure + S&D + QM, M5/M1.

Trend-following combination of the four PoB tools, per the Property of
Bystra doctrine ("Multi timeframe analysis is behind every great setup"):

  1. MARKET STRUCTURE (M15, resampled in-strategy from the M5 feed):
     zigzag swings labeled HH/HL/LH/LL exactly like the frontend
     `swingStructure()` (ATR-margin labeling). HH+HL = uptrend -> buys
     only; LH+LL = downtrend -> sells only. No clean trend, no zone trade.
  2. SUPPLY & DEMAND ZONES (M30, resampled): the "only 4 types of Entry
     Point" — RBR/DBR demand (buy the retest) and DBD/RBD supply (sell
     the retest) — same leg-base-leg geometry as the frontend `sndZones()`
     and the sibling pob_snd_zones_xauusd strategy. Only the trend-aligned
     zone kind is tradeable, first retest episode only.
  3. QUASIMODO (M15 structure swings): QMC-style continuation — inside a
     downtrend (H1 EMA), a pullback rally prints HH shoulder / HL neckline
     / higher-HH head, confirms on an M15 close back through the neckline,
     and the M5 retest of the left shoulder is the sell. Mirror for buys.
     Same geometry as the frontend `quasimodoLevels()`: a wick past the
     head (maximum pain level) voids the level. QM entries need only the
     H1 EMA trend (the pullback itself flips the M15 labels — that IS the
     setup), zone entries need both structure and EMA agreement.
  4. CANDLESTICK CONFIRMATION: the M5 entry bar must print a confirming
     engulfing or pin bar in the trade direction (engulfing > pin, same
     ladder as the other PoB bots), and the M1 feed must show a confirming
     engulfing/strong-body candle within the last m1_confirm_lookback
     minutes — the M1 layer is what makes this an M1+M5 bot: M5 picks the
     bar, M1 checks the final minutes actually turned.

Entry timeframe is M5 (project rule); M1 and H1 ride along as
confirmation feeds. STOP is structural: beyond the zone's distal edge or
the QM head, plus an ATR/zone-height margin, floored at half an ATR so
paper-thin bases can't produce spread-sized stops. TARGET is a fixed
tp_rr multiple of the spread-adjusted risk (tp = tp_rr * (sl + spread),
the SpreadGate formula) — tp_rr 1.8 clears configs/symbols/xauusd.yaml's
min_rr 1.5 with headroom by construction, so no signal is silently
vetoed at the broker layer.

Every signal's `reason` carries the full entry analysis — setup type,
structure labels, zone/QM rectangle, entry pattern, M1 confirmation,
retest episode and age, distance from the level in ATRs, and the
entry/sl/tp prices — so each trade in the activity log and backtest
report is self-explaining. Zone/QM rectangles and the last labeled
swings are attached as chart annotations (PriceZone / StructurePoint).
"""

import numpy as np
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
    rng = df["high"].iloc[i] - df["low"].iloc[i]
    if rng <= 0:
        return False, ""
    if abs(df["close"].iloc[i] - df["open"].iloc[i]) / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


def _is_pin_bar(
    df: pd.DataFrame, i: int, max_body_ratio: float, min_wick_body_mult: float
) -> tuple[bool, str]:
    rng = df["high"].iloc[i] - df["low"].iloc[i]
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
    """Confirming candlestick pattern at bar `i`, strongest match first
    (engulfing > pin bar > plain body candle) — same ladder as the other
    PoB bots so they all read candles identically."""
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


def _entry_pattern_at(df: pd.DataFrame, i: int, params: dict) -> tuple[str | None, str | None]:
    """Confirming pattern at bar `i` filtered by the entry_patterns tier
    ("any" | "engulf_pin" | "engulf") — single definition of "this bar can
    trigger an entry", shared by the entry bar and the episode dedup scan."""
    pattern, side = _classify_pattern(df, i, params)
    if pattern is None:
        return None, None
    tier = params.get("entry_patterns", "any")
    if tier == "engulf" and "engulfing" not in pattern:
        return None, None
    if tier == "engulf_pin" and "body_candle" in pattern:
        return None, None
    return pattern, side


def _m1_confirmation(ctx: MarketContext, direction: Direction, params: dict) -> str | None:
    """Name of the confirming M1 pattern within the last m1_confirm_lookback
    minutes (engulfing preferred, else strong body candle), or None. The M1
    layer checks the final minutes actually turned the trade's way before
    the M5 bar is trusted."""
    df = ctx.candles.get("M1")
    lookback = int(params["m1_confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return None
    want_up = direction == Direction.BUY
    best: str | None = None
    for i in range(len(df) - lookback, len(df)):
        if want_up and _is_bullish_engulfing(df, i):
            return "m1_bullish_engulfing"
        if not want_up and _is_bearish_engulfing(df, i):
            return "m1_bearish_engulfing"
        strong, side = _body_candle_side(df, i, params["m1_min_body_ratio"])
        if strong and side == ("up" if want_up else "down"):
            best = f"m1_{'bullish' if want_up else 'bearish'}_body_candle"
    return best


def _resample(df: pd.DataFrame, tf_minutes: int) -> tuple[pd.DataFrame, np.ndarray] | None:
    """Bucket M5 rows into tf_minutes OHLC bars (numpy reduceat). Returns
    (frame with open/high/low/close, int64-ns bucket END times) or None if
    nothing resamples. The last bucket is dropped unless its final M5 bar
    reaches the bucket end — structure must not form from half-built bars."""
    t_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8
    step = np.int64(tf_minutes) * 60 * 1_000_000_000
    m5_ns = np.int64(5) * 60 * 1_000_000_000
    bucket = t_ns // step
    starts = np.flatnonzero(np.concatenate(([True], bucket[1:] != bucket[:-1])))
    if len(starts) < 2:
        return None
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    ends = np.concatenate((starts[1:], [len(t_ns)])) - 1
    frame = pd.DataFrame(
        {
            "open": opens[starts],
            "high": np.maximum.reduceat(highs, starts),
            "low": np.minimum.reduceat(lows, starts),
            "close": closes[ends],
        }
    )
    end_times = (bucket[starts] + 1) * step
    if t_ns[ends[-1]] + m5_ns < end_times[-1]:  # partial last bucket
        frame = frame.iloc[:-1]
        end_times = end_times[:-1]
    if len(frame) < 2:
        return None
    return frame, end_times


def _swing_flags(highs: np.ndarray, lows: np.ndarray, wing: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows: a bar whose high (low) is the max (min) of
    the `wing`-bar window on each side — same detector as trend_structure_v2
    and the frontend swingStructure()."""
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


def _zigzag_swings(highs: np.ndarray, lows: np.ndarray, wing: int) -> list[tuple[int, float, str]]:
    """Alternating (index, price, "high"|"low") swings; same-kind runs
    collapse to the most extreme pivot so the sequence is a strict zigzag."""
    is_high, is_low = _swing_flags(highs, lows, wing)
    swings: list[tuple[int, float, str]] = []
    for i in np.flatnonzero(is_high | is_low):
        index = int(i)
        if is_high[index]:
            _push_swing(swings, index, float(highs[index]), "high")
        if is_low[index]:
            _push_swing(swings, index, float(lows[index]), "low")
    return swings


def _push_swing(swings: list[tuple[int, float, str]], index: int, price: float, kind: str) -> None:
    if swings and swings[-1][2] == kind:
        _, prev_price, _ = swings[-1]
        if (kind == "high" and price > prev_price) or (kind == "low" and price < prev_price):
            swings[-1] = (index, price, kind)
        return
    swings.append((index, price, kind))


def _label_swings(
    swings: list[tuple[int, float, str]], atr_val: float, margin_atr_mult: float
) -> list[tuple[int, float, str, str]]:
    """(index, price, kind, HH|HL|LH|LL) per swing, first-of-kind skipped —
    ATR-margin labeling identical to the frontend swingStructure(): a high
    only counts as HH if it beats the previous swing high by margin."""
    margin = atr_val * margin_atr_mult
    labeled: list[tuple[int, float, str, str]] = []
    last_high: float | None = None
    last_low: float | None = None
    for index, price, kind in swings:
        if kind == "high":
            if last_high is not None:
                labeled.append((index, price, kind, "HH" if price > last_high + margin else "LH"))
            last_high = price
        else:
            if last_low is not None:
                labeled.append((index, price, kind, "HL" if price > last_low + margin else "LL"))
            last_low = price
    return labeled


def _structure_trend(labeled: list[tuple[int, float, str, str]]) -> str:
    """"up" when the most recent labeled swing high is a HH and the most
    recent labeled swing low is a HL, "down" for LH+LL, "" otherwise —
    the classic structure read: both zigzag legs must agree on direction."""
    # Plain loop, not next(...): the runtime sandbox's builtins omit `next`.
    last_high_label: str | None = None
    last_low_label: str | None = None
    for _, _, kind, lb in reversed(labeled):
        if kind == "high" and last_high_label is None:
            last_high_label = lb
        elif kind == "low" and last_low_label is None:
            last_low_label = lb
        if last_high_label is not None and last_low_label is not None:
            break
    if last_high_label == "HH" and last_low_label == "HL":
        return "up"
    if last_high_label == "LH" and last_low_label == "LL":
        return "down"
    return ""


def _detect_zones(df: pd.DataFrame, atr: pd.Series, params: dict) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over `df` — same leg-base-leg geometry as the
    frontend `sndZones()` and pob_snd_zones_xauusd. Returns chronological
    zone dicts; retest/break tracking is done by the caller on the M5 feed."""
    n = len(df)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    def classify(i: int) -> int:
        if abs(closes[i] - opens[i]) <= base_mult * atr_filled[i]:
            return 0
        return 1 if closes[i] >= opens[i] else -1

    runs: list[list[int]] = []
    for i in range(n):
        cls = classify(i)
        if runs and runs[-1][0] == cls:
            runs[-1][2] = i
        else:
            runs.append([cls, i, i])

    def is_leg(run: list[int]) -> bool:
        cls, start, end = run
        return cls != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    merged = True
    while merged:
        merged = False
        for k in range(len(runs) - 2):
            d1, pause, d2 = runs[k], runs[k + 1], runs[k + 2]
            if d1[0] == 0 or pause[0] != 0 or d2[0] != d1[0]:
                continue
            if pause[2] - pause[1] + 1 > max_base:
                continue
            if is_leg(d1) and is_leg(d2):
                continue
            runs[k : k + 3] = [[d1[0], d1[1], d2[2]]]
            merged = True
            break

    legs = [r for r in runs if is_leg(r)]

    zones: list[dict] = []
    for k in range(len(legs) - 1):
        leg_in, leg_out = legs[k], legs[k + 1]
        base_start = leg_in[2] + 1
        base_end = leg_out[1] - 1
        base_count = base_end - base_start + 1
        if base_count < 1 or base_count > max_base:
            continue

        price_high = float(highs[base_start : base_end + 1].max())
        price_low = float(lows[base_start : base_end + 1].min())

        leg_out_up = leg_out[0] == 1
        conf_idx = None
        for j in range(leg_out[1], leg_out[2] + 1):
            cleared = (closes[j] > price_high) if leg_out_up else (closes[j] < price_low)
            if cleared:
                conf_idx = j
                break
        if conf_idx is None:
            continue

        if leg_in[0] == 1:
            pattern = "RBR" if leg_out_up else "RBD"
        else:
            pattern = "DBR" if leg_out_up else "DBD"

        zones.append(
            {
                "pattern": pattern,
                "kind": ZoneKind.DEMAND if leg_out_up else ZoneKind.SUPPLY,
                "price_high": price_high,
                "price_low": price_low,
                "base_start": base_start,
                "conf_idx": conf_idx,
                "leg_out_end": leg_out[2],
            }
        )
    return zones


def _detect_quasimodo(
    labeled: list[tuple[int, float, str, str]], closes: np.ndarray, highs: np.ndarray,
    lows: np.ndarray
) -> list[dict]:
    """QM levels from labeled structure swings — same geometry as the
    frontend `quasimodoLevels()`: bearish = HH shoulder / HL neckline /
    higher-HH head, confirmed by a close back below the neckline before any
    high exceeds the head; bullish is the mirror. Returns dicts with
    shoulder/neckline/head prices, "buy"|"sell" side, and conf_idx (the
    structure-frame bar that closed through the neckline)."""
    qms: list[dict] = []
    n = len(closes)
    for i in range(len(labeled) - 2):
        s_idx, s_price, s_kind, s_label = labeled[i]
        n_idx, n_price, n_kind, n_label = labeled[i + 1]
        h_idx, h_price, h_kind, h_label = labeled[i + 2]
        bearish = (
            (s_kind, n_kind, h_kind) == ("high", "low", "high")
            and s_label == "HH"
            and n_label == "HL"
            and h_label == "HH"
            and h_price > s_price
        )
        bullish = (
            (s_kind, n_kind, h_kind) == ("low", "high", "low")
            and s_label == "LL"
            and n_label == "LH"
            and h_label == "LL"
            and h_price < s_price
        )
        if not bearish and not bullish:
            continue
        conf_idx = None
        for j in range(h_idx + 1, n):
            if bearish and highs[j] > h_price:
                break
            if bullish and lows[j] < h_price:
                break
            if (bearish and closes[j] < n_price) or (bullish and closes[j] > n_price):
                conf_idx = j
                break
        if conf_idx is None:
            continue
        qms.append(
            {
                "side": "sell" if bearish else "buy",
                "shoulder": s_price,
                "neckline": n_price,
                "head": h_price,
                "head_idx": h_idx,
                "conf_idx": conf_idx,
            }
        )
    return qms


def _track_band_on_m5(
    band_low: float,
    band_high: float,
    void_below: float | None,
    void_above: float | None,
    start_ns: np.int64,
    m5_t_ns: np.ndarray,
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    m5_closes: np.ndarray,
) -> tuple[list[int], int | None]:
    """(retest episode start indices, first void M5 index) for a price band.
    An episode starts on the first bar whose wick re-enters [band_low,
    band_high] after being outside it. void_below / void_above are close
    levels (zone far side) or wick levels (QM head, passed as the same
    number for close+wick simplicity: a close beyond the head implies a
    wick beyond it). Episodes after the void are discarded. Vectorized —
    called once per candidate per evaluate."""
    start = int(np.searchsorted(m5_t_ns, start_ns, side="left"))
    if start >= len(m5_t_ns):
        return [], None
    in_band = (m5_lows[start:] <= band_high) & (m5_highs[start:] >= band_low)
    void = np.zeros(len(in_band), dtype=bool)
    if void_below is not None:
        void |= m5_closes[start:] < void_below
    if void_above is not None:
        void |= m5_closes[start:] > void_above
    void_idx = int(np.argmax(void)) + start if void.any() else None
    entered = in_band & ~np.concatenate(([False], in_band[:-1]))
    episode_starts = [int(i) + start for i in np.flatnonzero(entered)]
    if void_idx is not None:
        episode_starts = [i for i in episode_starts if i < void_idx]
    return episode_starts, void_idx


def _in_session(minute_of_day: int, windows: tuple) -> bool:
    if not windows:
        return True
    return any(start <= minute_of_day < end for start, end in windows)


def _active_episode(
    episodes: list[int], last_i: int, max_episodes: int, window: int
) -> tuple[int, int] | None:
    """(episode number 1-based, episode start index) if one of the first
    max_episodes retests is happening right now, else None."""
    for ep_num, ep_start in enumerate(episodes[:max_episodes], start=1):
        age = last_i - ep_start
        if 0 <= age <= window:
            return ep_num, ep_start
    return None


class PobTrendConfluenceXauusd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_trend_confluence_xauusd",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M5",
            confirmation_timeframes=("M1", "H1"),
            params={
                # Resampled analysis frames: M15 draws structure and QM
                # levels, M30 draws the S&D rectangles (the zone TF that won
                # the pob_snd_zones_xauusd sweeps — M15 zones are too thin
                # for gold's wicks).
                "structure_tf_minutes": 15,
                "zone_tf_minutes": 30,
                "atr_period": 14,
                # Structure detection — frontend swingStructure() params.
                "pivot_wing": 2,
                "structure_margin_atr_mult": 0.15,
                # Zone geometry — frontend sndZones() params.
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 1.0,
                "max_base_candles": 3,
                # Trend gates. Zone entries need the M15 structure read
                # (HH+HL for buys / LH+LL for sells) AND the H1 EMA; QM
                # entries need only the H1 EMA — the pullback that builds
                # the QM flips the M15 labels by construction.
                "htf_trend_ema_period": 50,
                # Retest gating (shared by zones and QM levels): first
                # episode only — episodes 2+ produced the loss clusters in
                # the sibling strategy's sweeps — and a confirming candle
                # must print within retest_entry_window_bars M5 bars.
                "max_retest_episodes": 1,
                "retest_entry_window_bars": 24,
                # Candlestick ladder (M5 entry bar).
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "entry_patterns": "engulf_pin",
                # M1 micro-confirmation: a confirming engulfing or strong
                # body candle in the last m1_confirm_lookback minutes.
                "require_m1_confirm": True,
                "m1_confirm_lookback": 8,
                "m1_min_body_ratio": 0.5,
                # Entry must still be near the level: close no further than
                # this many zone-TF ATRs past the proximal edge / QM level.
                "entry_max_dist_atr_mult": 1.0,
                # UTC liquidity windows (candles are stored UTC): London
                # open through the end of the NY overlap. Wider than the
                # sibling strategy's NY-only window — this bot leans on two
                # extra filters (structure trend + M1), so it can afford
                # more session and still stay selective.
                "session_windows": ((420, 1020),),
                # Risk shape — STOP beyond the structural invalidation
                # (zone distal edge or QM head) plus a volatility margin,
                # floored at half an ATR.
                "sl_buffer_atr_mult": 0.25,
                "sl_buffer_zone_frac": 0.15,
                "sl_min_atr_mult": 0.5,
                # TARGET: fixed multiple of the spread-adjusted risk
                # (SpreadGate formula, tp = tp_rr * (sl + spread)). 1.8
                # clears xauusd.yaml's min_rr 1.5 with headroom by
                # construction — nothing gets silently vetoed.
                "tp_rr": 1.8,
                "point_value": 0.01,
                "min_confidence": 0.5,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        zone_tf = int(params["zone_tf_minutes"])
        struct_tf = int(params["structure_tf_minutes"])
        atr_period = int(params["atr_period"])
        # Enough M5 history for an ATR-warm zone frame plus a few legs.
        min_bars = (atr_period + 6) * (zone_tf // 5)
        if df is None or len(df) < min_bars or "time" not in df.columns:
            return None

        last_i = len(df) - 1
        t = df["time"].iloc[last_i]
        if not _in_session(t.hour * 60 + t.minute, tuple(params["session_windows"])):
            return None

        # H1 EMA trend — the master gate for a trend-following bot: no
        # aligned higher-timeframe trend, no trade of either setup type.
        h1 = ctx.candles.get("H1")
        ema_period = int(params["htf_trend_ema_period"])
        if h1 is None or len(h1) < ema_period:
            return None
        ema_last = float(h1["close"].ewm(span=ema_period, adjust=False).mean().iloc[-1])
        h1_close = float(h1["close"].iloc[-1])
        if h1_close == ema_last:
            return None
        ema_trend = "up" if h1_close > ema_last else "down"

        # M15 structure frame: zigzag swings labeled HH/HL/LH/LL.
        struct_resampled = _resample(df, struct_tf)
        if struct_resampled is None:
            return None
        struct_frame, struct_end_ns = struct_resampled
        struct_atr = _atr(struct_frame, atr_period)
        struct_atr_val = struct_atr.iloc[-1]
        if pd.isna(struct_atr_val) or struct_atr_val <= 0:
            return None
        struct_atr_val = float(struct_atr_val)
        s_highs = struct_frame["high"].to_numpy()
        s_lows = struct_frame["low"].to_numpy()
        s_closes = struct_frame["close"].to_numpy()
        swings = _zigzag_swings(s_highs, s_lows, int(params["pivot_wing"]))
        labeled = _label_swings(swings, struct_atr_val, params["structure_margin_atr_mult"])
        if len(labeled) < 3:
            return None
        struct_trend = _structure_trend(labeled)

        # M30 zone frame + zones.
        zone_resampled = _resample(df, zone_tf)
        if zone_resampled is None:
            return None
        zone_frame, zone_end_ns = zone_resampled
        zone_atr_series = _atr(zone_frame, atr_period)
        zone_atr_val = zone_atr_series.iloc[-1]
        if pd.isna(zone_atr_val) or zone_atr_val <= 0:
            return None
        zone_atr_val = float(zone_atr_val)

        m5_t_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8
        m5_highs = df["high"].to_numpy()
        m5_lows = df["low"].to_numpy()
        m5_closes = df["close"].to_numpy()
        max_episodes = int(params["max_retest_episodes"])
        entry_window = int(params["retest_entry_window_bars"])

        # ---- Setup A: trend-aligned S&D zone retest (needs BOTH the M15
        # structure trend and the H1 EMA to agree on direction). ----
        candidate: dict | None = None
        if struct_trend == ema_trend:
            want_kind = ZoneKind.DEMAND if ema_trend == "up" else ZoneKind.SUPPLY
            for z in _detect_zones(zone_frame, zone_atr_series, params):
                if z["kind"] != want_kind:
                    continue
                far_low = z["price_low"] if z["kind"] == ZoneKind.DEMAND else None
                far_high = z["price_high"] if z["kind"] == ZoneKind.SUPPLY else None
                episodes, void_idx = _track_band_on_m5(
                    z["price_low"],
                    z["price_high"],
                    far_low,
                    far_high,
                    zone_end_ns[z["leg_out_end"]],
                    m5_t_ns,
                    m5_highs,
                    m5_lows,
                    m5_closes,
                )
                if void_idx is not None:
                    continue
                active = _active_episode(episodes, last_i, max_episodes, entry_window)
                if active is None:
                    continue
                demand = z["kind"] == ZoneKind.DEMAND
                candidate = {
                    "setup": f"{z['pattern']}-zone-retest({zone_tf}m)",
                    "direction": Direction.BUY if demand else Direction.SELL,
                    "episode": active[0],
                    "ep_start": active[1],
                    "level": z["price_high"] if demand else z["price_low"],
                    "invalidation": z["price_low"] if demand else z["price_high"],
                    "band": (z["price_low"], z["price_high"]),
                    "band_start_ns": zone_end_ns[z["base_start"]],
                    "height": z["price_high"] - z["price_low"],
                    "atr": zone_atr_val,
                    "kind": z["kind"],
                }
                break

        # ---- Setup B: Quasimodo continuation (QMC) — the pullback against
        # the H1 EMA trend prints a QM whose break re-joins the trend. Only
        # QMs on the trend's side are taken; the M15 labels are expected to
        # disagree here (the pullback IS the setup), so only the EMA gates.
        if candidate is None:
            want_side = "buy" if ema_trend == "up" else "sell"
            for qm in reversed(_detect_quasimodo(labeled, s_closes, s_highs, s_lows)):
                if qm["side"] != want_side:
                    continue
                buy = qm["side"] == "buy"
                # Retest band = shoulder..head (frontend quasimodoLevels():
                # the retest is the tag of the shoulder, a close past the
                # head — the maximum pain level — voids the setup).
                episodes, void_idx = _track_band_on_m5(
                    qm["head"] if buy else qm["shoulder"],
                    qm["shoulder"] if buy else qm["head"],
                    qm["head"] if buy else None,
                    qm["head"] if not buy else None,
                    struct_end_ns[qm["conf_idx"]],
                    m5_t_ns,
                    m5_highs,
                    m5_lows,
                    m5_closes,
                )
                if void_idx is not None:
                    continue
                active = _active_episode(episodes, last_i, max_episodes, entry_window)
                if active is None:
                    continue
                candidate = {
                    "setup": f"{'QML_INV' if buy else 'QML'}-retest({struct_tf}m)",
                    "direction": Direction.BUY if buy else Direction.SELL,
                    "episode": active[0],
                    "ep_start": active[1],
                    "level": qm["shoulder"],
                    "invalidation": qm["head"],
                    "band": (
                        (qm["head"], qm["shoulder"]) if buy else (qm["shoulder"], qm["head"])
                    ),
                    "band_start_ns": struct_end_ns[qm["head_idx"]],
                    "height": abs(qm["shoulder"] - qm["head"]),
                    "atr": struct_atr_val,
                    "kind": ZoneKind.DEMAND if buy else ZoneKind.SUPPLY,
                }
                break
        if candidate is None:
            return None

        direction = candidate["direction"]
        buy = direction == Direction.BUY

        # M5 candlestick confirmation on the entry bar, first confirming
        # candle of the episode only (dedup — later bars of the same episode
        # would double-enter the same setup).
        pattern, side = _entry_pattern_at(df, last_i, params)
        want_side = "up" if buy else "down"
        if pattern is None or side != want_side:
            return None
        for j in range(candidate["ep_start"], last_i):
            _, prev_side = _entry_pattern_at(df, j, params)
            if prev_side == want_side:
                return None

        # M1 micro-confirmation — the final minutes must have turned too.
        # A missing/too-short M1 feed is neutral, not a veto: the broker's
        # M1 history is shallow (~3 months), so early backtest stretches
        # have no M1 rows at all — vetoing there would silently zero the
        # backtest. Live trading always has M1, so the gate is fully active
        # where it matters; the reason string records which case applied.
        m1_df = ctx.candles.get("M1")
        if m1_df is None or len(m1_df) < int(params["m1_confirm_lookback"]) + 2:
            m1_pattern = "unavailable"
        else:
            m1_pattern = _m1_confirmation(ctx, direction, params)
            if params["require_m1_confirm"] and m1_pattern is None:
                return None

        close = float(m5_closes[last_i])
        dist = (close - candidate["level"]) if buy else (candidate["level"] - close)
        if dist > params["entry_max_dist_atr_mult"] * candidate["atr"]:
            return None

        # STOP beyond the structural invalidation (zone far edge / QM head)
        # plus a volatility margin, floored at half an ATR.
        buffer = max(
            candidate["atr"] * params["sl_buffer_atr_mult"],
            candidate["height"] * params["sl_buffer_zone_frac"],
        )
        if buy:
            sl_points = (close - candidate["invalidation"]) + buffer
        else:
            sl_points = (candidate["invalidation"] - close) + buffer
        sl_points = max(sl_points, candidate["atr"] * params["sl_min_atr_mult"])

        spread_price = float(ctx.spread_points) * params["point_value"]
        tp_points = (sl_points + spread_price) * params["tp_rr"]

        confidence = 0.55
        if "engulfing" in pattern:
            confidence += 0.1
        if m1_pattern is not None and "engulfing" in m1_pattern:
            confidence += 0.05
        if candidate["setup"].startswith(("RBR", "DBD")):
            confidence += 0.05  # continuation zones — PoB's strongest entries
        confidence = min(confidence, 0.9)
        if confidence < params["min_confidence"]:
            return None

        if buy:
            sl_price, tp_price = close - sl_points, close + tp_points
        else:
            sl_price, tp_price = close + sl_points, close - tp_points

        band_low, band_high = candidate["band"]
        zone = PriceZone(
            kind=candidate["kind"],
            price_low=float(band_low),
            price_high=float(band_high),
            time_start=df["time"].iloc[
                min(int(np.searchsorted(m5_t_ns, candidate["band_start_ns"])), last_i)
            ],
            time_end=t,
        )
        label_map = {"HH": StructureLabel.HH, "HL": StructureLabel.HL,
                     "LH": StructureLabel.LH, "LL": StructureLabel.LL}
        structure = tuple(
            StructurePoint(
                time=df["time"].iloc[
                    min(int(np.searchsorted(m5_t_ns, struct_end_ns[idx])), last_i)
                ],
                price=price,
                label=label_map[lb],
            )
            for idx, price, _, lb in labeled[-4:]
        )
        struct_desc = "/".join(lb for _, _, _, lb in labeled[-4:])
        reason = (
            f"{candidate['setup']} dir={direction.value} pattern={pattern} "
            f"m1_confirm={m1_pattern or 'none'} "
            f"m15_structure={struct_desc}({struct_trend or 'mixed'}) "
            f"h1_ema{ema_period}={ema_trend} "
            f"band=[{band_low:.2f},{band_high:.2f}] invalidation={candidate['invalidation']:.2f} "
            f"retest_ep={candidate['episode']} age={last_i - candidate['ep_start']} "
            f"dist_atr={dist / candidate['atr']:.2f} "
            f"sl=structure+{buffer:.2f}buf rr={params['tp_rr']} "
            f"lines: entry={close:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
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
