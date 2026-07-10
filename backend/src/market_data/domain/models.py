"""Market data domain: timeframes, candles, ticks, symbol specs.

Pure values — no I/O, no framework imports. All times are UTC; candle `time`
is the bar's open time, matching MT5 and lightweight-charts conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_TIMEFRAME_SECONDS = {"M5": 300, "H1": 3600, "H4": 14400, "D1": 86400}


class Timeframe(StrEnum):
    M5 = "M5"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def seconds(self) -> int:
        return _TIMEFRAME_SECONDS[self.value]

    def bar_open(self, moment: datetime) -> datetime:
        """Open time of the bar containing `moment` (UTC-aligned; broker
        server-time offsets for D1 are a Phase 4 concern)."""
        epoch = int(moment.timestamp())
        return datetime.fromtimestamp(epoch - epoch % self.seconds, tz=UTC)

    def last_closed_open(self, now: datetime) -> datetime:
        """Open time of the most recent fully closed bar at `now`."""
        return datetime.fromtimestamp(int(self.bar_open(now).timestamp()) - self.seconds, tz=UTC)


@dataclass(frozen=True, kw_only=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    time: datetime  # bar open, UTC
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_points: int

    @property
    def close_time(self) -> datetime:
        return datetime.fromtimestamp(int(self.time.timestamp()) + self.timeframe.seconds, tz=UTC)

    def is_closed(self, now: datetime) -> bool:
        return now >= self.close_time


@dataclass(frozen=True, kw_only=True)
class Tick:
    symbol: str
    time: datetime
    bid: float
    ask: float


@dataclass(frozen=True, kw_only=True)
class SymbolInfo:
    symbol: str
    bid: float
    ask: float
    spread_points: int
    point: float
    digits: int
    stops_level: int
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float


class MarketDataUnavailable(Exception):
    """Gateway unreachable, not logged in, or the terminal rejected the call."""
