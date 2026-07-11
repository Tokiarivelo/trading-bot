from datetime import UTC, datetime

import pytest

from src.backtest.application.period import InvalidPeriod, parse_period


def test_parse_period_single_month():
    start, end = parse_period("2025-01:2025-01")
    assert start == datetime(2025, 1, 1, tzinfo=UTC)
    assert end == datetime(2025, 2, 1, tzinfo=UTC)


def test_parse_period_multi_month_handles_month_lengths():
    start, end = parse_period("2025-01:2025-02")
    assert start == datetime(2025, 1, 1, tzinfo=UTC)
    assert end == datetime(2025, 3, 1, tzinfo=UTC)


def test_parse_period_leap_year_february():
    start, end = parse_period("2024-02:2024-02")
    assert start == datetime(2024, 2, 1, tzinfo=UTC)
    assert end == datetime(2024, 3, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "period",
    ["2025-01", "2025-01:2025-02:2025-03", "not-a-period", "2025-13:2025-14", ""],
)
def test_parse_period_invalid_raises(period):
    with pytest.raises(InvalidPeriod):
        parse_period(period)


def test_parse_period_end_before_start_raises():
    with pytest.raises(InvalidPeriod):
        parse_period("2025-06:2025-01")
