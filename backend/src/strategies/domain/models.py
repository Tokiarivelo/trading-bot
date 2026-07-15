"""Strategy contract — the interface every generated strategy implements.

Generated code receives a MarketContext and returns a Signal or None.
It has no access to the broker, filesystem, or network: the engine is the
only component that executes trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ZoneKind(StrEnum):
    DEMAND = "demand"  # buy zone (support) — price expected to rise from it
    SUPPLY = "supply"  # sell zone (resistance) — price expected to fall from it


@dataclass(frozen=True)
class PriceZone:
    """A supply/demand rectangle a strategy identified before entering —
    chart-annotation data, not used by the engine for execution."""

    kind: ZoneKind
    price_low: float
    price_high: float
    time_start: datetime
    time_end: datetime


class StructureLabel(StrEnum):
    HH = "HH"  # higher high
    HL = "HL"  # higher low
    LH = "LH"  # lower high
    LL = "LL"  # lower low


@dataclass(frozen=True)
class StructurePoint:
    """A single labeled swing point (HH/HL/LH/LL) — chart-annotation data."""

    time: datetime
    price: float
    label: StructureLabel


@dataclass(frozen=True)
class Signal:
    direction: Direction
    sl_points: float
    tp_points: float
    confidence: float = 1.0  # 0..1
    reason: str = ""
    # Optional chart-annotation data a strategy may supply. Not read by the
    # engine — purely for backtest reports / chart drawing, so existing
    # strategies that don't set these keep working unchanged.
    zone: PriceZone | None = None
    pattern: str | None = None
    structure: tuple[StructurePoint, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StrategySpec:
    name: str
    version: int
    symbols: tuple[str, ...]
    entry_timeframe: str  # always "M5" per project rules
    confirmation_timeframes: tuple[str, ...]
    params: dict[str, Any]


@dataclass(frozen=True)
class MarketContext:
    """Everything a strategy may look at. Populated by the engine (Phase 4).

    candles maps timeframe → OHLCV frame (pandas DataFrame at runtime; typed
    loosely here so domain code stays import-light).
    """

    symbol: str
    candles: dict[str, Any]
    spread_points: float


@runtime_checkable
class Strategy(Protocol):
    spec: StrategySpec

    def evaluate(self, ctx: MarketContext) -> Signal | None: ...
