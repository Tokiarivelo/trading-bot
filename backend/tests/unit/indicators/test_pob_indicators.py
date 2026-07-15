"""Unit tests for the 15 PoB pattern/confirmation custom indicators under
`backend/scripts/pob_indicators/` — Python sources authored for the
existing custom-indicator system (`src/indicators/`), seeded into the DB by
`backend/scripts/seed_pob_indicators.py`. Loaded the same way the sandbox
loads any saved indicator (`validate_and_load`), not `import`ed directly,
so these tests also double as a sandbox-compliance check for every file."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from src.indicators.sandbox import validate_and_load

_INDICATORS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "pob_indicators"

_ALL_NAMES = [
    "pob_snrc1",
    "pob_snrc2",
    "pob_qmr",
    "pob_qm2p",
    "pob_qmm",
    "pob_qmc",
    "pob_hybrid1",
    "pob_hybrid2",
    "pob_blindspot1",
    "pob_blindspot2",
    "pob_engulfing",
    "pob_pin_bar",
    "pob_body_candle",
    "pob_ck_confluence",
    "pob_swing_structure",
]

START = datetime(2025, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _load_module(name: str) -> ModuleType:
    path = _INDICATORS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(name: str) -> str:
    return (_INDICATORS_DIR / f"{name}.py").read_text()


def _zigzag_df(n_cycles: int, normalize_tail: bool = False) -> pd.DataFrame:
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
    if normalize_tail:
        # Bring the zigzag's ending level back to exactly 100.0 so a caller
        # can append bars at that well-tested level with predictable prices.
        while abs(level - 100.0) > 0.01:
            d = -1 if level > 100.0 else 1
            o, c = level, level + d * 2.0
            rows.append(_bar(i, o, max(o, c) + 0.4, min(o, c) - 0.4, c))
            i += 1
            level = c
    return pd.DataFrame(rows)


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


def _qmr_sell_df() -> pd.DataFrame:
    """H -> L -> HH -> LL -> neckline retest with a bearish engulfing, the
    QMR Sell shape from p.90-91."""
    rows = [_bar(k, 100.0, 100.4, 99.6, 100.0) for k in range(20)]
    i = 20
    r, i = _apex_leg(i, 100.0, 130.0, 115.0)
    rows += r
    r, i = _apex_leg(i, 115.0, 110.0, 125.0)
    rows += r
    r, i = _apex_leg(i, 125.0, 150.0, 118.0)
    rows += r
    r, i = _apex_leg(i, 118.0, 90.0, 128.0)
    rows += r
    rows.append(_bar(i, 128.0, 129.7, 127.8, 129.5))
    i += 1
    rows.append(_bar(i, 129.6, 130.0, 127.5, 127.9))
    return pd.DataFrame(rows)


# ---- sandbox compliance + basic output shape, all 15 -----------------------


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_indicator_passes_sandbox_validation(name: str) -> None:
    instance, errors = validate_and_load(_source(name))
    assert errors == ()
    assert instance is not None


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_indicator_output_series_match_candle_length(name: str) -> None:
    module = _load_module(name)
    indicator_cls = next(
        v for v in vars(module).values() if isinstance(v, type) and hasattr(v, "compute")
    )
    df = _zigzag_df(20)
    result = indicator_cls().compute(df, {})
    assert isinstance(result, dict)
    assert len(result) > 0
    for series_name, values in result.items():
        assert len(values) == len(df), f"{name}.{series_name} length mismatch"


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_indicator_handles_empty_candles(name: str) -> None:
    module = _load_module(name)
    indicator_cls = next(
        v for v in vars(module).values() if isinstance(v, type) and hasattr(v, "compute")
    )
    empty = pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])
    result = indicator_cls().compute(empty, {})
    assert isinstance(result, dict)
    for values in result.values():
        assert values == []


# ---- targeted detection tests ------------------------------------------------


def test_snrc2_detects_reversal_off_tested_zone():
    mod = _load_module("pob_snrc2")
    df = _zigzag_df(25, normalize_tail=True)
    i = len(df)
    extra = [
        _bar(i, 100.0, 100.3, 99.8, 100.1),
        _bar(i + 1, 100.1, 100.3, 99.7, 99.9),
        _bar(i + 2, 99.9, 105.5, 99.8, 105.0),
    ]
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    result = mod.PobSnrc2Indicator().compute(df, {})
    assert any(v is not None for v in result["entry_marker_up"])
    assert any(v is not None for v in result["zone_high"])


def test_snrc1_finds_nothing_on_pure_reversal_zigzag():
    # The same zigzag+tail-base used above resolves to SNRC2 (a reversal off
    # a tested zone), not SNRC1 (continuation) — SNRC1 should stay quiet.
    mod = _load_module("pob_snrc1")
    df = _zigzag_df(25, normalize_tail=True)
    i = len(df)
    extra = [
        _bar(i, 100.0, 100.3, 99.8, 100.1),
        _bar(i + 1, 100.1, 100.3, 99.7, 99.9),
        _bar(i + 2, 99.9, 105.5, 99.8, 105.0),
    ]
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    result = mod.PobSnrc1Indicator().compute(df, {})
    assert all(v is None for v in result["entry_marker_up"])
    assert all(v is None for v in result["entry_marker_down"])


def test_qmr_detects_head_and_shoulders_reversal():
    mod = _load_module("pob_qmr")
    df = _qmr_sell_df()
    result = mod.PobQmrIndicator().compute(df, {})
    assert any(v is not None for v in result["entry_marker_down"])
    assert any(v is not None for v in result["neckline"])
    assert any(v is not None for v in result["head_marker"])
    assert any(v is not None for v in result["extreme_marker"])


def test_engulfing_marks_bullish_and_bearish_occurrences():
    mod = _load_module("pob_engulfing")
    df = _zigzag_df(10)
    result = mod.PobEngulfingIndicator().compute(df, {})
    assert any(v is not None for v in result["engulfing_marker_up"])
    assert any(v is not None for v in result["engulfing_marker_down"])


def test_body_candle_marks_momentum_candles():
    mod = _load_module("pob_body_candle")
    df = _zigzag_df(10)
    result = mod.PobBodyCandleIndicator().compute(df, {})
    assert any(v is not None for v in result["body_candle_marker_up"])
    assert any(v is not None for v in result["body_candle_marker_down"])


def test_swing_structure_labels_lh_and_ll_on_a_ranging_zigzag():
    mod = _load_module("pob_swing_structure")
    df = _zigzag_df(10)
    result = mod.PobSwingStructureIndicator().compute(df, {})
    assert any(v is not None for v in result["lh_marker"])
    assert any(v is not None for v in result["ll_marker"])


def test_ck_confluence_marks_trendline_touches():
    mod = _load_module("pob_ck_confluence")
    df = _zigzag_df(10)
    result = mod.PobCkConfluenceIndicator().compute(df, {})
    assert any(v is not None for v in result["ck1_marker"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
