"""Port the trading path writes its decision trail through.

`engine/application/trade_loop.py` and `broker/application/order_service.py`
depend on this Protocol only — never on `activity/adapters` — so the
application layer stays free of SQLAlchemy (CLAUDE.md, hexagonal rule). The
concrete implementation is `activity.application.signal_decision_service.
SignalDecisionService`, wired in `container.py`; both call sites accept
`None` (no sink) so the backtest runner and unit tests can build an engine
without a database.

`account_id` is deliberately absent from the interface: the sink is built
per account and stamps it, so the engine never has to know which account it
belongs to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class SignalDecisionSinkPort(Protocol):
    async def record(
        self,
        *,
        signal_id: str,
        bot: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        direction: str,
        price: float | None,
        created_at: datetime,
        reason: str,
        confidence: float | None,
    ) -> None:
        """Records a freshly fired signal with no terminal outcome yet
        (`outcome="skipped"`)."""

    async def record_outcome(
        self, signal_id: str, outcome: str, *, reason: str | None = None
    ) -> None:
        """Sets what the engine/broker finally did with the signal. Must never
        be able to downgrade an already-`opened` decision."""
