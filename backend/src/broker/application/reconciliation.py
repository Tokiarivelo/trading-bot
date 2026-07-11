"""Position reconciliation (Phase 9 §12): detects trades the broker closed
without the backend's involvement — a server-side SL/TP fill, or any close
that happened while the backend was down — and republishes `PositionClosed`
so the journal, risk-manager circuit breakers, and 10-trade review trigger
all see it exactly as if `OrderService.close_position` had been called.

Two entry points:
  - `reconcile_all()`: startup/reconnect — diffs the journal's persisted
    open trades against the broker's current open positions, across all
    symbols. Catches closes that happened while the backend was completely
    down.
  - `reconcile_vanished()`: mid-session — `PositionManager.on_candle_closed`
    already knows exactly which tickets disappeared between two M5 closes;
    this just resolves and republishes them. Catches a live SL/TP fill
    during normal operation, which nothing else in the system detects.
"""

from __future__ import annotations

import logging

from src.broker.ports.trading import BrokerPort
from src.journal.application.trade_journal import TradeJournalService
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed

logger = logging.getLogger(__name__)


class ReconciliationService:
    def __init__(
        self, broker: BrokerPort, journal: TradeJournalService, event_bus: EventBus
    ) -> None:
        self._broker = broker
        self._journal = journal
        self._event_bus = event_bus

    async def reconcile_all(self) -> None:
        open_trades = await self._journal.get_open_trades()
        if not open_trades:
            return
        open_tickets = {p.ticket for p in await self._broker.get_positions()}
        stale = [t for t in open_trades if int(t.id) not in open_tickets]
        for trade in stale:
            await self._close_from_history(trade.symbol, trade.id)

    async def reconcile_vanished(self, symbol: str, vanished_tickets: set[int]) -> None:
        for ticket in vanished_tickets:
            await self._close_from_history(symbol, str(ticket))

    async def _close_from_history(self, symbol: str, ticket_id: str) -> None:
        info = await self._broker.get_close_info(int(ticket_id))
        if info is None:
            logger.warning(
                "reconciliation: no close history for ticket=%s symbol=%s — still unresolved, "
                "will retry next reconciliation pass",
                ticket_id,
                symbol,
            )
            return
        await self._event_bus.publish(
            PositionClosed(
                symbol=symbol,
                position_id=ticket_id,
                close_price=info.price,
                profit=info.profit,
                occurred_at=info.time,
            )
        )
        logger.info(
            "reconciled broker-side close: ticket=%s symbol=%s profit=%.2f",
            ticket_id,
            symbol,
            info.profit,
        )
