"""Backtest-only account + trade recorder.

Serves two roles behind one explicit, single-writer flow — no reliance on
`asyncio.gather` handler-ordering for money math (CLAUDE.md: money-touching
code paths must be explicit over clever):

- Duck-typed as an `AccountService` (`async status()`) so `TradeEngine` can
  size positions against a simulated balance instead of a live MT5 account.
- The sole `PositionClosed` subscriber: updates balance, feeds the
  `RiskManager` circuit breakers, and records a `BacktestTrade`. Because it's
  the only writer, there's no question of which handler ran first.

`TradeEngine.on_position_closed` must NOT also be subscribed to the backtest
event bus — this class replaces that responsibility entirely.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.backtest.domain.models import BacktestTrade, EquityPoint
from src.engine.application.risk_manager import RiskManager
from src.shared.events.definitions import PositionClosed, PositionOpened


@dataclass
class _OpenLeg:
    side: str
    volume: float
    open_time: datetime
    open_price: float
    sl: float | None
    tp: float | None


class BacktestBookkeeper:
    def __init__(
        self,
        starting_balance: float,
        risk_manager: RiskManager,
        contract_size: float,
        clock: Callable[[], datetime],
    ) -> None:
        self.balance = starting_balance
        self._risk_manager = risk_manager
        self._contract_size = contract_size
        self._clock = clock
        self._open: dict[str, _OpenLeg] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = [
            EquityPoint(time=clock(), balance=starting_balance)
        ]

    async def status(self) -> dict[str, Any]:
        return {"account": {"balance": self.balance}}

    async def on_position_opened(self, event: PositionOpened) -> None:
        self._open[event.position_id] = _OpenLeg(
            side=event.side,
            volume=event.volume,
            open_time=self._clock(),
            open_price=event.price,
            sl=event.sl,
            tp=event.tp,
        )

    async def on_position_closed(self, event: PositionClosed) -> None:
        self.balance += event.profit
        now = self._clock()
        self._risk_manager.record_trade_closed(event.profit, balance=self.balance, now=now)
        self.equity_curve.append(EquityPoint(time=now, balance=self.balance))

        leg = self._open.pop(event.position_id, None)
        if leg is None:
            return  # shouldn't happen outside adversarial tests, but don't crash a report over it
        r_multiple = None
        if leg.sl is not None:
            initial_risk = abs(leg.open_price - leg.sl) * leg.volume * self._contract_size
            if initial_risk > 0:
                r_multiple = event.profit / initial_risk
        self.trades.append(
            BacktestTrade(
                side=leg.side,
                volume=leg.volume,
                open_time=leg.open_time,
                open_price=leg.open_price,
                sl=leg.sl,
                tp=leg.tp,
                close_time=now,
                close_price=event.close_price,
                profit=event.profit,
                r_multiple=r_multiple,
            )
        )
