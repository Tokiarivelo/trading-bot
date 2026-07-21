"""Core event types exchanged between modules.

Phase 0 defines the shapes the whole system is built around; later phases
fill in richer payloads as the domain models land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, kw_only=True)
class Event:
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class CandleClosed(Event):
    symbol: str
    timeframe: str  # "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN"


@dataclass(frozen=True, kw_only=True)
class PositionOpened(Event):
    symbol: str
    position_id: str
    side: str  # "buy" | "sell"
    volume: float
    price: float
    sl: float | None
    tp: float | None
    spread_points: int
    comment: str = ""
    strategy_version: str | None = None
    skill: str | None = None
    # Optional chart-annotation data from the strategy's Signal (see
    # strategies/domain/models.py: PriceZone/StructurePoint). Flattened to
    # primitives rather than importing those domain types, same as `side`
    # above being a plain str instead of the broker's Side enum — shared
    # events stay framework/module-independent so any module can subscribe
    # without importing another module's internals.
    zone_kind: str | None = None  # "demand" | "supply"
    zone_price_low: float | None = None
    zone_price_high: float | None = None
    zone_time_start: datetime | None = None
    zone_time_end: datetime | None = None
    pattern: str | None = None
    structure: tuple[tuple[str, float, datetime], ...] = ()
    """Swing points as (label, price, time), label one of HH/HL/LH/LL."""


@dataclass(frozen=True, kw_only=True)
class PositionClosed(Event):
    symbol: str
    position_id: str
    close_price: float
    profit: float


@dataclass(frozen=True, kw_only=True)
class TenTradesCompleted(Event):
    """Emitted by the journal every 10 closed trades for one bot → triggers
    AI review. Scoped by `skill` (a bot's unique `NormalSkill.name`), not
    just `symbol`, since several bots may trade the same symbol
    concurrently, each on its own 10-trade cadence."""

    symbol: str
    skill: str
    trade_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class NewsWindowEntered(Event):
    event_name: str
    symbols: tuple[str, ...]
    close_all: bool = False
    """Whether the matched news skill's `pre_event.close_all` requests
    flattening open positions in `symbols` before the event (§6.6)."""


@dataclass(frozen=True, kw_only=True)
class NewsWindowExited(Event):
    event_name: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class CircuitBreakerTripped(Event):
    """Emitted when the engine pauses — either a risk-manager circuit breaker
    (consecutive losses, daily loss limit) or the manual kill switch (§11).
    Alerting subscribes to this; nothing else does."""

    reason: str


@dataclass(frozen=True, kw_only=True)
class RefinementCompleted(Event):
    """Emitted after the 10-trade AI review loop finishes (§8.2), regardless
    of whether it proposed a refinement. Alerting subscribes to this."""

    symbol: str
    verdict: str
    proposal_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class GatewayHealthChanged(Event):
    """Emitted by `GatewayHealthMonitor` on a gateway-up/terminal-connected
    state transition (Phase 9 reconnect/resume). Alerting subscribes to this."""

    gateway_up: bool
    terminal_connected: bool
