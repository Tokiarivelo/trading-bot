import pandas as pd

from src.engine.application.mtf_confirm import confirm
from src.strategies.domain.models import Direction, MarketContext


def _trending_frame(n: int, step: float) -> pd.DataFrame:
    closes = [100.0 + i * step for i in range(n)]
    return pd.DataFrame({"close": closes})


def _ctx(**frames: pd.DataFrame) -> MarketContext:
    return MarketContext(symbol="XAUUSD", candles=frames, spread_points=25.0)


def test_confirms_buy_when_htf_trend_agrees():
    ctx = _ctx(H1=_trending_frame(60, step=0.5), H4=_trending_frame(60, step=0.5))
    confirmed, reason = confirm(Direction.BUY, ctx, ("H1", "H4"))
    assert confirmed
    assert reason == ""


def test_vetoes_buy_when_htf_trend_disagrees():
    ctx = _ctx(H1=_trending_frame(60, step=-0.5))
    confirmed, reason = confirm(Direction.BUY, ctx, ("H1",))
    assert not confirmed
    assert "H1" in reason


def test_vetoes_sell_when_htf_trend_disagrees():
    ctx = _ctx(H1=_trending_frame(60, step=0.5))
    confirmed, reason = confirm(Direction.SELL, ctx, ("H1",))
    assert not confirmed


def test_insufficient_history_does_not_block():
    ctx = _ctx(H1=_trending_frame(10, step=-5.0))  # far below slow_period+1
    confirmed, reason = confirm(Direction.BUY, ctx, ("H1",))
    assert confirmed
    assert reason == ""


def test_missing_timeframe_does_not_block():
    ctx = _ctx(H1=_trending_frame(60, step=0.5))
    confirmed, _ = confirm(Direction.BUY, ctx, ("H1", "H4"))  # H4 absent from ctx.candles
    assert confirmed
