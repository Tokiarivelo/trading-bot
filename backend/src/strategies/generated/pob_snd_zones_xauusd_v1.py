"""PoB S&D zone-retest strategy for XAUUSD — MTF zones, M5 trigger.

Trades the "only 4 types of Entry Point" from the Property of Bystra notes:
RBR / DBR demand zones (buy the retest) and DBD / RBD supply zones (sell the
retest). Zone geometry is the same leg-base-leg detector as the frontend
`snd` chart indicator (`frontend/src/features/chart/indicators.ts`,
`sndZones()`) — keep the two in sync — run on a zone timeframe RESAMPLED
in-strategy from the M5 feed (default M15), per the PoB doctrine that the
tradeable rectangles live above the trigger chart: the zone TF draws the
rectangle, M5 only times the entry.

How a trade happens:

  - M5 candles are bucketed into zone_tf_minutes bars (numpy reduceat — no
    partial last bucket) and RBR/DBD/RBD/DBR zones detected on them. A zone
    is live once its leg-out close clears the base band, and dies when an
    M5 bar CLOSES through its far side.
  - The M5 feed tracks *retest episodes*: each distinct return of price
    into the band after the leg-out. PoB treats every tap as consuming the
    zone's resting orders, so only the first max_retest_episodes are
    tradeable, and only within retest_entry_window_bars M5 bars of the
    episode start. Entry needs a confirming M5 candle in the zone's
    direction (engulfing > pin bar > body candle) and fires only on the
    FIRST confirming candle of an episode (stateless dedup — later bars of
    the same episode would double-enter the same setup).
  - STOP is anchored on the zone rectangle: beyond the distal edge (low of
    demand / high of supply) plus a volatility margin
    max(sl_zone_buffer_atr_mult * zone-TF ATR, sl_zone_buffer_zone_frac *
    zone height), floored at sl_min_atr_mult * ATR — the ATR term absorbs
    gold's wick spikes past the edge, the height term scales the margin
    with how imprecise the base itself is, the floor keeps paper-thin bases
    from producing spread-sized stops.
  - TARGET is the next opposite zone, per PoB (buy demand -> take profit in
    front of the next supply above, and vice versa): the nearest live
    opposite zone-TF zone (H1 zones from the confirmation feed optionally
    join the pool), front-run by tp_buffer_atr_mult * ATR so the fill
    happens before that zone's own reaction. No opposite zone in view ->
    tp_fallback_rr (0 = skip the trade).
  - Because both stop and target are structural, reward:risk is variable —
    the strategy enforces its own spread-adjusted floor (min_signal_rr,
    same formula as SpreadGate: tp >= rr * (sl + spread)) with headroom
    over configs/symbols/xauusd.yaml's min_rr 1.5, so nothing is silently
    vetoed at the broker layer. A retest with no room to the next opposite
    zone is a skipped trade, not a force-fitted one.
  - Optional extras: continuation-only (RBR/DBD), H1 EMA-trend alignment,
    H1/H4 candle confirmations, rejection-close requirement, and a UTC
    session filter (gold's zone retests only respect structure when
    liquidity is in).

Engine interplay (engine code is read-only to strategies, see CLAUDE.md):
the PositionManager moves SL to breakeven at +1R and time-stops progress-less
positions after 4 hours, so this strategy deliberately trades compact
zone-TF rectangles whose targets resolve within a session, rather than tall
H1 structures that would mostly exit at breakeven. Note the live engine
serves 200 bars per timeframe — every lookback here fits inside that.

v1 defaults come from a 2025-09..2026-07 XAUUSD sweep (10 months, 62k M5
bars, ~10 grids of 8 configs each): 16 trades, 50.0% win rate, profit
factor 3.70, +4.2% on 0.5% risk/trade, max drawdown 0.9%, worst streak 4;
80% of decisive (non-breakeven) trades won; both period halves profitable
(PF 4.34 / PF 1.80). Selectivity is the edge — expect ~1-2 trades/month,
mostly NY-overlap continuation retests. Levers if more activity is wanted,
with their measured cost: session_windows (420,1020) -> ~2x trades, PF
drops to ~1.6; entry_patterns "any" -> +30% trades, PF ~2.1; and
max_retest_episodes 2 -> +25% trades, PF ~2.3.
"""

import numpy as np
import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
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
    (engulfing > pin bar > plain body candle) — same ladder as the fx/vix75
    strategies so all the PoB bots read candles identically."""
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
    ("any" | "engulf_pin" | "engulf") — the single definition of "this bar
    can trigger an entry", used both for the entry bar itself and for the
    episode dedup scan (an earlier bar counts as already-fired only if it
    passed the same tier)."""
    pattern, side = _classify_pattern(df, i, params)
    if pattern is None:
        return None, None
    tier = params.get("entry_patterns", "any")
    if tier == "engulf" and "engulfing" not in pattern:
        return None, None
    if tier == "engulf_pin" and "body_candle" in pattern:
        return None, None
    return pattern, side


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


def _resample(df: pd.DataFrame, tf_minutes: int) -> tuple[pd.DataFrame, np.ndarray] | None:
    """Bucket M5 rows into tf_minutes OHLC bars (numpy reduceat). Returns
    (frame with open/high/low/close, int64-ns bucket END times) or None if
    nothing resamples. The last bucket is dropped unless its final M5 bar
    reaches the bucket end — zones must not form from half-built bases."""
    # as_unit("ns") first: a datetime column's integer view is in whatever
    # resolution it carries (s/us/ns depending on how the frame was built).
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


def _track_on_m5(
    zone: dict,
    zone_end_ns: np.int64,
    m5_t_ns: np.ndarray,
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    m5_closes: np.ndarray,
) -> tuple[list[int], int | None]:
    """(retest episode start indices, first break M5 index) for `zone`,
    scanning M5 bars from the end of the zone-TF leg-out bar that confirmed
    it (the leg-out's own wicks still overlap the base and aren't a return).

    A retest *episode* starts on the first bar whose wick re-enters the band
    after being outside it. Episodes after the break are discarded.
    Vectorized — called once per zone per evaluate."""
    start = int(np.searchsorted(m5_t_ns, zone_end_ns, side="left"))
    if start >= len(m5_t_ns):
        return [], None
    demand = zone["kind"] == ZoneKind.DEMAND
    if demand:
        in_band = m5_lows[start:] <= zone["price_high"]
        broke = m5_closes[start:] < zone["price_low"]
    else:
        in_band = m5_highs[start:] >= zone["price_low"]
        broke = m5_closes[start:] > zone["price_high"]
    broken_idx = int(np.argmax(broke)) + start if broke.any() else None
    entered = in_band & ~np.concatenate(([False], in_band[:-1]))
    episode_starts = [int(i) + start for i in np.flatnonzero(entered)]
    if broken_idx is not None:
        episode_starts = [i for i in episode_starts if i < broken_idx]
    return episode_starts, broken_idx


def _detect_zones(df: pd.DataFrame, atr: pd.Series, params: dict) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over `df` — same leg-base-leg geometry as the
    frontend `sndZones()` (see module docstring).

    Returns chronological zone dicts:
      pattern ("RBR"|"DBD"|"RBD"|"DBR"), kind (ZoneKind), price_high,
      price_low, base_start / conf_idx / leg_out_end (integer positions in
      `df`). Retest/break tracking is NOT done here — the caller tracks
      those on the M5 feed for bar-accurate freshness.
    """
    n = len(df)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    # Pad the ATR warmup bars with the first available value so early
    # candles still classify (same padding the chart indicator does).
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    # 0 = base (small body, either color); +1/-1 = directional momentum bar.
    def classify(i: int) -> int:
        if abs(closes[i] - opens[i]) <= base_mult * atr_filled[i]:
            return 0
        return 1 if closes[i] >= opens[i] else -1

    # Runs of consecutive same-class candles, as mutable [cls, start, end].
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

    # Weak same-direction runs split by a short base run merge into one run
    # (a rally printing 0.7-ATR candles around a doji is one leg, not two
    # non-legs). Runs that BOTH already qualify as legs stay separate: the
    # pause between them is a stacked-zone base, not leg interior.
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
        # Confirmation: first leg-out candle whose close actually departs the
        # base band — a momentum run that never clears the base is still
        # consolidation, not a zone.
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


def _in_session(minute_of_day: int, windows: tuple) -> bool:
    if not windows:
        return True
    return any(start <= minute_of_day < end for start, end in windows)


def _nearest_opposite_edge(
    edges: list[tuple[float, str]], demand: bool, close: float
) -> tuple[float, str] | None:
    """Nearest opposite-zone proximal edge past the entry price, from
    (edge_price, pattern) candidates — the PoB target: buys aim at the next
    supply band above, sells at the next demand band below."""
    best: tuple[float, str] | None = None
    for edge, pattern in edges:
        if demand:
            if edge <= close:
                continue
            if best is None or edge < best[0]:
                best = (edge, pattern)
        else:
            if edge >= close:
                continue
            if best is None or edge > best[0]:
                best = (edge, pattern)
    return best


class PobSndZonesXauusd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_snd_zones_xauusd",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M5",
            confirmation_timeframes=("H1", "H4"),
            params={
                # Zone detection — same geometry params as the frontend
                # `snd` indicator, run on M5 resampled to zone_tf_minutes.
                # M30 beat M15 and H1 across the 2025-09..2026-07 sweeps
                # (M15 zones are too thin for gold's wicks, H1 stops too
                # wide for the engine's 4h time-stop).
                "zone_tf_minutes": 30,
                "atr_period": 14,
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 1.0,
                "max_base_candles": 3,
                # Entry gating (M5 trigger). A zone is tradeable during its
                # first max_retest_episodes returns into the band, and only
                # within retest_entry_window_bars M5 bars of each return's
                # start (a confirming candle needs a few bars to print).
                # First episode only: re-entering a band that already
                # rejected once re-trades a weakening zone — episodes 2+
                # produced the loss clusters in the 2025-09..2026-07 sweeps
                # (3-5 stops on the same failing zone in one day).
                "max_retest_episodes": 1,
                "retest_entry_window_bars": 24,
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 6,
                "min_confirmations": 2,
                # Which confirmation-candle tiers may trigger an entry:
                # "any" (engulfing/pin/body), "engulf_pin", or "engulf".
                # Plain body candles were the weakest tier in the sweeps
                # (dropping them: PF 2.1 -> 3.5 at ~equal trade count).
                "entry_patterns": "engulf_pin",
                "continuation_only": True,
                # "" trades both ways; "buy"/"sell" restricts to demand or
                # supply zones only (e.g. ride a secular trend one-sided).
                "allowed_direction": "",
                # 0 disables; otherwise only trade zones aligned with the
                # H1 EMA trend (close vs EMA(n)).
                "htf_trend_ema_period": 50,
                # Require the entry bar to CLOSE back outside the band in
                # the trade direction — proven rejection, not a hope-entry.
                "require_rejection_close": False,
                # Entry must still be near the zone: close no further than
                # this many zone-TF ATRs past the proximal edge.
                "entry_max_dist_atr_mult": 1.0,
                # UTC liquidity windows as (start_minute, end_minute) of the
                # day — candle timestamps are stored UTC. 12:00-17:00 UTC
                # (the NY overlap, gold's volume peak) was decisively better
                # than broader windows in the sweeps: outside it, retests
                # don't respect structure. Empty tuple = no session filter.
                "session_windows": ((720, 1020),),
                # Risk shape — STOP: distal zone edge + volatility margin
                # (terms sized off the zone-TF ATR the rectangle lives on),
                # floored so paper-thin bases can't produce spread-sized
                # stops.
                "sl_zone_buffer_atr_mult": 0.25,
                "sl_zone_buffer_zone_frac": 0.15,
                "sl_min_atr_mult": 0.5,
                # Risk shape — TARGET: nearest live opposite zone, front-run
                # by tp_buffer_atr_mult * ATR; H1 zones (confirmation feed)
                # can join the target pool. tp_fallback_rr > 0 substitutes a
                # fixed reward:risk when no opposite zone is in view, 0
                # skips the trade instead.
                "tp_buffer_atr_mult": 0.25,
                "tp_use_h1_zones": True,
                "tp_fallback_rr": 1.7,
                # Cap the target at this multiple of the spread-adjusted
                # risk (0 = no cap). A far next-zone stays the *direction*
                # of the target but the exit is brought inside it: gold
                # rarely traverses 3-4R of structure before reacting, and
                # the engine's breakeven mover scratches most of those runs
                # anyway — an uncapped structural target anti-selects
                # exactly the trades whose zone is hardest to reach (the
                # single biggest lever found in the sweeps).
                "tp_max_rr": 1.7,
                # Spread-adjusted reward:risk floor, same formula as
                # SpreadGate (tp >= rr * (sl + spread_points * point)) with
                # headroom over xauusd.yaml's min_rr 1.5 so nothing is
                # silently vetoed at the broker layer. Capped/fallback
                # targets satisfy it by construction; only structural
                # (next-zone) targets can fail it.
                "min_signal_rr": 1.55,
                "point_value": 0.01,
                "min_confidence": 0.5,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        tf_minutes = int(params["zone_tf_minutes"])
        atr_period = int(params["atr_period"])
        # Enough M5 history for an ATR-warm zone frame plus a few legs.
        min_bars = (atr_period + 6) * (tf_minutes // 5)
        if df is None or len(df) < min_bars or "time" not in df.columns:
            return None

        last_i = len(df) - 1
        t = df["time"].iloc[last_i]
        if not _in_session(t.hour * 60 + t.minute, tuple(params["session_windows"])):
            return None

        resampled = _resample(df, tf_minutes)
        if resampled is None:
            return None
        zone_frame, zone_end_ns = resampled
        atr_series = _atr(zone_frame, atr_period)
        atr_val = atr_series.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)

        zones = _detect_zones(zone_frame, atr_series, params)
        if not zones:
            return None

        m5_t_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8
        m5_highs = df["high"].to_numpy()
        m5_lows = df["low"].to_numpy()
        m5_closes = df["close"].to_numpy()

        # A live (unbroken) zone is a trade candidate while one of its first
        # max_retest_episodes returns into the band is happening right now
        # (episode started within retest_entry_window_bars of the last bar).
        # A broken zone, an untouched zone, or a spent zone all pass — no
        # trade. Live zones also feed the TP pool.
        max_episodes = int(params["max_retest_episodes"])
        entry_window = int(params["retest_entry_window_bars"])
        candidate = None
        candidate_age = None
        candidate_episode = None
        candidate_ep_start = None
        live_zones: list[dict] = []
        for z in zones:
            episodes, broken_idx = _track_on_m5(
                z, zone_end_ns[z["leg_out_end"]], m5_t_ns, m5_highs, m5_lows, m5_closes
            )
            if broken_idx is not None:
                continue
            live_zones.append(z)
            if candidate is not None:
                continue
            if params.get("continuation_only") and z["pattern"] not in ("RBR", "DBD"):
                continue
            for ep_num, ep_start in enumerate(episodes[:max_episodes], start=1):
                age = last_i - ep_start
                if 0 <= age <= entry_window:
                    candidate = z
                    candidate_age = age
                    candidate_episode = ep_num
                    candidate_ep_start = ep_start
                    break
        if candidate is None:
            return None

        demand = candidate["kind"] == ZoneKind.DEMAND
        direction = Direction.BUY if demand else Direction.SELL
        allowed = params.get("allowed_direction", "")
        if allowed and direction.value != allowed:
            return None

        # Confirmation candle on the entry bar, in the zone's direction —
        # "the best confirmation is in the engulfing candle body". Fire only
        # on the FIRST confirming candle of the episode: an earlier
        # confirming bar means this setup already signalled (dedup).
        pattern, side = _entry_pattern_at(df, last_i, params)
        want_side = "up" if demand else "down"
        if pattern is None or side != want_side:
            return None
        for j in range(candidate_ep_start, last_i):
            _, prev_side = _entry_pattern_at(df, j, params)
            if prev_side == want_side:
                return None

        close = float(df["close"].iloc[last_i])
        proximal = candidate["price_high"] if demand else candidate["price_low"]
        # Negative when the close is inside the band; the gate only rejects
        # closes that already ran too far past the zone to anchor a stop.
        dist = (close - proximal) if demand else (proximal - close)
        if dist > params["entry_max_dist_atr_mult"] * atr_val:
            return None
        if params.get("require_rejection_close") and dist <= 0:
            return None

        ema_period = int(params.get("htf_trend_ema_period", 0))
        if ema_period > 0:
            htf = ctx.candles.get(self.spec.confirmation_timeframes[0])
            if htf is None or len(htf) < ema_period:
                return None
            ema_last = htf["close"].ewm(span=ema_period, adjust=False).mean().iloc[-1]
            htf_close = htf["close"].iloc[-1]
            aligned = (htf_close > ema_last) if demand else (htf_close < ema_last)
            if not aligned:
                return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        # STOP — anchored beyond the zone rectangle's distal edge, with a
        # volatility margin (ATR wick allowance vs zone-height share,
        # whichever is larger) and an ATR floor.
        zone_height = candidate["price_high"] - candidate["price_low"]
        buffer = max(
            atr_val * params["sl_zone_buffer_atr_mult"],
            zone_height * params["sl_zone_buffer_zone_frac"],
        )
        if demand:
            sl_points = (close - candidate["price_low"]) + buffer
        else:
            sl_points = (candidate["price_high"] - close) + buffer
        sl_points = max(sl_points, atr_val * params["sl_min_atr_mult"])

        # Risk denominator the whole system prices in: SpreadGate, the cap
        # and the fallback all express reward as a multiple of (sl + spread).
        spread_price = float(ctx.spread_points) * params["point_value"]
        risk_price = sl_points + spread_price

        # TARGET — nearest live opposite zone, front-run by the buffer.
        tp_pool = [
            (z["price_low"] if demand else z["price_high"], z["pattern"])
            for z in live_zones
            if z["kind"] != candidate["kind"]
        ]
        if params.get("tp_use_h1_zones"):
            h1 = ctx.candles.get("H1")
            if h1 is not None and len(h1) >= atr_period * 2:
                h1_atr_series = _atr(h1, atr_period)
                if not h1_atr_series.dropna().empty:
                    h1_closes = h1["close"].to_numpy()
                    for z in _detect_zones(h1, h1_atr_series, params):
                        if z["kind"] == candidate["kind"]:
                            continue
                        # H1 zones already closed through (an H1 close past
                        # the far side after the leg-out) are spent targets.
                        after = h1_closes[z["leg_out_end"] + 1 :]
                        z_demand = z["kind"] == ZoneKind.DEMAND
                        broke = (
                            (after < z["price_low"]) if z_demand else (after > z["price_high"])
                        )
                        if broke.any():
                            continue
                        tp_pool.append(
                            (z["price_high"] if z_demand else z["price_low"], z["pattern"])
                        )

        target = _nearest_opposite_edge(tp_pool, demand, close)
        tp_buffer = atr_val * params["tp_buffer_atr_mult"]
        if target is not None:
            tp_points = abs(target[0] - close) - tp_buffer
            tp_desc = f"next_{'supply' if demand else 'demand'}_zone({target[1]}@{target[0]:.2f})"
        elif params["tp_fallback_rr"] > 0:
            tp_points = risk_price * params["tp_fallback_rr"]
            tp_desc = f"fallback_rr={params['tp_fallback_rr']}"
        else:
            return None
        if params["tp_max_rr"] > 0:
            capped = risk_price * params["tp_max_rr"]
            if tp_points > capped:
                tp_points = capped
                tp_desc += f"|capped@{params['tp_max_rr']}R"
        if tp_points <= 0:
            return None

        # Spread-adjusted reward:risk floor (SpreadGate formula) — a retest
        # with no room to the next opposite zone is a skipped trade, not a
        # force-fitted one. Capped/fallback targets satisfy it by
        # construction (cap and fallback are multiples of the same
        # spread-adjusted risk); only structural targets can fail here.
        rr = tp_points / risk_price
        if rr < params["min_signal_rr"]:
            return None

        continuation = candidate["pattern"] in ("RBR", "DBD")
        confidence = (0.5 if continuation else 0.45) + 0.1 * confirmations
        if "engulfing" in pattern:
            confidence += 0.05
        confidence = min(confidence, 0.9)
        if confidence < params["min_confidence"]:
            return None

        if demand:
            sl_price, tp_price = close - sl_points, close + tp_points
        else:
            sl_price, tp_price = close + sl_points, close - tp_points

        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=df["time"].iloc[
                min(int(np.searchsorted(m5_t_ns, zone_end_ns[candidate["base_start"]])), last_i)
            ],
            time_end=t,
        )
        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        reason = (
            f"{candidate['pattern']}-retest({tf_minutes}m) pattern={pattern} "
            f"zone_rect=[{candidate['price_low']:.2f},{candidate['price_high']:.2f}] "
            f"sl=zone_edge+{buffer:.2f}buf tp={tp_desc} rr={rr:.2f} "
            f"retest_ep={candidate_episode} age={candidate_age} "
            f"mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"dist_atr={dist / atr_val:.2f} zone_unbroken "
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
        )
