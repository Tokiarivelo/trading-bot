"""Unit tests for `pob_trend_confluence_xauusd_v1.py` — the XAUUSD PoB
trend-confluence strategy (M15 structure + M30 S&D zones + M15 Quasimodo +
M5/M1 candlestick confirmation). Analysis frames are resampled in-strategy
from M5, so fixtures build M5 bars in groups of three (one M15 bucket each)
and the tests pin both analysis timeframes to 15 minutes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.strategies.domain.models import Direction, MarketContext, ZoneKind
from src.strategies.generated.pob_trend_confluence_xauusd_v1 import (
    PobTrendConfluenceXauusd,
    _structure_trend,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)
SPREAD_POINTS = 20.0  # * point_value 0.01 -> 0.2 price units


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
    appended by each test."""
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
    for _ in range(6):  # away from the band, M5-granular
        bars.append(_bar(len(bars), 106.8, 107.2, 106.5, 107.0))
    return bars


def _downtrend_qm_fixture() -> list[dict]:
    """Bearish Quasimodo on the M15 structure: HH shoulder 102.4, HL
    neckline 100.9, higher-HH head 103.6, confirmed by the close at 100.7
    back through the neckline. H1 (fabricated separately) is in a downtrend,
    so the QM's break re-joins the trend — a QMC sell. The shoulder retest
    is appended by each test."""
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


def _m1(confirming: str | None) -> pd.DataFrame:
    """12 M1 bars — dojis (wide range, tiny body: never a confirming
    candle), optionally ending in a bullish or bearish engulfing."""
    rows = [
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.02, "tick_volume": 10}
        for _ in range(12)
    ]
    if confirming == "up":
        rows[-2] = {"open": 100.5, "high": 100.6, "low": 100.2, "close": 100.3, "tick_volume": 10}
        rows[-1] = {"open": 100.3, "high": 100.7, "low": 100.2, "close": 100.6, "tick_volume": 10}
    elif confirming == "down":
        rows[-2] = {"open": 100.3, "high": 100.7, "low": 100.2, "close": 100.6, "tick_volume": 10}
        rows[-1] = {"open": 100.6, "high": 100.7, "low": 100.2, "close": 100.2, "tick_volume": 10}
    return pd.DataFrame(rows)


def _strategy(**param_overrides) -> PobTrendConfluenceXauusd:
    strategy = PobTrendConfluenceXauusd()
    strategy.spec.params.update(
        {
            "zone_tf_minutes": 15,
            "structure_tf_minutes": 15,
            "session_windows": (),
            "htf_trend_ema_period": 5,
            "entry_max_dist_atr_mult": 1.5,
            "require_m1_confirm": False,
        }
    )
    strategy.spec.params.update(param_overrides)
    return strategy


def _ctx(
    bars: list[dict], h1: pd.DataFrame, m1: pd.DataFrame | None = None
) -> MarketContext:
    candles: dict = {"M5": pd.DataFrame(bars), "H1": h1}
    if m1 is not None:
        candles["M1"] = m1
    return MarketContext(symbol="XAUUSD", candles=candles, spread_points=SPREAD_POINTS)


def _append_rbr_retest(bars: list[dict]) -> None:
    bars.append(_bar(len(bars), 105.0, 105.1, 104.4, 104.5))  # bearish setup bar
    bars.append(_bar(len(bars), 104.4, 105.2, 103.9, 105.0))  # bullish engulfing into band


def test_buy_signal_on_trend_aligned_rbr_retest() -> None:
    bars = _uptrend_rbr_fixture()
    _append_rbr_retest(bars)

    strategy = _strategy(require_m1_confirm=True)
    signal = strategy.evaluate(_ctx(bars, _h1("up"), _m1("up")))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.pattern == "bullish_engulfing"
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.DEMAND
    assert signal.zone.price_low == pytest.approx(103.3)
    assert signal.zone.price_high == pytest.approx(104.0)
    assert "RBR" in signal.reason
    assert "m1_bullish_engulfing" in signal.reason
    assert "m15_structure" in signal.reason
    assert signal.structure  # labeled swings attached for the chart

    # SL anchors beyond the zone's far edge (103.3) plus the volatility
    # margin — strictly deeper than the raw close-to-edge distance.
    close = 105.0
    assert signal.sl_points > close - 103.3
    # TP is a fixed multiple of the spread-adjusted risk (SpreadGate formula).
    params = strategy.spec.params
    risk = signal.sl_points + SPREAD_POINTS * params["point_value"]
    assert signal.tp_points == pytest.approx(risk * params["tp_rr"])


def test_no_signal_on_short_history() -> None:
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(30)]
    assert _strategy().evaluate(_ctx(bars, _h1("up"))) is None


def test_no_signal_when_h1_trend_misaligned() -> None:
    # Perfect RBR retest in a clean M15 uptrend — but H1 says downtrend, so
    # the demand zone is against the trend and must be skipped.
    bars = _uptrend_rbr_fixture()
    _append_rbr_retest(bars)
    assert _strategy().evaluate(_ctx(bars, _h1("down"))) is None


def test_no_signal_without_m1_confirmation() -> None:
    # Same valid setup as the positive test, but the last M1 candles never
    # print a confirming pattern — the M1 layer vetoes the entry.
    bars = _uptrend_rbr_fixture()
    _append_rbr_retest(bars)
    strategy = _strategy(require_m1_confirm=True)
    assert strategy.evaluate(_ctx(bars, _h1("up"), _m1(None))) is None


def test_signal_fires_when_m1_feed_has_no_history() -> None:
    # An absent M1 feed (e.g. backtest range before the broker's M1 history
    # starts) is neutral — the entry fires and the analysis records it.
    bars = _uptrend_rbr_fixture()
    _append_rbr_retest(bars)
    strategy = _strategy(require_m1_confirm=True)
    signal = strategy.evaluate(_ctx(bars, _h1("up")))
    assert signal is not None
    assert "m1_confirm=unavailable" in signal.reason


def test_no_signal_on_wrong_direction_pattern() -> None:
    bars = _uptrend_rbr_fixture()
    bars.append(_bar(len(bars), 104.6, 105.2, 104.5, 105.1))  # bullish setup bar
    bars.append(_bar(len(bars), 105.2, 105.3, 103.9, 104.45))  # BEARISH engulfing at demand
    assert _strategy().evaluate(_ctx(bars, _h1("up"))) is None


def test_sell_signal_on_qm_retest_in_downtrend() -> None:
    bars = _downtrend_qm_fixture()
    bars.append(_bar(len(bars), 101.4, 101.9, 101.3, 101.8))  # bullish setup bar
    bars.append(_bar(len(bars), 101.9, 102.6, 101.2, 101.3))  # bearish engulfing tagging 102.4

    signal = _strategy().evaluate(_ctx(bars, _h1("down")))

    assert signal is not None
    assert signal.direction is Direction.SELL
    assert signal.pattern == "bearish_engulfing"
    assert "QML" in signal.reason
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.SUPPLY
    assert signal.zone.price_low == pytest.approx(102.4)  # shoulder
    assert signal.zone.price_high == pytest.approx(103.6)  # head (max pain level)
    # SL anchors beyond the head plus the volatility margin.
    close = 101.3
    assert signal.sl_points > 103.6 - close


def test_no_signal_when_qm_voided_past_head() -> None:
    bars = _downtrend_qm_fixture()
    # Price closes beyond the head (103.6) after confirmation — the maximum
    # pain level is hit and the QM level is void; the later retest must not
    # trade.
    bars.append(_bar(len(bars), 101.0, 104.0, 100.9, 103.8))
    bars.append(_bar(len(bars), 103.8, 103.9, 101.4, 101.8))
    bars.append(_bar(len(bars), 101.9, 102.6, 101.2, 101.3))  # would-be entry bar
    assert _strategy().evaluate(_ctx(bars, _h1("down"))) is None


def test_structure_trend_reads_last_labels() -> None:
    up = [(0, 102.0, "high", "HH"), (1, 101.0, "low", "HL")]
    down = [(0, 102.0, "high", "LH"), (1, 100.0, "low", "LL")]
    mixed = [(0, 102.0, "high", "HH"), (1, 100.0, "low", "LL")]
    assert _structure_trend(up) == "up"
    assert _structure_trend(down) == "down"
    assert _structure_trend(mixed) == ""


def test_spec_shape() -> None:
    strategy = PobTrendConfluenceXauusd()
    assert strategy.spec.name == "pob_trend_confluence_xauusd"
    assert strategy.spec.symbols == ("XAUUSD",)
    assert strategy.spec.entry_timeframe == "M5"
    assert strategy.spec.confirmation_timeframes == ("M1", "H1")
    assert strategy.spec.params["tp_rr"] >= 1.55  # headroom over xauusd min_rr 1.5
