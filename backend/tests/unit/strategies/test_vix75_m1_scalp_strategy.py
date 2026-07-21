"""Unit tests for `pob_price_action_snd_m1_scalp for vix75_v1.py` — the M1
scalping retiming of `pob_price_action_snd for vix75_v2.py`. Loaded via
`importlib` from its path since the generated file's name has a space, same
as `strategies/sandbox.py`'s `validate_and_load` does."""

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
    / "pob_price_action_snd_m1_scalp for vix75_v1.py"
)

START = datetime(2025, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=1)


def _load_strategy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "vix75_m1_scalp_strategy_under_test", _STRATEGY_PATH
    )
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


# ---- spec sanity: this is the M1 retiming, not a copy of the M5 version ----


def test_spec_is_retimed_for_m1_scalping():
    spec = mod.PobPriceActionSndM1Scalp().spec
    assert spec.entry_timeframe == "M1"
    assert spec.confirmation_timeframes == ("M5", "M15")
    assert spec.symbols == ("Volatility 75 Index",)
    # Tighter than the M5 version's sl_atr_mult=1.2 / reward_risk_ratio=1.8 —
    # a smaller $ risk per broker-minimum-lot trade is the whole point.
    assert spec.params["sl_atr_mult"] < 1.2
    assert spec.params["reward_risk_ratio"] < 1.8
    # Only 2 confirmation timeframes now (vs the M5 version's 4) — requiring
    # both would be a stricter bar than the M5 version's "2 of 4", not
    # equivalent, so this must have come down too.
    assert spec.params["min_confirmations"] == 1


def test_evaluate_returns_none_below_min_bars():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M1": pd.DataFrame([_bar(0, 100.0, 100.5, 99.5, 100.0)])},
        spread_points=20.0,
    )
    assert mod.PobPriceActionSndM1Scalp().evaluate(ctx) is None


# ---- end-to-end: a clean base + breakout + SR + MTF confirm produces a signal


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
    rows = _zigzag_sr_history(n_cycles=45)  # more cycles than the M5 test: sr_lookback_bars=180
    i = len(rows)
    # Base: two small bars near the well-tested 100 support, second bearish
    # so the next bar can be a clean bullish engulfing off it.
    rows.append(_bar(i, 100.0, 100.3, 99.8, 100.1))
    i += 1
    rows.append(_bar(i, 100.1, 100.3, 99.7, 99.9))
    i += 1
    # Breakout: bullish engulfing off the base.
    rows.append(_bar(i, 99.9, 105.5, 99.8, 105.0))

    candles = {"M1": pd.DataFrame(rows)}
    for tf in ("M5", "M15"):
        candles[tf] = _mtf_confirmation_df()
    return MarketContext(symbol="Volatility 75 Index", candles=candles, spread_points=20.0)


def test_evaluate_populates_zone_pattern_structure_on_signal():
    strategy = mod.PobPriceActionSndM1Scalp()
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

    # The tighter M1 risk params actually took effect on this signal.
    assert signal.sl_points > 0
    spread_distance = 20.0 * 0.01  # ctx.spread_points * Volatility 75 Index point size
    expected_tp = (signal.sl_points + spread_distance) * strategy.spec.params["reward_risk_ratio"]
    assert signal.tp_points == pytest.approx(expected_tp)


def test_evaluate_returns_none_without_mtf_confirmation():
    ctx = make_buy_signal_ctx()
    # Replace both confirmation timeframes with flat, patternless candles —
    # min_confirmations=1 can't be met.
    flat = pd.DataFrame([_bar(k, 100.0, 100.1, 99.9, 100.0) for k in range(8)])
    ctx = MarketContext(
        symbol=ctx.symbol,
        candles={**ctx.candles, "M5": flat, "M15": flat},
        spread_points=ctx.spread_points,
    )
    assert mod.PobPriceActionSndM1Scalp().evaluate(ctx) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
