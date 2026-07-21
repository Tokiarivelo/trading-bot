import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_range_breakout_v1_v1 import ScalpRangeBreakoutV1


def make_ctx(closes: list[float], volumes: list[float] | None = None) -> MarketContext:
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    volumes = volumes or [100.0] * len(closes)
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def test_buy_signal_on_volume_confirmed_breakout_above_range():
    closes = [2400.0] * 18 + [2410.0]
    volumes = [100.0] * 18 + [200.0]  # 2x the 10-bar window average -> clears 1.3x filter
    strategy = ScalpRangeBreakoutV1()
    signal = strategy.evaluate(make_ctx(closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    spread_distance = 25.0 * 0.01  # ctx.spread_points * XAUUSD point size
    assert signal.tp_points == (signal.sl_points + spread_distance) * strategy.spec.params["tp_rr"]


def test_sell_signal_on_volume_confirmed_breakout_below_range():
    closes = [2400.0] * 18 + [2390.0]
    volumes = [100.0] * 18 + [200.0]
    signal = ScalpRangeBreakoutV1().evaluate(make_ctx(closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_breakout_lacks_volume_confirmation():
    closes = [2400.0] * 18 + [2410.0]
    volumes = [100.0] * 19  # breakout bar volume == average, below the 1.3x filter
    assert ScalpRangeBreakoutV1().evaluate(make_ctx(closes, volumes)) is None


def test_no_signal_inside_range():
    closes = [2400.0] * 19
    volumes = [100.0] * 18 + [200.0]
    assert ScalpRangeBreakoutV1().evaluate(make_ctx(closes, volumes)) is None


def test_no_signal_with_insufficient_history():
    closes = [2400.0] * 5
    assert ScalpRangeBreakoutV1().evaluate(make_ctx(closes)) is None


def test_spec_covers_all_five_symbols_and_m5_entry():
    spec = ScalpRangeBreakoutV1().spec
    assert set(spec.symbols) == {
        "XAUUSD",
        "XAGUSD",
        "BTCUSD",
        "Boom 1000 Index",
        "Volatility 75 Index",
    }
    assert spec.entry_timeframe == "M5"
    assert spec.confirmation_timeframes == ("M1", "H1")
