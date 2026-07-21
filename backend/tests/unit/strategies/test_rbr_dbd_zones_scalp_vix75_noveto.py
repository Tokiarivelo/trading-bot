"""Unit tests for `rbr_dbd_zones_scalp_vix75_noveto_v1.py` — forked from
`rbr_dbd_zones_scalp_vix75_v1.py` (same zone-detection engine, same tests for
that shared part), with the hard M5 trend veto replaced by a soft
`counter_trend_penalty` term and `spec.htf_veto=False`. The trend-filter
section below replaces the parent's "trend filter" tests (which asserted a
hard veto) with tests for the new soft-penalty behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

import src.strategies.generated.rbr_dbd_zones_scalp_vix75_noveto_v1 as mod
from src.strategies.domain.models import Direction, MarketContext, ZoneKind

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=1)


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _flat(n: int) -> list[dict]:
    return [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(n)]


def _mtf_bullish() -> pd.DataFrame:
    bars = _flat(8)
    bars.append(_bar(8, 100.4, 100.5, 99.8, 99.9))  # bearish
    bars.append(_bar(9, 99.8, 101.2, 99.7, 101.0))  # engulfs it
    return pd.DataFrame(bars)


def _mtf_bearish() -> pd.DataFrame:
    bars = _flat(8)
    bars.append(_bar(8, 100.0, 100.6, 99.9, 100.5))  # bullish
    bars.append(_bar(9, 100.6, 100.7, 99.2, 99.4))  # engulfs it
    return pd.DataFrame(bars)


PARAMS = mod.RbrDbdZonesScalpVix75Noveto().spec.params


# ---- spec -------------------------------------------------------------------


def test_spec_opts_out_of_engine_htf_veto():
    spec = mod.RbrDbdZonesScalpVix75Noveto().spec
    assert spec.htf_veto is False
    assert spec.entry_timeframe == "M1"


# ---- _detect_zones (unchanged from the parent strategy) ---------------------


def test_detect_zones_finds_rbr_with_retest():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    bars.append(_bar(i + 3, 108.0, 108.5, 107.5, 108.2))  # drift
    bars.append(_bar(i + 4, 108.2, 108.4, 104.3, 107.9))  # retest
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    rbr = [z for z in zones if z["pattern"] == "RBR"]
    assert len(rbr) == 1
    assert rbr[0]["kind"] == ZoneKind.DEMAND
    assert rbr[0]["retest_idx"] == i + 4
    assert rbr[0]["broken_idx"] is None


def test_detect_zones_finds_dbd_supply():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.0, 100.0, 95.8, 96.0))  # drop in
    bars.append(_bar(i + 1, 96.0, 96.4, 95.6, 95.9))  # base
    bars.append(_bar(i + 2, 95.9, 95.9, 91.7, 92.0))  # drop out
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    dbd = [z for z in zones if z["pattern"] == "DBD"]
    assert len(dbd) == 1
    assert dbd[0]["kind"] == ZoneKind.SUPPLY
    assert dbd[0]["price_high"] == 96.4
    assert dbd[0]["price_low"] == 95.6


def test_detect_zones_flips_polarity_on_strong_break():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    bars.append(_bar(i + 3, 108.0, 108.1, 102.9, 103.1))  # strong close through the band
    bars.append(_bar(i + 4, 103.1, 103.3, 102.8, 103.0))  # one more bar so the flip can be scanned
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    original = [z for z in zones if z["pattern"] == "RBR"]
    flipped = [z for z in zones if z["pattern"] == "RBR_flip"]
    assert len(original) == 1
    assert original[0]["broken_idx"] == i + 3
    assert len(flipped) == 1
    assert flipped[0]["kind"] == ZoneKind.SUPPLY
    assert flipped[0]["flipped"] is True
    assert flipped[0]["price_high"] == original[0]["price_high"]
    assert flipped[0]["price_low"] == original[0]["price_low"]


# ---- evaluate -----------------------------------------------------------


def _pattern_tail(rally: bool) -> list[dict]:
    if rally:
        return [
            _bar(0, 100.0, 104.2, 100.0, 104.0),  # rally in
            _bar(1, 104.0, 104.4, 103.6, 104.1),  # base
            _bar(2, 104.1, 108.3, 104.0, 108.0),  # rally out
            _bar(3, 108.2, 108.3, 107.4, 107.7),
            _bar(4, 107.7, 107.8, 106.9, 107.2),
            _bar(5, 107.2, 107.3, 106.4, 106.7),
            _bar(6, 106.7, 106.8, 106.0, 106.2),
            _bar(7, 106.1, 107.0, 104.2, 106.9),  # retest + bullish engulf
        ]
    return [
        _bar(0, 100.8, 100.8, 96.6, 96.8),  # drop in
        _bar(1, 96.8, 97.2, 96.4, 96.7),  # base
        _bar(2, 96.7, 96.8, 92.5, 92.8),  # drop out
        _bar(3, 92.6, 93.4, 92.5, 93.1),
        _bar(4, 93.1, 93.9, 93.0, 93.6),
        _bar(5, 93.6, 94.4, 93.5, 94.1),
        _bar(6, 94.1, 94.9, 94.0, 94.6),
        _bar(7, 94.7, 96.6, 93.8, 94.0),  # retest + bearish engulf
    ]


def _padded_bars(tail: list[dict]) -> pd.DataFrame:
    lookback = int(PARAMS["zone_lookback_bars"])
    n_warmup = lookback - len(tail)
    warmup = _flat(n_warmup)
    combined = warmup + tail
    for idx, bar in enumerate(combined):
        bar["time"] = START + idx * STEP
    return pd.DataFrame(combined)


def test_evaluate_buys_demand_zone_retest():
    strategy = mod.RbrDbdZonesScalpVix75Noveto()
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M1": _padded_bars(_pattern_tail(rally=True)),
            "M5": _mtf_bullish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert "RBR-retest" in signal.reason
    assert signal.sl_points > 0
    assert signal.tp_points >= PARAMS["min_rr_floor"] * signal.sl_points


def test_evaluate_sells_supply_zone_retest():
    strategy = mod.RbrDbdZonesScalpVix75Noveto()
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M1": _padded_bars(_pattern_tail(rally=False)),
            "M5": _mtf_bearish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert "DBD-retest" in signal.reason


def test_evaluate_none_without_retest():
    tail = _pattern_tail(rally=True)[:-1]
    tail.append(_bar(len(tail), 106.1, 107.0, 105.9, 106.9))  # stays away from the band
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": _padded_bars(tail), "M5": _mtf_bullish()},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx) is None


def test_evaluate_none_without_mtf_confirmation():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": _padded_bars(_pattern_tail(rally=True))},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": pd.DataFrame(_flat(10)), "M5": _mtf_bullish()},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx) is None


# ---- soft trend penalty (replaces the parent's hard trend veto) -------------


def _m5_trend(up: bool, n: int = 60) -> pd.DataFrame:
    """Long M5 frame with a clear EMA20-vs-EMA50 trend; every bar is a strong
    body candle, so MTF confirmation also passes in the trend direction."""
    bars = []
    for i in range(n):
        if up:
            o = 100.0 + i * 0.5
            bars.append(_bar(i, o, o + 0.45, o - 0.05, o + 0.4))
        else:
            o = 140.0 - i * 0.5
            bars.append(_bar(i, o, o + 0.05, o - 0.45, o - 0.4))
    return pd.DataFrame(bars)


def _m5_downtrend_with_recent_bullish_snapback() -> pd.DataFrame:
    """52 bars of a steep EMA20/50 downtrend, then a 6-bar sharp bullish
    reversal strong enough to satisfy `_mtf_confirms(BUY)` while the slower
    EMA50 hasn't caught up yet — i.e. `_trend_direction` still reads "down".
    Isolates the soft-penalty path: a genuinely counter-trend setup that a
    hard veto would kill outright but that still has a real, currently-live
    bullish MTF signal behind it."""
    bars = []
    price = 140.0
    for i in range(52):
        o, c = price, price - 0.5
        bars.append(_bar(i, o, o + 0.05, c - 0.05, c))
        price = c
    for j in range(6):
        i = 52 + j
        o, c = price, price + 0.6
        bars.append(_bar(i, o, c + 0.05, o - 0.05, c))
        price = c
    return pd.DataFrame(bars)


def test_evaluate_buys_when_m5_trend_aligned():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": _padded_bars(_pattern_tail(rally=True)), "M5": _m5_trend(up=True)},
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert "trend=up" in signal.reason
    assert "trend_aligned=True" in signal.reason


def test_evaluate_trend_filter_skipped_on_short_m5_history():
    # <= trend_slow_period bars: the filter must skip (trend=None, treated as
    # aligned, no penalty) — this is the existing buy test's setup and it
    # must keep producing a signal exactly as the parent strategy does.
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": _padded_bars(_pattern_tail(rally=True)), "M5": _mtf_bullish()},
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx)
    assert signal is not None
    assert "trend=n/a" in signal.reason
    assert "trend_aligned=True" in signal.reason


def test_evaluate_counter_trend_setup_fires_with_default_zero_penalty():
    """A genuinely counter-trend setup (M5 EMA20/50 still down, but a live
    bullish MTF signal in the last 6 bars) is exactly what the parent
    strategy's hard veto would have killed outright. The grid sweep picked
    `counter_trend_penalty=0.0` as the default (see module docstring) — trend
    is tracked and reported (`trend_aligned=False` still lands in the reason
    string for auditability) but no longer costs any confidence at all:
    0.5 continuation + 0.1 confirmation + 0.05 engulfing - 0.0 penalty =
    0.65, comfortably above `min_confidence`."""
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M1": _padded_bars(_pattern_tail(rally=True)),
            "M5": _m5_downtrend_with_recent_bullish_snapback(),
        },
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert "trend=down" in signal.reason
    assert "trend_aligned=False" in signal.reason
    assert signal.confidence == 0.65


def test_evaluate_counter_trend_setup_blocked_when_penalty_raised():
    # Same exact setup as above, only `counter_trend_penalty` raised from its
    # 0.0 default — proves the knob is real and not a no-op, even though the
    # sweep-picked default leaves it disabled.
    strategy = mod.RbrDbdZonesScalpVix75Noveto()
    strategy.spec.params["counter_trend_penalty"] = 0.30
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M1": _padded_bars(_pattern_tail(rally=True)),
            "M5": _m5_downtrend_with_recent_bullish_snapback(),
        },
        spread_points=1.0,
    )
    assert strategy.evaluate(ctx) is None


# ---- fresh-but-misaligned zone must not mask an aligned one -----------------


def test_more_recent_opposite_zone_does_not_mask_aligned_retest():
    """A fresh supply zone formed after the demand zone used to become the
    single candidate; the bullish entry candle then mismatched it and the
    valid demand retest on the same bar was lost. Now every fresh zone is
    scanned for a direction match."""
    tail = [
        # demand zone A: rally in / base [103.6, 104.4] / rally out
        _bar(0, 100.0, 104.2, 100.0, 104.0),
        _bar(1, 104.0, 104.4, 103.6, 104.1),
        _bar(2, 104.1, 108.3, 104.0, 108.0),
        # push higher to make room for a supply zone above
        _bar(3, 108.0, 114.2, 107.9, 114.0),
        # supply zone C: drop in / base [110.0, 110.8] / drop out
        _bar(4, 114.0, 114.1, 110.4, 110.6),
        _bar(5, 110.6, 110.8, 110.0, 110.4),
        _bar(6, 110.4, 110.5, 106.3, 106.5),
        # drift, staying above A's band
        _bar(7, 106.5, 107.1, 106.2, 106.8),
        # bearish pop whose wick retests C (fresh, unbroken)
        _bar(8, 107.0, 110.1, 106.0, 106.2),
        # bullish engulf whose low retests A (fresh, unbroken)
        _bar(9, 106.1, 107.3, 104.2, 107.1),
    ]
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": _padded_bars(tail), "M5": _mtf_bullish()},
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesScalpVix75Noveto().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.zone.price_low == 103.6
    assert signal.zone.price_high == 104.4
