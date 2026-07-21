import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_volume_imbalance_v1_v2 import ScalpVolumeImbalanceV2

N = 29  # v2 MIN_HISTORY: imbalance_window(14) + atr_period(10) + 5


def _ctx(opens, highs, lows, closes, volumes) -> MarketContext:
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def _biased_window(bullish: bool) -> tuple[list, list, list, list, list]:
    opens = [100.0] * N
    closes = [100.0] * N
    volumes = [50.0] * N
    delta = 3.0 if bullish else -3.0  # strong-bodied bars, not near-doji
    for i in range(N - 14, N):
        closes[i] = 100.0 + delta
        volumes[i] = 200.0
    opens[N - 3] = 100.0
    closes[N - 3] = 100.0 - delta * 0.5
    volumes[N - 3] = 50.0
    highs = [max(o, c) + 0.1 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.1 for o, c in zip(opens, closes, strict=True)]
    return opens, closes, volumes, highs, lows


def test_buy_signal_on_body_weighted_bullish_imbalance():
    opens, closes, volumes, highs, lows = _biased_window(bullish=True)
    strategy = ScalpVolumeImbalanceV2()
    signal = strategy.evaluate(_ctx(opens, highs, lows, closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    assert signal.tp_points == signal.sl_points * strategy.spec.params["tp_rr"]


def test_sell_signal_on_body_weighted_bearish_imbalance():
    opens, closes, volumes, highs, lows = _biased_window(bullish=False)
    signal = ScalpVolumeImbalanceV2().evaluate(_ctx(opens, highs, lows, closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_directional_volume_is_balanced():
    opens = [100.0] * N
    closes = [100.0] * N
    volumes = [50.0] * N
    for i in range(N - 14, N):
        offset = N - 14
        closes[i] = 101.0 if (i - offset) % 2 == 0 else 99.0
        volumes[i] = 150.0
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    signal = ScalpVolumeImbalanceV2().evaluate(_ctx(opens, highs, lows, closes, volumes))
    assert signal is None


def test_no_signal_with_insufficient_history():
    closes = [100.0] * 5
    opens = list(closes)
    volumes = [50.0] * 5
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    assert ScalpVolumeImbalanceV2().evaluate(_ctx(opens, highs, lows, closes, volumes)) is None


def test_spec_is_version_two_with_body_weighting_and_higher_threshold():
    spec = ScalpVolumeImbalanceV2().spec
    assert spec.version == 2
    assert spec.name == "scalp_volume_imbalance_v1"
    assert spec.params["imbalance_window"] == 14
    assert spec.params["imbalance_threshold"] == 0.55
    assert spec.params["atr_mult"] == 1.3
