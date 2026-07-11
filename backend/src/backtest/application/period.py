"""Parses the CLI's `YYYY-MM:YYYY-MM` period argument into a UTC [start, end) range."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime


class InvalidPeriod(Exception):
    pass


def parse_period(period: str) -> tuple[datetime, datetime]:
    """`"2025-01:2025-06"` -> (2025-01-01, 2025-07-01), both UTC midnight —
    `end` is exclusive, one day past the last day of the end month."""
    parts = period.split(":")
    if len(parts) != 2:
        raise InvalidPeriod(f"expected 'YYYY-MM:YYYY-MM', got {period!r}")
    try:
        start = _month_start(parts[0])
        end_month_start = _month_start(parts[1])
    except ValueError as exc:
        raise InvalidPeriod(f"expected 'YYYY-MM:YYYY-MM', got {period!r}: {exc}") from exc
    end = _next_month(end_month_start)
    if end <= start:
        raise InvalidPeriod(f"end of period must be after start: {period!r}")
    return start, end


def _month_start(token: str) -> datetime:
    year_str, month_str = token.split("-")
    return datetime(int(year_str), int(month_str), 1, tzinfo=UTC)


def _next_month(month_start: datetime) -> datetime:
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    epoch = int(month_start.timestamp()) + days_in_month * 86400
    return datetime.fromtimestamp(epoch, tz=UTC)
