import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_ema_cross_v1_v2 import ScalpEmaCrossV2


def make_ctx(closes: list[float], offset: float = 3.0) -> MarketContext:
    highs = [c + offset for c in closes]
    lows = [c - offset for c in closes]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": [100.0] * len(closes),
        }
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def test_buy_signal_on_confirmed_bullish_cross_with_enough_volatility():
    closes = [2400.0] * 41 + [2412.0]
    strategy = ScalpEmaCrossV2()
    signal = strategy.evaluate(make_ctx(closes))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    assert signal.tp_points == signal.sl_points * strategy.spec.params["tp_rr"]


def test_sell_signal_on_confirmed_bearish_cross_with_enough_volatility():
    closes = [2400.0] * 41 + [2388.0]
    signal = ScalpEmaCrossV2().evaluate(make_ctx(closes))

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_cross_is_too_quiet_to_clear_volatility_floor():
    # Same shape of cross as the v1 test, but with a tiny high/low offset and
    # a barely-there ramp: ATR(14)/close stays under the v2 min_vol_ratio
    # floor, which v1 had no equivalent filter for.
    closes = [2400.0] * 41 + [2403.0]
    signal = ScalpEmaCrossV2().evaluate(make_ctx(closes, offset=0.05))
    assert signal is None


def test_no_signal_with_insufficient_history():
    closes = [2400.0] * 10
    assert ScalpEmaCrossV2().evaluate(make_ctx(closes)) is None


def test_spec_is_version_two_with_new_filters():
    spec = ScalpEmaCrossV2().spec
    assert spec.version == 2
    assert spec.name == "scalp_ema_cross_v1"
    assert spec.params["atr_mult"] == 1.4
    assert spec.params["min_vol_ratio"] == 0.0006
