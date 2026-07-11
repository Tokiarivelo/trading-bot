"""Port: order execution, live (MT5 gateway) or simulated (paper)."""

from __future__ import annotations

from typing import Protocol

from src.broker.domain.trading import ExecutionResult, OrderRequest, Position


class BrokerPort(Protocol):
    async def open_position(self, order: OrderRequest) -> ExecutionResult: ...

    async def close_position(self, ticket: int, volume: float | None = None) -> ExecutionResult: ...

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> None: ...

    async def get_positions(self, symbol: str | None = None) -> list[Position]: ...
