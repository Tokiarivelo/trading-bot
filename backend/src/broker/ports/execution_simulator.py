"""Port a simulating broker adapter uses to model real broker behaviour.

`PaperBroker` fills whatever it is asked to, at the mid-derived bid/ask, in
whatever lot size arrives. That is fine as a plumbing stub and catastrophic as
a research tool: it is why M1 scalp backtests reported winning trades that a
live broker refuses outright (OBSERVABILITY_PLAN.md Phase 4).

Rather than teaching `PaperBroker` about `stops_level`, lot grids and slippage
directly — which would bake a backtest concern into a broker adapter and force
every existing test to grow broker facts — the behaviour is injected through
this Protocol. `PaperBroker(execution_simulator=None)` keeps the old, frictionless
fills; the backtest runner passes
`src.backtest.adapters.constraint_simulator.BrokerConstraintSimulator`.

Implementations raise `OrderRejected` (with the broker's own retcode) for an
order a real server would refuse, so the rejection travels the same code path
a live refusal does and lands on the Phase 1/2 decision trail unchanged.
"""

from __future__ import annotations

from typing import Protocol

from src.broker.domain.broker_constraints import SimulatedEntry
from src.broker.domain.trading import Side
from src.market_data.domain.models import SymbolInfo


class ExecutionSimulatorPort(Protocol):
    def simulate_entry(
        self,
        *,
        symbol: str,
        side: Side,
        volume: float,
        sl: float | None,
        tp: float | None,
        info: SymbolInfo,
    ) -> SimulatedEntry:
        """Broker-legal lot size and realistic fill price for an entry.

        Raises `src.broker.domain.trading.OrderRejected` — carrying the MT5
        retcode the live server would have returned — when the order would be
        refused rather than filled."""
