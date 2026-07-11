"""Port: order execution, live (MT5 gateway) or simulated (paper)."""

from __future__ import annotations

from typing import Protocol

from src.broker.domain.trading import (
    ClosedPositionInfo,
    ExecutionResult,
    OrderRequest,
    PendingOrder,
    PendingOrderRequest,
    Position,
)


class BrokerPort(Protocol):
    async def open_position(self, order: OrderRequest) -> ExecutionResult: ...

    async def close_position(self, ticket: int, volume: float | None = None) -> ExecutionResult: ...

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> None: ...

    async def get_positions(self, symbol: str | None = None) -> list[Position]: ...

    async def get_close_info(self, ticket: int) -> ClosedPositionInfo | None:
        """How `ticket` actually closed, if the broker no longer shows it
        open — `None` when there's no such history (paper mode, unknown
        ticket, or purged history). Used only for reconciliation
        (`broker/application/reconciliation.py`)."""
        ...

    async def place_pending_order(self, order: PendingOrderRequest) -> PendingOrder: ...

    async def cancel_pending_order(self, ticket: int) -> None: ...

    async def modify_pending_order(
        self, ticket: int, price: float | None, sl: float | None, tp: float | None
    ) -> None: ...

    async def get_pending_orders(self, symbol: str | None = None) -> list[PendingOrder]: ...

    @property
    def simulates_pending_fills(self) -> bool:
        """True for adapters (paper) that must trigger their own resting
        orders once price crosses; False for adapters (live) whose broker
        triggers pending orders server-side — callers use this to decide
        between self-triggering a fill and waiting to reconcile one."""
        ...
