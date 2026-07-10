"""Strategy contract — the interface every generated strategy implements.

Generated code receives a MarketContext and returns a Signal or None.
It has no access to the broker, filesystem, or network: the engine is the
only component that executes trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Signal:
    direction: Direction
    sl_points: float
    tp_points: float
    confidence: float = 1.0  # 0..1
    reason: str = ""


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
