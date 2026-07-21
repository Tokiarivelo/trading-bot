import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_vwap_reversion_v1_v2 import ScalpVwapReversionV2

N_WARMUP = 50  # v2 MIN_HISTORY (51) - 1: lookback(30) + atr_period(14) + fresh_bars(5) + 2


def _ctx(opens, highs, lows, closes, volumes) -> MarketContext:
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def _warmup_and_stretch(stretch_close: float, stretch_open: float) -> MarketContext:
    closes = [100.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(N_WARMUP)]
    opens = list(closes)
    volumes = [1000.0] * N_WARMUP
    closes.append(stretch_close)
    opens.append(stretch_open)
    volumes.append(10.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    return _ctx(opens, highs, lows, closes, volumes)


def test_buy_signal_on_fresh_downward_stretch_in_non_trending_regime():
    strategy = ScalpVwapReversionV2()
    signal = strategy.evaluate(_warmup_and_stretch(stretch_close=88.0, stretch_open=86.0))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    assert signal.tp_points == signal.sl_points * strategy.spec.params["tp_rr"]


def test_sell_signal_on_fresh_upward_stretch_in_non_trending_regime():
    signal = ScalpVwapReversionV2().evaluate(
        _warmup_and_stretch(stretch_close=112.0, stretch_open=114.0)
    )

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_stretch_is_not_fresh():
    # A gradual multi-bar ramp down means the deviation already existed
    # `fresh_bars` back -- v2's freshness check rejects it as an
    # established trend, not a fresh overextension.
    closes = [100.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(N_WARMUP - 6)]
    opens = list(closes)
    volumes = [1000.0] * (N_WARMUP - 6)
    for i in range(8):
        closes.append(100.0 - (i + 1) * 2.0)
        opens.append(closes[-1] + 0.3)
        volumes.append(1000.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    signal = ScalpVwapReversionV2().evaluate(_ctx(opens, highs, lows, closes, volumes))
    assert signal is None


def test_no_signal_with_insufficient_history():
    closes = [100.0] * 10
    opens = list(closes)
    volumes = [100.0] * 10
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    assert ScalpVwapReversionV2().evaluate(_ctx(opens, highs, lows, closes, volumes)) is None


def test_spec_is_version_two_with_new_regime_and_freshness_filters():
    spec = ScalpVwapReversionV2().spec
    assert spec.version == 2
    assert spec.name == "scalp_vwap_reversion_v1"
    assert spec.confirmation_timeframes == ()
    assert spec.params["deviation_mult"] == 2.75
    assert spec.params["fresh_bars"] == 5
    assert spec.params["max_trend_slope_atr"] == 3.0
