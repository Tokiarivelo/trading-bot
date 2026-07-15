"""Unit tests for the zone/pattern/structure additions to
`pob_price_action_snd for vix75_v1.py`. The generated file's name has a
space, so it can't be `import`-ed normally — loaded via `importlib` from its
path instead, same as the rest of the system does through
`strategies/sandbox.py`'s `validate_and_load` (which execs the source text
rather than importing it)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from src.strategies.domain.models import Direction, MarketContext, StructureLabel, ZoneKind

_STRATEGY_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "strategies"
    / "generated"
    / "pob_price_action_snd for vix75_v1.py"
)

START = datetime(2025, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _load_strategy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vix75_strategy_under_test", _STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_strategy_module()


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


# ---- _is_pin_bar -----------------------------------------------------------


def test_is_pin_bar_detects_bullish_rejection():
    df = pd.DataFrame([_bar(0, 100.0, 100.5, 97.0, 100.3)])
    is_pin, side = mod._is_pin_bar(df, 0, max_body_ratio=0.35, min_wick_body_mult=2.0)
    assert is_pin is True
    assert side == "up"


def test_is_pin_bar_detects_bearish_rejection():
    df = pd.DataFrame([_bar(0, 100.0, 103.0, 99.5, 99.7)])
    is_pin, side = mod._is_pin_bar(df, 0, max_body_ratio=0.35, min_wick_body_mult=2.0)
    assert is_pin is True
    assert side == "down"


def test_is_pin_bar_rejects_large_body_candle():
    df = pd.DataFrame([_bar(0, 100.0, 105.2, 99.8, 105.0)])
    is_pin, side = mod._is_pin_bar(df, 0, max_body_ratio=0.35, min_wick_body_mult=2.0)
    assert is_pin is False
    assert side == ""


# ---- _classify_pattern ------------------------------------------------------


def test_classify_pattern_prefers_engulfing():
    params = mod.PobPriceActionSnd().spec.params
    df = pd.DataFrame([_bar(0, 100.1, 100.3, 99.7, 99.9), _bar(1, 99.9, 105.5, 99.8, 105.0)])
    pattern, side = mod._classify_pattern(df, 1, params)
    assert pattern == "bullish_engulfing"
    assert side == "up"


def test_classify_pattern_falls_back_to_pin_bar():
    params = mod.PobPriceActionSnd().spec.params
    df = pd.DataFrame([_bar(0, 100.0, 100.5, 97.0, 100.3)])
    pattern, side = mod._classify_pattern(df, 0, params)
    assert pattern == "bullish_pin_bar"
    assert side == "up"


def test_classify_pattern_falls_back_to_body_candle():
    params = mod.PobPriceActionSnd().spec.params
    # Body ratio 0.5/0.6 ~= 0.83 clears engulf_min_body_ratio (0.6) but the
    # tiny wicks fail the pin-bar wick/body multiple, so this should resolve
    # to a plain body candle, not a pin bar.
    df = pd.DataFrame([_bar(0, 100.0, 100.55, 99.95, 100.5)])
    pattern, side = mod._classify_pattern(df, 0, params)
    assert pattern == "bullish_body_candle"
    assert side == "up"


def test_classify_pattern_none_for_indecisive_candle():
    params = mod.PobPriceActionSnd().spec.params
    # body/range = 0.3/0.7 ~= 0.43: too big a body to read as a pin-bar
    # rejection (max 0.35), too small to read as a momentum body candle
    # (needs >= 0.6) — genuinely indecisive.
    df = pd.DataFrame([_bar(0, 100.0, 100.5, 99.8, 100.3)])
    pattern, side = mod._classify_pattern(df, 0, params)
    assert pattern is None
    assert side is None


# ---- _classify_structure -----------------------------------------------------


def test_classify_structure_labels_hh_hl_lh_ll():
    times = [START + i * STEP for i in range(6)]
    df = pd.DataFrame(
        {
            "time": times,
            "high": [100.0, 0.0, 105.0, 0.0, 102.0, 0.0],
            "low": [0.0, 90.0, 0.0, 95.0, 0.0, 85.0],
        }
    )
    is_high = pd.Series([True, False, True, False, True, False])
    is_low = pd.Series([False, True, False, True, False, True])

    structure = mod._classify_structure(df, is_high, is_low, max_points=10)

    assert [p.label for p in structure] == [
        StructureLabel.HH,
        StructureLabel.HL,
        StructureLabel.LH,
        StructureLabel.LL,
    ]
    assert [p.price for p in structure] == [105.0, 95.0, 102.0, 85.0]
    assert [p.time for p in structure] == [times[2], times[3], times[4], times[5]]


def test_classify_structure_margin_biases_near_ties_to_lower_label():
    # Second high (100.05) is only marginally above the first (100.0) — a
    # noise-level "retest," not a real break of structure. With a 0.2 margin
    # it should read as LH, not HH; without a margin it would read as HH.
    times = [START + i * STEP for i in range(2)]
    df = pd.DataFrame({"time": times, "high": [100.0, 100.05], "low": [0.0, 0.0]})
    is_high = pd.Series([True, True])
    is_low = pd.Series([False, False])

    structure = mod._classify_structure(df, is_high, is_low, max_points=10, margin=0.2)
    assert [p.label for p in structure] == [StructureLabel.LH]

    structure_no_margin = mod._classify_structure(df, is_high, is_low, max_points=10, margin=0.0)
    assert [p.label for p in structure_no_margin] == [StructureLabel.HH]


def test_classify_structure_truncates_to_max_points():
    times = [START + i * STEP for i in range(6)]
    df = pd.DataFrame(
        {
            "time": times,
            "high": [100.0, 0.0, 105.0, 0.0, 102.0, 0.0],
            "low": [0.0, 90.0, 0.0, 95.0, 0.0, 85.0],
        }
    )
    is_high = pd.Series([True, False, True, False, True, False])
    is_low = pd.Series([False, True, False, True, False, True])

    structure = mod._classify_structure(df, is_high, is_low, max_points=2)

    assert len(structure) == 2
    assert [p.label for p in structure] == [StructureLabel.LH, StructureLabel.LL]


# ---- end-to-end: evaluate() populates zone/pattern/structure ---------------


def _zigzag_sr_history(n_cycles: int) -> list[dict]:
    """Oscillates between 100 and 110 in 5-bar legs, giving several swing
    touches at both levels — the tested support/resistance the final base
    breaks out from."""
    rows: list[dict] = []
    level = 100.0
    step_dir = 1
    i = 0
    for _ in range(n_cycles):
        for _ in range(5):
            o, c = level, level + step_dir * 2.0
            rows.append(_bar(i, o, max(o, c) + 0.4, min(o, c) - 0.4, c))
            i += 1
            level = c
        step_dir *= -1
    while abs(level - 100.0) > 0.01:
        d = -1 if level > 100.0 else 1
        o, c = level, level + d * 2.0
        rows.append(_bar(i, o, max(o, c) + 0.4, min(o, c) - 0.4, c))
        i += 1
        level = c
    return rows


def _mtf_confirmation_df() -> pd.DataFrame:
    rows = [_bar(k, 100.0, 100.5, 99.5, 100.0) for k in range(8)]
    rows[-2] = _bar(6, 100.0, 100.3, 99.6, 99.7)  # small bearish
    rows[-1] = _bar(7, 99.7, 103.0, 99.6, 102.5)  # bullish engulfing
    return pd.DataFrame(rows)


def make_buy_signal_ctx() -> MarketContext:
    rows = _zigzag_sr_history(n_cycles=25)
    i = len(rows)
    # Base: two small bars near the well-tested 100 support, second bearish
    # so the next bar can be a clean bullish engulfing off it.
    rows.append(_bar(i, 100.0, 100.3, 99.8, 100.1))
    i += 1
    rows.append(_bar(i, 100.1, 100.3, 99.7, 99.9))
    i += 1
    # Breakout: bullish engulfing off the base.
    rows.append(_bar(i, 99.9, 105.5, 99.8, 105.0))

    candles = {"M5": pd.DataFrame(rows)}
    for tf in ("M15", "M30", "H1", "H4"):
        candles[tf] = _mtf_confirmation_df()
    return MarketContext(symbol="Volatility 75 Index", candles=candles, spread_points=20.0)


def test_evaluate_populates_zone_pattern_structure_on_signal():
    strategy = mod.PobPriceActionSnd()
    signal = strategy.evaluate(make_buy_signal_ctx())

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.pattern == "bullish_engulfing"

    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.DEMAND
    assert signal.zone.price_low < signal.zone.price_high
    assert signal.zone.time_start < signal.zone.time_end

    assert len(signal.structure) > 0
    assert all(p.label in StructureLabel for p in signal.structure)


def test_evaluate_returns_none_below_min_bars():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M5": pd.DataFrame([_bar(0, 100.0, 100.5, 99.5, 100.0)])},
        spread_points=20.0,
    )
    assert mod.PobPriceActionSnd().evaluate(ctx) is None


# ---- _fit_trendline / _touches_trendline ------------------------------------


def test_fit_trendline_basic_line():
    line = mod._fit_trendline([(0, 100.0), (10, 110.0)])
    assert line is not None
    slope, intercept = line
    assert slope == pytest.approx(1.0)
    assert intercept == pytest.approx(100.0)


def test_fit_trendline_needs_at_least_two_points():
    assert mod._fit_trendline([(5, 50.0)]) is None


def test_fit_trendline_rejects_same_index_points():
    assert mod._fit_trendline([(3, 10.0), (3, 20.0)]) is None


def test_touches_trendline_within_tolerance():
    df = pd.DataFrame([_bar(0, 100.0, 100.3, 99.8, 100.0)])
    assert mod._touches_trendline(df, slope=0.0, intercept=100.0, i=0, tolerance=0.5) is True


def test_touches_trendline_outside_tolerance():
    df = pd.DataFrame([_bar(0, 105.0, 105.3, 104.8, 105.0)])
    assert mod._touches_trendline(df, slope=0.0, intercept=100.0, i=0, tolerance=0.5) is False


# ---- _find_qm_structure (QMR/QM2P/QMM shared structure) ---------------------


def test_find_qm_structure_sell_reversal():
    raw_points = [(0, 100.0, "high"), (3, 95.0, "low"), (6, 105.0, "high"), (9, 90.0, "low")]
    qm = mod._find_qm_structure(raw_points)
    assert qm is not None
    assert qm["reversal_direction"] is Direction.SELL
    assert qm["manipulation_direction"] is Direction.BUY
    assert qm["neckline_price"] == 100.0
    assert qm["head_price"] == 105.0
    assert qm["extreme_price"] == 90.0


def test_find_qm_structure_buy_reversal():
    raw_points = [(0, 95.0, "low"), (3, 100.0, "high"), (6, 90.0, "low"), (9, 105.0, "high")]
    qm = mod._find_qm_structure(raw_points)
    assert qm is not None
    assert qm["reversal_direction"] is Direction.BUY
    assert qm["manipulation_direction"] is Direction.SELL
    assert qm["neckline_price"] == 95.0
    assert qm["head_price"] == 90.0


def test_find_qm_structure_none_when_head_doesnt_extend_past_neckline():
    # p2 (98) does not exceed p0 (100) -> not a genuine QM head, just noise.
    raw_points = [(0, 100.0, "high"), (3, 95.0, "low"), (6, 98.0, "high"), (9, 90.0, "low")]
    assert mod._find_qm_structure(raw_points) is None


def test_find_qm_structure_none_with_fewer_than_four_points():
    assert mod._find_qm_structure([(0, 100.0, "high"), (3, 95.0, "low")]) is None


# ---- _find_hybrid -------------------------------------------------------------


def _hybrid_breakout_rows() -> list[dict]:
    rows = [_bar(i, 100.0, 100.5, 99.5, 100.0) for i in range(20)]
    rows.append(_bar(20, 100.2, 100.3, 99.7, 99.8))  # small bearish, prev for the breakout bar
    rows.append(_bar(21, 99.7, 125.3, 99.6, 125.0))  # bullish engulfing breaking upward
    return rows


def test_find_hybrid_detects_clean_downtrend_break_buy():
    params = mod.PobPriceActionSnd().spec.params
    raw_points = [(0, 130.0, "low"), (10, 125.0, "low"), (20, 120.0, "low")]
    sr_slice = pd.DataFrame(_hybrid_breakout_rows())
    result = mod._find_hybrid(raw_points, sr_slice, atr_val=2.0, params=params)
    assert result is not None
    assert result["setup"] == "Hybrid1"
    assert result["direction"] is Direction.BUY
    assert result["risk"] == "high"


def test_find_hybrid_none_when_trendline_points_not_monotonic():
    params = mod.PobPriceActionSnd().spec.params
    # Middle point (130) is higher than the first (125) -> not a clean,
    # one-directional decline, so the Danger Zone validity proxy fails it.
    raw_points = [(0, 125.0, "low"), (10, 130.0, "low"), (20, 120.0, "low")]
    sr_slice = pd.DataFrame(_hybrid_breakout_rows())
    assert mod._find_hybrid(raw_points, sr_slice, atr_val=2.0, params=params) is None


# ---- _find_blindspot -----------------------------------------------------------


def _blindspot_rows() -> list[dict]:
    rows = [_bar(i, 100.0, 100.2, 99.8, 100.0) for i in range(5)]
    rows.append(_bar(5, 100.2, 100.3, 99.7, 99.8))  # small bearish
    rows.append(_bar(6, 99.7, 103.2, 99.6, 103.0))  # bullish engulfing ("failed engulfing")
    rows.append(_bar(7, 103.0, 103.5, 102.5, 103.2))
    rows.append(_bar(8, 103.2, 103.4, 100.0, 101.0))
    rows.append(_bar(9, 101.0, 101.2, 97.0, 98.0))
    rows.append(_bar(10, 98.0, 98.2, 94.5, 95.0))  # closes below bar 6's low: significant break
    rows.append(_bar(11, 95.0, 96.0, 94.0, 95.5))
    rows.append(_bar(12, 95.5, 97.0, 95.0, 96.5))
    rows.append(_bar(13, 98.7, 99.1, 98.6, 99.0))  # small bullish, prev for the retest bar
    rows.append(_bar(14, 99.2, 99.3, 98.5, 98.6))  # bearish engulfing at the retest
    return rows


def test_find_blindspot_detects_failed_engulf_and_retest():
    params = {**mod.PobPriceActionSnd().spec.params, "blindspot_lookback_bars": 10}
    sr_slice = pd.DataFrame(_blindspot_rows())
    result = mod._find_blindspot([], sr_slice, atr_val=2.0, params=params)
    assert result is not None
    assert result["setup"] == "Blindspot1"
    assert result["direction"] is Direction.SELL


def test_find_blindspot_none_without_a_significant_break():
    params = {**mod.PobPriceActionSnd().spec.params, "blindspot_lookback_bars": 10}
    rows = _blindspot_rows()
    # Keep every bar between the engulfing candle (6) and the retest (14)
    # above its low (99.6) — the engulfing candle never actually fails, so
    # there's nothing to retest.
    for idx in (8, 9, 10, 11, 12, 13):
        rows[idx] = _bar(idx, 100.0, 100.2, 99.8, 100.0)
    sr_slice = pd.DataFrame(rows)
    assert mod._find_blindspot([], sr_slice, atr_val=2.0, params=params) is None


# ---- _confidence_cap_for -------------------------------------------------------


def test_confidence_cap_for_high_risk_setup():
    params = mod.PobPriceActionSnd().spec.params
    assert (
        mod._confidence_cap_for("QMR risk=high pattern=x", params)
        == params["reversal_confidence_cap"]
    )


def test_confidence_cap_for_medium_risk_setup():
    params = mod.PobPriceActionSnd().spec.params
    assert (
        mod._confidence_cap_for("QM2P risk=medium pattern=x", params)
        == params["reversal_confidence_cap_confirmed"]
    )


def test_confidence_cap_for_snrc_setup_uses_default_ceiling():
    params = mod.PobPriceActionSnd().spec.params
    assert mod._confidence_cap_for("SNRC1-RBR pattern=x", params) == 0.95


# ---- evaluate(): reversal pipeline is opt-in and risk-tiered ------------------


def _ramp_rows(start_i: int, start_price: float, end_price: float, n_bars: int) -> list[dict]:
    step = (end_price - start_price) / n_bars
    rows = []
    price = start_price
    for k in range(n_bars):
        o = price
        price += step
        c = price
        rows.append(_bar(start_i + k, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
    return rows


def _apex_leg(
    start_i: int,
    from_price: float,
    apex_price: float,
    to_price: float,
    leg_bars: int = 4,
    gap: float = 3.0,
) -> tuple[list[dict], int]:
    """Ramps from `from_price` to within `gap` of `apex_price`, a single
    dedicated apex bar, then ramps on from within `gap` of `apex_price` to
    `to_price` — the `gap` keeps the apex bar's high/low a strict local
    extreme within +/- `swing_lookback` bars, unlike two ramps meeting
    exactly at the peak (which ties the boundary bars' highs/lows and
    produces duplicate, non-alternating swing points)."""
    rising = apex_price > from_price
    pre_target = apex_price - gap if rising else apex_price + gap
    rows = _ramp_rows(start_i, from_price, pre_target, leg_bars)
    i = start_i + leg_bars
    o, c = pre_target, apex_price
    rows.append(_bar(i, o, max(o, c) + 0.3, min(o, c) - 0.3, c))
    i += 1
    falling_from_apex = to_price < apex_price
    post_start = apex_price - gap if falling_from_apex else apex_price + gap
    rows += _ramp_rows(i, post_start, to_price, leg_bars)
    return rows, i + leg_bars


def _qmr_sell_zigzag_ctx() -> MarketContext:
    """A quiet flat run (keeps ATR small but positive, and gives SNRC's
    `_find_base` nothing to work with) followed by a sharp H -> L -> HH -> LL
    -> neckline-retest zigzag — the QMR Sell shape from p.90-91."""
    rows = [_bar(k, 100.0, 100.4, 99.6, 100.0) for k in range(90)]
    i = 90
    r, i = _apex_leg(i, 100.0, 130.0, 115.0)  # up into H
    rows += r
    r, i = _apex_leg(i, 115.0, 110.0, 125.0)  # down into L
    rows += r
    r, i = _apex_leg(i, 125.0, 150.0, 118.0)  # up into HH (new high past H)
    rows += r
    r, i = _apex_leg(i, 118.0, 90.0, 128.0)  # down into LL (new low past L), rally toward neckline
    rows += r
    rows.append(_bar(i, 128.0, 129.7, 127.8, 129.5))  # bullish approach to the neckline
    i += 1
    rows.append(_bar(i, 129.6, 130.0, 127.5, 127.9))  # bearish engulfing retest

    candles = {"M5": pd.DataFrame(rows)}
    for tf in ("M15", "M30", "H1", "H4"):
        candles[tf] = _mtf_confirmation_df_bearish()
    return MarketContext(symbol="Volatility 75 Index", candles=candles, spread_points=20.0)


def _mtf_confirmation_df_bearish() -> pd.DataFrame:
    rows = [_bar(k, 100.0, 100.5, 99.5, 100.0) for k in range(8)]
    rows[-2] = _bar(6, 100.0, 100.3, 99.7, 100.3)  # small bullish
    rows[-1] = _bar(7, 100.3, 100.4, 96.0, 96.5)  # bearish engulfing
    return pd.DataFrame(rows)


def test_evaluate_reversal_disabled_by_default_returns_none_for_qmr_shape():
    strategy = mod.PobPriceActionSnd()
    assert strategy.spec.params["enable_reversal_setups"] is False
    ctx = _qmr_sell_zigzag_ctx()
    # SNRC's own base-finder has nothing to work with (no ATR-scale
    # compression base right before the last bar), so this shape produces no
    # signal at all while the reversal pipeline stays off by default.
    assert strategy.evaluate(ctx) is None


def test_evaluate_reversal_enabled_detects_qmr_sell():
    strategy = mod.PobPriceActionSnd()
    strategy.spec.params["enable_reversal_setups"] = True
    ctx = _qmr_sell_zigzag_ctx()

    signal = strategy.evaluate(ctx)

    assert signal is not None
    assert signal.direction is Direction.SELL
    assert "QMR" in signal.reason
    assert "risk=high" in signal.reason
    # High-risk tier: CK confluence can never push confidence past this cap.
    assert signal.confidence <= strategy.spec.params["reversal_confidence_cap"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
