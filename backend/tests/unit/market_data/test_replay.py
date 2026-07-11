from datetime import UTC, datetime

import pytest

from src.market_data.adapters.replay import ReplayMarketDataPort, SymbolSpec
from src.market_data.domain.models import Timeframe

SPEC = SymbolSpec(
    point=0.01,
    digits=2,
    stops_level=0,
    contract_size=100.0,
    volume_min=0.01,
    volume_max=50.0,
    volume_step=0.01,
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_replay(candle_factory) -> ReplayMarketDataPort:
    m5_times = [utc(2026, 7, 10, 9, m) for m in (0, 5, 10, 15, 20)]
    m5 = [candle_factory(t, close=2400.0 + i, spread_points=20) for i, t in enumerate(m5_times)]
    # H1 bar 08:00-09:00 is fully closed by 09:05; the 09:00-10:00 bar is still forming.
    h1 = [
        candle_factory(utc(2026, 7, 10, 8, 0), timeframe=Timeframe.H1, close=2390.0),
        candle_factory(utc(2026, 7, 10, 9, 0), timeframe=Timeframe.H1, close=2450.0),
    ]
    return ReplayMarketDataPort("XAUUSD", {Timeframe.M5: m5, Timeframe.H1: h1}, SPEC)


async def test_get_candles_excludes_future_bars(candle_factory):
    replay = make_replay(candle_factory)
    replay.advance_to(utc(2026, 7, 10, 9, 10))  # the M5 bar opened @09:05 has just closed

    bars = await replay.get_candles("XAUUSD", Timeframe.M5, 10)
    assert [c.time for c in bars] == [utc(2026, 7, 10, 9, 0), utc(2026, 7, 10, 9, 5)]


async def test_get_candles_respects_count(candle_factory):
    replay = make_replay(candle_factory)
    replay.advance_to(utc(2026, 7, 10, 9, 25))

    bars = await replay.get_candles("XAUUSD", Timeframe.M5, 2)
    assert [c.time for c in bars] == [utc(2026, 7, 10, 9, 15), utc(2026, 7, 10, 9, 20)]


async def test_still_forming_higher_timeframe_bar_is_not_visible(candle_factory):
    """No lookahead bias: at 09:05 the H1 08:00-09:00 bar is closed and
    visible, but the 09:00-10:00 bar (which only closes at 10:00) must not be
    — it hasn't happened yet in simulated time."""
    replay = make_replay(candle_factory)
    replay.advance_to(utc(2026, 7, 10, 9, 5))

    bars = await replay.get_candles("XAUUSD", Timeframe.H1, 10)
    assert [c.time for c in bars] == [utc(2026, 7, 10, 8, 0)]


async def test_symbol_info_derives_bid_ask_from_current_m5_bar(candle_factory):
    replay = make_replay(candle_factory)
    replay.advance_to(utc(2026, 7, 10, 9, 5))  # M5 bar closing at 09:05 has close=2400.0

    info = await replay.get_symbol_info("XAUUSD")
    half_spread = 20 * 0.01 / 2
    assert info.bid == pytest.approx(2400.0 - half_spread)
    assert info.ask == pytest.approx(2400.0 + half_spread)
    assert info.spread_points == 20
    assert info.contract_size == 100.0


async def test_get_candles_before_pages_further_back(candle_factory):
    replay = make_replay(candle_factory)
    replay.advance_to(utc(2026, 7, 10, 9, 25))

    bars = await replay.get_candles("XAUUSD", Timeframe.M5, 2, before=utc(2026, 7, 10, 9, 15))
    assert [c.time for c in bars] == [utc(2026, 7, 10, 9, 5), utc(2026, 7, 10, 9, 10)]


async def test_get_candles_before_any_data_raises_without_advance(candle_factory):
    replay = make_replay(candle_factory)
    with pytest.raises(RuntimeError):
        await replay.get_candles("XAUUSD", Timeframe.M5, 5)
