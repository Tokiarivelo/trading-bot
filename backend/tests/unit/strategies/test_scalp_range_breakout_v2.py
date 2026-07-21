import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_range_breakout_v1_v2 import ScalpRangeBreakoutV2


def make_ctx(closes: list[float], volumes: list[float], offset: float = 0.3) -> MarketContext:
    highs = [c + offset for c in closes]
    lows = [c - offset for c in closes]
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def test_buy_signal_on_wide_range_breakout_with_strong_volume():
    # A low-noise zigzag establishes a wide 10-bar range (accumulated
    # excursion, not per-bar noise) so range width clears 1.2x ATR, then a
    # strong-volume breakout above it.
    base = 2400.0
    zigzag = [base + ((i % 6) - 3) * 0.5 for i in range(18)]
    closes = zigzag + [base + 8.0]
    volumes = [100.0] * 18 + [400.0]  # v2: needs >= 1.6x avg (was 1.3x in v1)

    strategy = ScalpRangeBreakoutV2()
    signal = strategy.evaluate(make_ctx(closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    assert signal.tp_points == signal.sl_points * strategy.spec.params["tp_rr"]


def test_no_signal_when_range_too_tight_versus_atr():
    # v1-style fixture: flat range then a breakout. The breakout bar's own
    # gap inflates ATR(7) enough that the tiny pre-breakout range fails the
    # v2 min-range-width filter -- this is intentional (v1's tight ranges
    # were mostly noise, not real consolidations).
    closes = [2400.0] * 18 + [2410.0]
    volumes = [100.0] * 18 + [400.0]
    assert ScalpRangeBreakoutV2().evaluate(make_ctx(closes, volumes)) is None


def test_no_signal_when_breakout_lacks_stronger_volume_confirmation():
    base = 2400.0
    zigzag = [base + ((i % 6) - 3) * 0.5 for i in range(18)]
    closes = zigzag + [base + 8.0]
    volumes = [100.0] * 19  # breakout bar volume == average, below the v2 1.6x floor
    assert ScalpRangeBreakoutV2().evaluate(make_ctx(closes, volumes)) is None


def test_no_signal_with_insufficient_history():
    closes = [2400.0] * 5
    volumes = [100.0] * 5
    assert ScalpRangeBreakoutV2().evaluate(make_ctx(closes, volumes)) is None


def test_spec_is_version_two_with_widened_filters():
    spec = ScalpRangeBreakoutV2().spec
    assert spec.version == 2
    assert spec.name == "scalp_range_breakout_v1"
    assert set(spec.symbols) == {
        "XAUUSD",
        "XAGUSD",
        "BTCUSD",
        "Boom 1000 Index",
        "Volatility 75 Index",
    }
    assert spec.params["volume_mult"] == 1.6
    assert spec.params["atr_mult"] == 1.3
    assert spec.params["min_range_atr_mult"] == 1.2
