from datetime import UTC, datetime

import pytest

from src.market_data.domain.models import Candle, Timeframe


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


class TestTimeframe:
    def test_seconds(self):
        assert Timeframe.M1.seconds == 60
        assert Timeframe.M5.seconds == 300
        assert Timeframe.M15.seconds == 900
        assert Timeframe.M30.seconds == 1800
        assert Timeframe.H1.seconds == 3600
        assert Timeframe.H4.seconds == 14400
        assert Timeframe.D1.seconds == 86400
        assert Timeframe.W1.seconds == 604800

    @pytest.mark.parametrize(
        ("timeframe", "moment", "expected"),
        [
            (Timeframe.M1, utc(2026, 7, 10, 14, 3, 21), utc(2026, 7, 10, 14, 3)),
            (Timeframe.M5, utc(2026, 7, 10, 14, 3, 21), utc(2026, 7, 10, 14, 0)),
            (Timeframe.M5, utc(2026, 7, 10, 14, 5, 0), utc(2026, 7, 10, 14, 5)),
            (Timeframe.M15, utc(2026, 7, 10, 14, 22), utc(2026, 7, 10, 14, 15)),
            (Timeframe.M30, utc(2026, 7, 10, 14, 45), utc(2026, 7, 10, 14, 30)),
            (Timeframe.H1, utc(2026, 7, 10, 14, 59, 59), utc(2026, 7, 10, 14, 0)),
            (Timeframe.H4, utc(2026, 7, 10, 14, 3), utc(2026, 7, 10, 12, 0)),
            (Timeframe.D1, utc(2026, 7, 10, 23, 59), utc(2026, 7, 10, 0, 0)),
            # 2026-07-10 is a Friday; the containing week opened Monday 2026-07-06.
            (Timeframe.W1, utc(2026, 7, 10, 23, 59), utc(2026, 7, 6, 0, 0)),
            (Timeframe.W1, utc(2026, 7, 6, 0, 0), utc(2026, 7, 6, 0, 0)),
            (Timeframe.MN, utc(2026, 7, 10, 23, 59), utc(2026, 7, 1, 0, 0)),
        ],
    )
    def test_bar_open(self, timeframe, moment, expected):
        assert timeframe.bar_open(moment) == expected

    def test_last_closed_open_is_previous_bar(self):
        # At 14:03 the 13:55 bar is the latest fully closed M5 bar.
        assert Timeframe.M5.last_closed_open(utc(2026, 7, 10, 14, 3)) == utc(2026, 7, 10, 13, 55)
        # Exactly on a boundary, the bar that just closed is the previous one.
        assert Timeframe.M5.last_closed_open(utc(2026, 7, 10, 14, 0)) == utc(2026, 7, 10, 13, 55)
        # M1 works the same way at its own (1-minute) granularity.
        assert Timeframe.M1.last_closed_open(utc(2026, 7, 10, 14, 3, 21)) == utc(2026, 7, 10, 14, 2)

    def test_last_closed_open_across_calendar_boundaries(self):
        # The previous week opened Monday 2026-06-29.
        assert Timeframe.W1.last_closed_open(utc(2026, 7, 10)) == utc(2026, 6, 29, 0, 0)
        # The previous month is June, even though July only has 31 days.
        assert Timeframe.MN.last_closed_open(utc(2026, 7, 10)) == utc(2026, 6, 1, 0, 0)
        # Crossing a year boundary: December is the month before January.
        assert Timeframe.MN.last_closed_open(utc(2027, 1, 15)) == utc(2026, 12, 1, 0, 0)

    def test_close_of_handles_variable_month_length(self):
        # January (31 days) closes into February; February (28 days in a
        # non-leap year) closes into March.
        assert Timeframe.MN.close_of(utc(2026, 1, 1)) == utc(2026, 2, 1)
        assert Timeframe.MN.close_of(utc(2026, 2, 1)) == utc(2026, 3, 1)
        assert Timeframe.MN.close_of(utc(2026, 12, 1)) == utc(2027, 1, 1)


def make_candle(**overrides) -> Candle:
    defaults = dict(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        time=utc(2026, 7, 10, 14, 0),
        open=2400.0,
        high=2401.0,
        low=2399.0,
        close=2400.5,
        tick_volume=1000,
        spread_points=25,
    )
    return Candle(**{**defaults, **overrides})


class TestCandle:
    def test_close_time(self):
        assert make_candle().close_time == utc(2026, 7, 10, 14, 5)

    def test_is_closed(self):
        candle = make_candle()
        assert not candle.is_closed(utc(2026, 7, 10, 14, 4, 59))
        assert candle.is_closed(utc(2026, 7, 10, 14, 5, 0))
