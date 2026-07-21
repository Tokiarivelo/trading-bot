import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.scalp_vwap_reversion_v1_v1 import ScalpVwapReversionV1

N_WARMUP = 45  # MIN_HISTORY (46) - 1: enough for the 30-bar deviation window + ATR(14)


def _ctx(opens: list[float], highs: list[float], lows: list[float],
         closes: list[float], volumes: list[float]) -> MarketContext:
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "tick_volume": volumes}
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def _warmup_and_stretch(stretch_close: float, stretch_open: float) -> MarketContext:
    # High-volume, tightly oscillating warmup anchors VWAP near 100 with a
    # small nonzero stdev; the final bar carries little volume (barely moves
    # the cumulative VWAP) but stretches far from it.
    closes = [100.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(N_WARMUP)]
    opens = list(closes)
    volumes = [1000.0] * N_WARMUP
    closes.append(stretch_close)
    opens.append(stretch_open)
    volumes.append(10.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    return _ctx(opens, highs, lows, closes, volumes)


def test_buy_signal_on_downward_stretch_with_bullish_reversal_candle():
    strategy = ScalpVwapReversionV1()
    signal = strategy.evaluate(_warmup_and_stretch(stretch_close=90.0, stretch_open=89.0))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    spread_distance = 25.0 * 0.01  # ctx.spread_points * XAUUSD point size
    assert signal.tp_points == (signal.sl_points + spread_distance) * strategy.spec.params["tp_rr"]


def test_sell_signal_on_upward_stretch_with_bearish_reversal_candle():
    signal = ScalpVwapReversionV1().evaluate(
        _warmup_and_stretch(stretch_close=110.0, stretch_open=111.0)
    )

    assert signal is not None
    assert signal.direction is Direction.SELL


def test_no_signal_when_stretch_candle_has_not_reversed_yet():
    # Same downward stretch, but the last candle is still bearish (open >
    # close) -- the move hasn't shown any reversion yet, so no BUY.
    signal = ScalpVwapReversionV1().evaluate(
        _warmup_and_stretch(stretch_close=90.0, stretch_open=91.0)
    )
    assert signal is None


def test_no_signal_without_meaningful_deviation():
    closes = [100.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(N_WARMUP + 1)]
    opens = list(closes)
    volumes = [1000.0] * len(closes)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    assert ScalpVwapReversionV1().evaluate(_ctx(opens, highs, lows, closes, volumes)) is None


def test_no_signal_with_insufficient_history():
    closes = [100.0] * 10
    opens = list(closes)
    volumes = [100.0] * 10
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    assert ScalpVwapReversionV1().evaluate(_ctx(opens, highs, lows, closes, volumes)) is None


def test_spec_covers_all_five_symbols_and_carries_no_confirmation_timeframes():
    spec = ScalpVwapReversionV1().spec
    assert set(spec.symbols) == {
        "XAUUSD",
        "XAGUSD",
        "BTCUSD",
        "Boom 1000 Index",
        "Volatility 75 Index",
    }
    assert spec.entry_timeframe == "M5"
    # Deliberately empty -- see the module docstring on the mtf_confirm veto risk.
    assert spec.confirmation_timeframes == ()
