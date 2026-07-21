import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_volume_imbalance_v1_v1 import ScalpVolumeImbalanceV1

N = 25  # MIN_HISTORY: imbalance_window(10) + atr_period(10) + 5


def _ctx(opens, highs, lows, closes, volumes) -> MarketContext:
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def _bars_with_last_ten_biased(bullish: bool) -> tuple[list, list, list]:
    """Flat filler for the first N-10 bars, then 9 heavily one-sided bars and
    one mild opposite bar in the trailing 10-bar imbalance window, with the
    final bar itself matching the bias (continuation)."""
    opens = [100.0] * N
    closes = [100.0] * N
    volumes = [50.0] * N
    delta = 1.0 if bullish else -1.0
    for i in range(N - 10, N):
        opens[i] = 100.0
        closes[i] = 100.0 + delta
        volumes[i] = 200.0
    # one mild counter-bar so the imbalance isn't a perfect 1.0
    opens[N - 3] = 100.0
    closes[N - 3] = 100.0 - delta
    volumes[N - 3] = 50.0
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    return opens, closes, volumes, highs, lows  # type: ignore[return-value]


def test_buy_signal_on_bullish_volume_imbalance():
    opens, closes, volumes, highs, lows = _bars_with_last_ten_biased(bullish=True)
    strategy = ScalpVolumeImbalanceV1()
    signal = strategy.evaluate(_ctx(opens, highs, lows, closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    spread_distance = 25.0 * 0.01  # ctx.spread_points * XAUUSD point size
    assert signal.tp_points == (signal.sl_points + spread_distance) * strategy.spec.params["tp_rr"]


def test_sell_signal_on_bearish_volume_imbalance():
    opens, closes, volumes, highs, lows = _bars_with_last_ten_biased(bullish=False)
    signal = ScalpVolumeImbalanceV1().evaluate(_ctx(opens, highs, lows, closes, volumes))

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_imbalance_is_balanced():
    opens = [100.0] * N
    closes = [100.0] * N
    volumes = [50.0] * N
    # Alternate bullish/bearish bars of equal volume in the trailing window
    # -> imbalance stays near zero, well under the 0.35 threshold.
    for i in range(N - 10, N):
        closes[i] = 100.0 + (1.0 if i % 2 == 0 else -1.0)
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    signal = ScalpVolumeImbalanceV1().evaluate(_ctx(opens, highs, lows, closes, volumes))
    assert signal is None


def test_no_signal_when_imbalance_present_but_last_bar_opposes_it():
    # Strong bullish imbalance over the window, but the final bar itself
    # closes bearish -> not a continuation, no signal.
    opens, closes, volumes, highs, lows = _bars_with_last_ten_biased(bullish=True)
    opens[-1], closes[-1] = 100.0, 99.0
    highs[-1], lows[-1] = 100.2, 98.8
    signal = ScalpVolumeImbalanceV1().evaluate(_ctx(opens, highs, lows, closes, volumes))
    assert signal is None


def test_no_signal_with_insufficient_history():
    closes = [100.0] * 5
    opens = list(closes)
    volumes = [50.0] * 5
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    assert ScalpVolumeImbalanceV1().evaluate(_ctx(opens, highs, lows, closes, volumes)) is None


def test_spec_covers_all_five_symbols_and_m5_entry():
    spec = ScalpVolumeImbalanceV1().spec
    assert set(spec.symbols) == {
        "XAUUSD",
        "XAGUSD",
        "BTCUSD",
        "Boom 1000 Index",
        "Volatility 75 Index",
    }
    assert spec.entry_timeframe == "M5"
    assert spec.confirmation_timeframes == ("M1", "H1")
