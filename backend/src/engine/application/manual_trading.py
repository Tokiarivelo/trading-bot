"""Risk gate for manually-initiated orders (chart buttons / click-to-trade).

`OrderService`/`trading_routes.py` alone let a manual order bypass every
account-level cap `RiskManager` enforces on automated entries — this closes
that gap by routing manual orders through the same `RiskManager` instance
the engine uses, without adding a `broker` -> `engine` import (which would
create a module cycle, since `engine` already depends on `broker`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.broker.application.order_service import OrderService
from src.broker.domain.trading import (
    ExecutionResult,
    OrderRejected,
    OrderType,
    PendingOrder,
    Side,
)
from src.engine.application.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class ManualTradeGate:
    def __init__(
        self,
        order_service: OrderService,
        risk_manager: RiskManager,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._order_service = order_service
        self._risk_manager = risk_manager
        self._clock = clock

    async def open_position(
        self,
        symbol: str,
        side: Side,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
    ) -> ExecutionResult:
        """Market order: full pretrade gate (pause, max open positions, max
        trades/day) before the fill, then records the trade — the same
        sequence `TradeEngine._try_enter` applies to automated entries."""
        now = self._clock()
        open_count = len(await self._order_service.get_positions())
        decision = self._risk_manager.check_pretrade(open_count, now)
        if not decision.approved:
            raise OrderRejected(decision.reason)
        result = await self._order_service.open_position(symbol, side, volume, sl, tp, comment)
        self._risk_manager.record_trade_opened(now)
        return result

    async def place_pending_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        volume: float,
        price: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
    ) -> PendingOrder:
        """Pending (limit/stop) order: only the pause/kill-switch state is
        checked at placement — `max_open_positions`/`max_trades_per_day`
        describe *open trades*, and a resting order isn't one yet, so those
        are re-checked properly when it actually fills
        (`PositionManager`/`ReconciliationService`)."""
        if self._risk_manager.paused:
            reason = self._risk_manager.status.pause_reason
            raise OrderRejected(f"engine paused: {reason}")
        return await self._order_service.place_pending_order(
            symbol, side, order_type, volume, price, sl, tp, comment
        )
