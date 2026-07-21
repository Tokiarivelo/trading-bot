"""Unit tests for `pob_trend_confluence_xauusd_v2.py` — the M1-only
aggressive variant of the XAUUSD PoB trend-confluence strategy. Analysis
frames (M15 structure, S&D zones, QM levels) are still resampled from the
M5 confirmation feed, but retest episodes and the entry trigger live on the
M1 entry feed — so fixtures build an M5 analysis staircase (in groups of
three bars = one M15 bucket, both analysis timeframes pinned to 15 minutes)
plus a separate timed M1 feed that performs the retest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.strategies.domain.models import Direction, MarketContext, ZoneKind
from src.strategies.generated.pob_trend_confluence_xauusd_v2 import (
    PobTrendConfluenceXauusdV2,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)
M1_STEP = timedelta(minutes=1)
SPREAD_POINTS = 20.0  # * point_value 0.01 -> 0.2 price units

PARKED_HIGH = (106.8, 107.2, 106.5, 107.0)  # above the RBR band, never in it
PARKED_LOW = (100.7, 101.0, 100.4, 100.8)  # below the QM shoulder, never in it


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _bucket(bars: list[dict], o: float, h: float, low: float, c: float) -> None:
    """Append one M15 bucket as three identical M5 bars (M15 open = first
    bar's open, close = last bar's close, high/low = shared range)."""
    i = len(bars)
    for j in range(3):
        bars.append(_bar(i + j, o, h, low, c))


def _uptrend_rbr_fixture() -> list[dict]:
    """M15 structure staircase (HH at 103.0, HL at 101.5 — clean uptrend)
    followed by rally - base - rally: an RBR demand zone with band
    [103.3, 104.0], then six M5 bars parked above the band. The retest is
    performed by the M1 feed each test builds."""
    bars: list[dict] = []
    for _ in range(14):  # ATR warmup
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 101.0, 100.0, 100.6)
    _bucket(bars, 100.6, 102.0, 100.5, 101.6)  # pivot high A=102.0 (HH)
    _bucket(bars, 101.6, 101.7, 100.8, 101.0)
    _bucket(bars, 101.0, 101.2, 100.4, 100.6)  # pivot low B=100.4 (HL)
    _bucket(bars, 100.6, 102.3, 100.5, 102.0)
    _bucket(bars, 102.0, 103.0, 101.8, 102.7)  # pivot high C=103.0 (HH)
    _bucket(bars, 102.7, 102.8, 101.9, 102.3)
    _bucket(bars, 102.3, 102.4, 101.5, 101.9)  # pivot low D=101.5 (HL)
    _bucket(bars, 101.9, 103.5, 101.8, 103.4)  # leg-in
    _bucket(bars, 103.4, 104.0, 103.3, 103.8)  # base -> zone band [103.3, 104.0]
    _bucket(bars, 103.8, 105.6, 103.7, 105.4)  # leg-out (105.4 > 104.0 confirms)
    _bucket(bars, 105.4, 107.1, 105.3, 107.0)
    for _ in range(6):  # away from the band
        bars.append(_bar(len(bars), *PARKED_HIGH))
    return bars


def _downtrend_qm_fixture() -> list[dict]:
    """Bearish Quasimodo on the M15 structure: HH shoulder 102.4, HL
    neckline 100.9, higher-HH head 103.6, confirmed by the close at 100.7
    back through the neckline. H1 (fabricated separately) is in a downtrend,
    so the QM's break re-joins the trend — a QMC sell. The shoulder retest
    is performed by the M1 feed each test builds."""
    bars: list[dict] = []
    for _ in range(14):  # ATR warmup
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 101.6, 100.2, 101.4)
    _bucket(bars, 101.4, 102.4, 101.2, 102.2)  # shoulder pivot high 102.4 (HH)
    _bucket(bars, 102.2, 102.3, 101.3, 101.6)
    _bucket(bars, 101.6, 101.8, 100.9, 101.2)  # neckline pivot low 100.9 (HL)
    _bucket(bars, 101.2, 103.0, 101.1, 102.8)
    _bucket(bars, 102.8, 103.6, 102.0, 103.2)  # head pivot high 103.6 (HH > shoulder)
    _bucket(bars, 103.2, 103.3, 101.8, 102.0)
    _bucket(bars, 102.0, 102.1, 100.5, 100.7)  # closes 100.7 < neckline -> confirmed
    _bucket(bars, 100.7, 101.0, 100.4, 100.8)  # parked below the shoulder
    return bars


def _h1(trend: str, rows: int = 12) -> pd.DataFrame:
    if trend == "up":
        closes = [100.0 + i for i in range(rows)]
    else:
        closes = [100.0 + rows - i for i in range(rows)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
        }
    )


def _m1_feed(m5_bars: list[dict], rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """M1 frame whose bars start right after the last M5 bar, one minute
    apart — every zone/QM confirmation time therefore precedes the whole
    M1 feed, so retest tracking scans it from the first row."""
    start = START + len(m5_bars) * STEP
    return pd.DataFrame(
        {
            "time": [start + k * M1_STEP for k in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "tick_volume": [10] * len(rows),
        }
    )


def _strategy(**param_overrides) -> PobTrendConfluenceXauusdV2:
    strategy = PobTrendConfluenceXauusdV2()
    strategy.spec.params.update(
        {
            "zone_tf_minutes": 15,
            "structure_tf_minutes": 15,
            "htf_trend_ema_period": 5,
            "entry_max_dist_atr_mult": 1.5,
        }
    )
    strategy.spec.params.update(param_overrides)
    return strategy


def _ctx(m5_bars: list[dict], h1: pd.DataFrame, m1: pd.DataFrame) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD",
        candles={"M1": m1, "M5": pd.DataFrame(m5_bars), "H1": h1},
        spread_points=SPREAD_POINTS,
    )


# M1 retest of the RBR band [103.3, 104.0]: a bearish setup bar parked just
# above the band, then a bullish engulfing whose wick dips into it.
RBR_SETUP_BAR = (105.0, 105.1, 104.4, 104.5)
RBR_ENTRY_ENGULF = (104.4, 105.2, 103.9, 105.0)
# In-band bearish body candle that starts an episode without printing a
# confirming *buy* pattern — used to consume episode 1.
RBR_EP_CONSUMER = (105.9, 106.0, 103.9, 104.0)


def test_buy_signal_on_trend_aligned_rbr_retest() -> None:
    m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])

    strategy = _strategy()
    signal = strategy.evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.pattern == "bullish_engulfing"
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.DEMAND
    assert signal.zone.price_low == pytest.approx(103.3)
    assert signal.zone.price_high == pytest.approx(104.0)
    assert "RBR" in signal.reason
    assert "retest_ep=1" in signal.reason
    assert "m15_structure" in signal.reason
    assert signal.structure  # labeled swings attached for the chart

    # SL anchors beyond the zone's far edge (103.3) plus the volatility
    # margin — strictly deeper than the raw close-to-edge distance.
    close = RBR_ENTRY_ENGULF[3]
    assert signal.sl_points > close - 103.3
    # TP is a fixed multiple of the spread-adjusted risk (SpreadGate formula).
    params = strategy.spec.params
    risk = signal.sl_points + SPREAD_POINTS * params["point_value"]
    assert signal.tp_points == pytest.approx(risk * params["tp_rr"])


def test_body_candle_qualifies_as_entry_pattern() -> None:
    # entry_patterns="any": a strong bullish body candle (not an engulfing,
    # not a pin bar) dipping into the band is a valid v2 entry trigger.
    m5 = _uptrend_rbr_fixture()
    body_candle = (104.2, 105.0, 103.95, 104.95)
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [body_candle])

    signal = _strategy().evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.pattern == "bullish_body_candle"


def test_second_retest_episode_allowed() -> None:
    # Episode 1 is consumed by a bearish dip whose entry window (120 M1
    # bars) fully expires; the second touch of the band is episode 2 and
    # still tradeable in v2 (v1 allowed only one episode).
    m5 = _uptrend_rbr_fixture()
    rows = (
        [PARKED_HIGH] * 10
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF]
    )
    m1 = _m1_feed(m5, rows)

    signal = _strategy().evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert "retest_ep=2" in signal.reason


def test_third_retest_episode_rejected() -> None:
    # Two stale episodes already exist — the third touch is beyond
    # max_retest_episodes=2 and must not trade.
    m5 = _uptrend_rbr_fixture()
    rows = (
        [PARKED_HIGH] * 10
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF]
    )
    m1 = _m1_feed(m5, rows)

    assert _strategy().evaluate(_ctx(m5, _h1("up"), m1)) is None


def test_no_signal_on_short_history() -> None:
    short_m5 = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(30)]
    full_m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(full_m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])

    # Short analysis feed.
    assert _strategy().evaluate(_ctx(short_m5, _h1("up"), m1)) is None
    # Short entry feed.
    short_m1 = _m1_feed(full_m5, [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])
    assert _strategy().evaluate(_ctx(full_m5, _h1("up"), short_m1)) is None


def test_no_signal_when_h1_trend_misaligned() -> None:
    # Perfect RBR retest in a clean M15 uptrend — but H1 says downtrend, so
    # the demand zone is against the trend and must be skipped.
    m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])
    assert _strategy().evaluate(_ctx(m5, _h1("down"), m1)) is None


def test_no_signal_on_wrong_direction_pattern() -> None:
    # A BEARISH engulfing tagging the demand band is not a buy trigger.
    m5 = _uptrend_rbr_fixture()
    bullish_setup = (104.6, 105.2, 104.5, 105.1)
    bearish_engulf = (105.2, 105.3, 103.9, 104.45)
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [bullish_setup, bearish_engulf])
    assert _strategy().evaluate(_ctx(m5, _h1("up"), m1)) is None


def test_sell_signal_on_qm_retest_in_downtrend() -> None:
    m5 = _downtrend_qm_fixture()
    bullish_setup = (101.4, 101.9, 101.3, 101.8)
    bearish_engulf = (101.9, 102.6, 101.2, 101.3)  # tags the 102.4 shoulder
    m1 = _m1_feed(m5, [PARKED_LOW] * 10 + [bullish_setup, bearish_engulf])

    signal = _strategy().evaluate(_ctx(m5, _h1("down"), m1))

    assert signal is not None
    assert signal.direction is Direction.SELL
    assert signal.pattern == "bearish_engulfing"
    assert "QML" in signal.reason
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.SUPPLY
    assert signal.zone.price_low == pytest.approx(102.4)  # shoulder
    assert signal.zone.price_high == pytest.approx(103.6)  # head (max pain level)
    # SL anchors beyond the head plus the volatility margin.
    close = bearish_engulf[3]
    assert signal.sl_points > 103.6 - close


def test_no_signal_when_qm_voided_past_head() -> None:
    # An M1 close beyond the head (103.6) after confirmation hits the
    # maximum pain level and voids the QM — the later retest must not trade.
    m5 = _downtrend_qm_fixture()
    void_bar = (101.0, 104.0, 100.9, 103.8)
    pullback = (103.8, 103.9, 101.4, 101.8)
    bullish_setup = (101.4, 101.9, 101.3, 101.8)
    bearish_engulf = (101.9, 102.6, 101.2, 101.3)
    m1 = _m1_feed(
        m5, [PARKED_LOW] * 10 + [void_bar, pullback, bullish_setup, bearish_engulf]
    )
    assert _strategy().evaluate(_ctx(m5, _h1("down"), m1)) is None


def test_spec_shape() -> None:
    strategy = PobTrendConfluenceXauusdV2()
    assert strategy.spec.name == "pob_trend_confluence_xauusd"
    assert strategy.spec.version == 2
    assert strategy.spec.symbols == ("XAUUSD",)
    assert strategy.spec.entry_timeframe == "M1"
    assert strategy.spec.confirmation_timeframes == ("M5", "H1")
    assert strategy.spec.params["tp_rr"] >= 1.55  # headroom over xauusd min_rr 1.5
    assert strategy.spec.params["session_windows"] == ()  # trades all sessions
    assert strategy.spec.params["max_retest_episodes"] == 2
