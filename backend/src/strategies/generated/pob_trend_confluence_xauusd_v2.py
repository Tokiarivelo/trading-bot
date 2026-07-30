"""PoB trend-confluence strategy for XAUUSD v2 — M1-only aggressive variant.

Same Property-of-Bystra toolset as v1 (M15 market structure, M30 supply &
demand zones, M15 Quasimodo continuation, H1 EMA trend gate — the analysis
frames are still resampled in-strategy from the M5 confirmation feed), but
the trading loop moves entirely to M1 and every throttle that limited v1's
trade count is opened up:

  - ENTRY TIMEFRAME IS M1: the bot is evaluated on every M1 close instead
    of every M5 close (5x more entry checks), the entry trigger is the M1
    candle itself, and zone/QM retest episodes are tracked on the M1 feed
    so intrabar touches v1 could not see become tradeable retests. There
    is no separate micro-confirmation layer — the entry bar IS the M1
    confirmation.
  - ALL SESSIONS: no London/NY window — session_windows is empty, the bot
    trades around the clock.
  - TWO RETEST EPISODES per level instead of one, each with its own
    first-confirming-candle entry (still deduped inside an episode so the
    same touch can't machine-gun entries).
  - ANY CONFIRMING PATTERN: engulfing, pin bar, or strong body candle all
    qualify (v1 required engulfing/pin).

Risk shape is unchanged from v1 — STOP beyond the structural invalidation
(zone distal edge or QM head) plus an ATR/zone-height margin floored at
half an ATR, TARGET a fixed tp_rr multiple of the spread-adjusted risk
(tp = tp_rr * (sl + spread), the SpreadGate formula; tp_rr 1.8 clears
configs/symbols/xauusd.yaml's min_rr 1.5 with headroom by construction).

Position sizing, max positions, trades-per-day, and the daily-loss breaker
remain engine-level concerns owned by configs/risk.yaml — this strategy
only decides how often it signals; it cannot and does not route around
those caps.

Every signal's `reason` carries the full entry analysis — setup type,
structure labels, zone/QM rectangle, entry pattern, retest episode and
age (in M1 bars), distance from the level in ATRs, and the entry/sl/tp
prices — so each trade in the activity log and backtest report is
self-explaining. Zone/QM rectangles and the last labeled swings are
attached as chart annotations (PriceZone / StructurePoint).
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


def _classify_bars(
    closes: np.ndarray, opens: np.ndarray, atr_filled: np.ndarray, base_mult: float
) -> np.ndarray:
    """Vectorized per-bar classification: 0 = base (small body, either
    color); +1/-1 = directional momentum bar. Split out of `_detect_zones`
    so `PobTrendConfluenceXauusdV2._detect_zones_cached` can reuse it —
    keep the two in sync (same rule as the sibling `pob_snd_zones_xauusd_v1`)."""
    body = np.abs(closes - opens)
    return np.where(body <= base_mult * atr_filled, 0, np.where(closes >= opens, 1, -1))


def _build_runs_from(classes: np.ndarray, start: int, stop: int | None = None) -> list[list[int]]:
    """Group `classes[start:stop]` into consecutive-same-class runs, as
    mutable [cls, start, end] triples of absolute positions."""
    end_pos = len(classes) if stop is None else stop
    runs: list[list[int]] = []
    for i in range(start, end_pos):
        cls = int(classes[i])
        if runs and runs[-1][0] == cls:
            runs[-1][2] = i
        else:
            runs.append([cls, i, i])
    return runs


def _coalesce_adjacent_runs(runs: list[list[int]]) -> list[list[int]]:
    """Re-join directly-adjacent same-class runs at a splice seam (used
    when a cached run-list prefix is stitched to freshly-built head/tail
    segments in `PobTrendConfluenceXauusdV2._detect_zones_cached`) — see
    `pob_snd_zones_xauusd_v1._coalesce_adjacent_runs` for the full
    rationale."""
    out: list[list[int]] = []
    for r in runs:
        if out and out[-1][0] == r[0] and out[-1][2] + 1 == r[1]:
            out[-1][2] = r[2]
        else:
            out.append(list(r))
    return out


def _make_is_leg(closes: np.ndarray, opens: np.ndarray, atr_filled: np.ndarray, leg_mult: float):
    def is_leg(run: list[int]) -> bool:
        cls, start, end = run
        return cls != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    return is_leg


def _merge_weak_runs(runs: list[list[int]], is_leg, max_base: int) -> list[list[int]]:
    """Fixed-point pass absorbing a short same-color-bracketed base run into
    one leg. Mutates and returns `runs` — see
    `pob_snd_zones_xauusd_v1._merge_weak_runs` for why re-scanning an
    already-final cached prefix is what keeps the incremental cache exact."""
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
    return runs


def _build_zones_from_runs(
    runs: list[list[int]],
    is_leg,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    max_base: int,
) -> list[dict]:
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


def _detect_zones(df: pd.DataFrame, atr: pd.Series, params: dict) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over `df` — same leg-base-leg geometry as the
    frontend `sndZones()` and pob_snd_zones_xauusd. Returns chronological
    zone dicts; retest/break tracking is done by the caller on the M1 feed.

    Pure full recompute, O(n) classify + O(runs^2)-ish merge every call —
    the stateless ground truth. `PobTrendConfluenceXauusdV2.evaluate()`
    uses the incremental, cache-backed `_detect_zones_cached` instead for
    its own (repeatedly-called, sliding-window) zone_frame; this function
    stays untouched for any other one-shot use.
    """
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

    classes = _classify_bars(closes, opens, atr_filled, base_mult)
    runs = _build_runs_from(classes, 0)
    is_leg = _make_is_leg(closes, opens, atr_filled, leg_mult)
    runs = _merge_weak_runs(runs, is_leg, max_base)
    return _build_zones_from_runs(runs, is_leg, highs, lows, closes, max_base)


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


def _track_band(
    band_low: float,
    band_high: float,
    void_below: float | None,
    void_above: float | None,
    start_ns: np.int64,
    t_ns: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> tuple[list[int], int | None]:
    """(retest episode start indices, first void bar index) for a price band,
    tracked on the entry feed — M1 here, so intrabar touches the M5 version
    of this bot could not see become their own retest episodes. An episode
    starts on the first bar whose wick re-enters [band_low, band_high] after
    being outside it. void_below / void_above are close levels (zone far
    side) or wick levels (QM head). Episodes after the void are discarded.
    Vectorized — called once per candidate per evaluate."""
    start = int(np.searchsorted(t_ns, start_ns, side="left"))
    if start >= len(t_ns):
        return [], None
    in_band = (lows[start:] <= band_high) & (highs[start:] >= band_low)
    void = np.zeros(len(in_band), dtype=bool)
    if void_below is not None:
        void |= closes[start:] < void_below
    if void_above is not None:
        void |= closes[start:] > void_above
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


class PobTrendConfluenceXauusdV2:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_trend_confluence_xauusd",
            version=2,
            symbols=("XAUUSD",),
            entry_timeframe="M1",
            confirmation_timeframes=("M5", "H1"),
            params={
                # Resampled analysis frames (from the M5 confirmation feed,
                # exactly like v1): M15 draws structure and QM levels, M30
                # draws the S&D rectangles.
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
                # Trend gates, unchanged from v1: zone entries need the M15
                # structure read AND the H1 EMA; QM entries need only the
                # H1 EMA.
                "htf_trend_ema_period": 50,
                # Retest gating on the M1 feed. Two episodes per level (v1
                # allowed one) and a window equal to v1's 24 M5 bars
                # expressed in M1 bars — the max-trade-count version keeps
                # the same wall-clock patience, it just sees more retests.
                "max_retest_episodes": 2,
                "retest_entry_window_bars": 120,
                # Candlestick ladder (M1 entry bar). "any" also accepts a
                # strong body candle — v1 required engulfing/pin.
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "entry_patterns": "any",
                # No session filter: the max-trade-count version trades all
                # hours (v1 traded London open .. end of NY overlap only).
                "session_windows": (),
                # Entry must still be near the level: close no further than
                # this many zone-TF ATRs past the proximal edge / QM level.
                "entry_max_dist_atr_mult": 1.0,
                # Risk shape — unchanged from v1: STOP beyond the structural
                # invalidation (zone distal edge or QM head) plus a
                # volatility margin, floored at half an ATR.
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
        # Incremental zone-detection cache for `_detect_zones_cached`, keyed
        # on zone-TF bucket END timestamps (int64 ns) — identical design to
        # `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._zone_cache` (see that
        # class's `_detect_zones_cached` docstring for the full rationale).
        # None until the first successful detection; reset to None whenever
        # a call can't produce a usable ATR.
        self._zone_cache: dict[str, object] | None = None

    def _detect_zones_cached(
        self,
        zone_frame: pd.DataFrame,
        zone_end_ns: np.ndarray,
        atr: pd.Series,
        params: dict,
    ) -> list[dict]:
        """Incremental, bit-identical replacement for module-level
        `_detect_zones(zone_frame, atr, params)`, exploiting that
        `evaluate()`'s Setup A branch calls this with a *sliding* window
        over the same zone-TF bucket grid every time it runs (the M30 frame
        resampled from the M5 confirmation feed — see `__init__`). Not
        every `evaluate()` call reaches this method (Setup A only runs
        when `struct_trend == ema_trend`), so gaps between calls are
        common; the prefix-overlap check below already treats any gap it
        can't bridge as a cold start (falls back to a full recompute), so
        correctness doesn't depend on being called every bar — only the
        steady-state savings does.

        Identical algorithm to
        `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached`
        (see that docstring for the full four-step design and the
        pre-merge-vs-post-merge correctness argument): cache raw
        (pre-merge) runs keyed on `zone_end_ns`, translate them into this
        call's positions via `searchsorted`, keep only a contiguous
        prefix satisfying `atr_period <= start` and `end <= overlap_len -
        2`, re-run classify+group only over the uncovered head/tail, then
        run the merge-loop and leg/zone-building fresh, in full, over the
        spliced raw run list every call.

        Bit-identical to `_detect_zones(zone_frame, atr, params)` on every
        call — proven by
        `tests/unit/strategies/test_pob_trend_confluence_xauusd_v2.py::test_incremental_cache_matches_full_recompute_every_step`.
        """
        n = len(zone_frame)
        valid_atr = atr.dropna()
        if valid_atr.empty:
            self._zone_cache = None
            return []
        atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

        opens = zone_frame["open"].to_numpy()
        highs = zone_frame["high"].to_numpy()
        lows = zone_frame["low"].to_numpy()
        closes = zone_frame["close"].to_numpy()

        base_mult = params["base_body_atr_mult"]
        leg_mult = params["leg_travel_atr_mult"]
        max_base = int(params["max_base_candles"])
        atr_period = int(params["atr_period"])

        classes = _classify_bars(closes, opens, atr_filled, base_mult)

        candidates: list[list[int]] = []
        cache = self._zone_cache
        if cache is not None and n:
            old_ends = cache["ends"]
            if len(old_ends):
                p = int(np.searchsorted(old_ends, zone_end_ns[0]))
                if 0 <= p < len(old_ends):
                    overlap_len = min(len(old_ends) - p, n)
                    if np.array_equal(
                        old_ends[p : p + overlap_len], zone_end_ns[:overlap_len]
                    ):
                        for cls, s_ns, e_ns in cache["raw_runs"]:
                            s = int(np.searchsorted(zone_end_ns, s_ns))
                            e = int(np.searchsorted(zone_end_ns, e_ns))
                            ok = (
                                s < len(zone_end_ns)
                                and e < len(zone_end_ns)
                                and zone_end_ns[s] == s_ns
                                and zone_end_ns[e] == e_ns
                                and atr_period <= s
                                and e <= overlap_len - 2
                            )
                            if not ok:
                                if candidates:
                                    break
                                continue
                            candidates.append([cls, s, e])

        if candidates:
            head_runs = _build_runs_from(classes, 0, stop=candidates[0][1])
            tail_runs = _build_runs_from(classes, candidates[-1][2] + 1)
            raw_runs = _coalesce_adjacent_runs(head_runs + candidates + tail_runs)
        else:
            raw_runs = _build_runs_from(classes, 0)

        is_leg = _make_is_leg(closes, opens, atr_filled, leg_mult)
        # `_merge_weak_runs` mutates its input in place — always give it a
        # fresh copy so `raw_runs` (what gets cached) stays pre-merge.
        merged_runs = _merge_weak_runs([list(r) for r in raw_runs], is_leg, max_base)
        zones = _build_zones_from_runs(merged_runs, is_leg, highs, lows, closes, max_base)

        self._zone_cache = {
            "ends": zone_end_ns.copy(),
            "raw_runs": [[cls, int(zone_end_ns[s]), int(zone_end_ns[e])] for cls, s, e in raw_runs],
        }
        return zones

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        m1 = ctx.candles.get(self.spec.entry_timeframe)
        m5 = ctx.candles.get("M5")
        zone_tf = int(params["zone_tf_minutes"])
        struct_tf = int(params["structure_tf_minutes"])
        atr_period = int(params["atr_period"])
        # Enough M5 history for an ATR-warm zone frame plus a few legs, and
        # enough M1 bars for pattern context around the current retest.
        min_m5_bars = (atr_period + 6) * (zone_tf // 5)
        if m5 is None or len(m5) < min_m5_bars or "time" not in m5.columns:
            return None
        if m1 is None or len(m1) < 10 or "time" not in m1.columns:
            return None

        last_i = len(m1) - 1
        t = m1["time"].iloc[last_i]
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
        struct_resampled = _resample(m5, struct_tf)
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
        zone_resampled = _resample(m5, zone_tf)
        if zone_resampled is None:
            return None
        zone_frame, zone_end_ns = zone_resampled
        zone_atr_series = _atr(zone_frame, atr_period)
        zone_atr_val = zone_atr_series.iloc[-1]
        if pd.isna(zone_atr_val) or zone_atr_val <= 0:
            return None
        zone_atr_val = float(zone_atr_val)

        # Retest tracking runs on the M1 feed — the defining change of v2.
        m1_t_ns = pd.DatetimeIndex(m1["time"]).as_unit("ns").asi8
        m1_highs = m1["high"].to_numpy()
        m1_lows = m1["low"].to_numpy()
        m1_closes = m1["close"].to_numpy()
        max_episodes = int(params["max_retest_episodes"])
        entry_window = int(params["retest_entry_window_bars"])

        # ---- Setup A: trend-aligned S&D zone retest (needs BOTH the M15
        # structure trend and the H1 EMA to agree on direction). ----
        candidate: dict | None = None
        if struct_trend == ema_trend:
            want_kind = ZoneKind.DEMAND if ema_trend == "up" else ZoneKind.SUPPLY
            for z in self._detect_zones_cached(zone_frame, zone_end_ns, zone_atr_series, params):
                if z["kind"] != want_kind:
                    continue
                far_low = z["price_low"] if z["kind"] == ZoneKind.DEMAND else None
                far_high = z["price_high"] if z["kind"] == ZoneKind.SUPPLY else None
                episodes, void_idx = _track_band(
                    z["price_low"],
                    z["price_high"],
                    far_low,
                    far_high,
                    zone_end_ns[z["leg_out_end"]],
                    m1_t_ns,
                    m1_highs,
                    m1_lows,
                    m1_closes,
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
                episodes, void_idx = _track_band(
                    qm["head"] if buy else qm["shoulder"],
                    qm["shoulder"] if buy else qm["head"],
                    qm["head"] if buy else None,
                    qm["head"] if not buy else None,
                    struct_end_ns[qm["conf_idx"]],
                    m1_t_ns,
                    m1_highs,
                    m1_lows,
                    m1_closes,
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

        # M1 candlestick confirmation on the entry bar, first confirming
        # candle of the episode only (dedup — later bars of the same episode
        # would double-enter the same setup; a second episode gets its own
        # entry, per max_retest_episodes).
        pattern, side = _entry_pattern_at(m1, last_i, params)
        want_side = "up" if buy else "down"
        if pattern is None or side != want_side:
            return None
        for j in range(candidate["ep_start"], last_i):
            _, prev_side = _entry_pattern_at(m1, j, params)
            if prev_side == want_side:
                return None

        close = float(m1_closes[last_i])
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
        elif "pin_bar" in pattern:
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
            time_start=m1["time"].iloc[
                min(int(np.searchsorted(m1_t_ns, candidate["band_start_ns"])), last_i)
            ],
            time_end=t,
        )
        label_map = {"HH": StructureLabel.HH, "HL": StructureLabel.HL,
                     "LH": StructureLabel.LH, "LL": StructureLabel.LL}
        structure = tuple(
            StructurePoint(
                time=m1["time"].iloc[
                    min(int(np.searchsorted(m1_t_ns, struct_end_ns[idx])), last_i)
                ],
                price=price,
                label=label_map[lb],
            )
            for idx, price, _, lb in labeled[-4:]
        )
        struct_desc = "/".join(lb for _, _, _, lb in labeled[-4:])
        reason = (
            f"{candidate['setup']} dir={direction.value} pattern=m1_{pattern} "
            f"m15_structure={struct_desc}({struct_trend or 'mixed'}) "
            f"h1_ema{ema_period}={ema_trend} "
            f"band=[{band_low:.2f},{band_high:.2f}] invalidation={candidate['invalidation']:.2f} "
            f"retest_ep={candidate['episode']} age_m1={last_i - candidate['ep_start']} "
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
