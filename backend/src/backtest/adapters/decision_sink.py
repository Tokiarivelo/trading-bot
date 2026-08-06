"""In-memory `SignalDecisionSinkPort` for backtests (OBSERVABILITY_PLAN.md
Phase 4, deliverable 4).

Before this, a backtest's signal list was reconstructed by regex-scraping the
replay's own log lines (`application/signals.py`) onto the **pre-Phase-2**
outcome vocabulary, which collapsed the HTF veto, the volatility guard, the
max-positions cap, the sizing failure and the daily-loss breaker into a single
`risk_rejected` bucket. The live funnel had already moved to the split
vocabulary in Phase 2, so live and backtest funnels could not be compared at
all — which is precisely what Phase 4's divergence report needs to do.

The engine and the order service already write every decision through
`SignalDecisionSinkPort`; live that sink is the database-backed
`SignalDecisionService`. A backtest just needs a sink that keeps them in
memory. No log parsing, no message-wording coupling, and the outcomes are the
same closed vocabulary (`SIGNAL_OUTCOMES`) the live path emits.

`account_id` is not part of the port (the sink stamps it), so a backtest's
decisions carry the constant `"backtest"`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.activity.domain.models import DecisionCheck, SignalDecision
from src.backtest.domain.models import BacktestSignal

BACKTEST_ACCOUNT_ID = "backtest"


class InMemorySignalDecisionSink:
    """Collects `SignalDecision`s in emission order.

    Mirrors the two invariants of the DB-backed service:

    * an already-`opened` decision is never downgraded — a multi-target signal
      whose first target fills and whose second is rejected stays `opened`,
      because the signal did become a trade;
    * `checks` append rather than replace, so every gate a signal walked past
      is on the record, not just the last one.
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._decisions: dict[str, SignalDecision] = {}

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
        if signal_id in self._decisions:
            return
        self._order.append(signal_id)
        self._decisions[signal_id] = SignalDecision(
            signal_id=signal_id,
            account_id=BACKTEST_ACCOUNT_ID,
            bot=bot,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            price=price,
            created_at=created_at,
            outcome="skipped",
            reason=reason,
            confidence=confidence,
        )

    async def record_outcome(
        self,
        signal_id: str,
        outcome: str,
        *,
        reason: str | None = None,
        checks: tuple[DecisionCheck, ...] = (),
    ) -> None:
        current = self._decisions.get(signal_id)
        if current is None:
            return
        if current.outcome == "opened" and outcome != "opened":
            # Still record the checks — the rejected second target's numbers
            # are real — but keep the terminal outcome.
            self._decisions[signal_id] = replace(current, checks=current.checks + checks)
            return
        self._decisions[signal_id] = replace(
            current,
            outcome=outcome,
            reason=current.reason if reason is None else reason,
            checks=current.checks + checks,
        )

    async def record_checks(self, signal_id: str, checks: tuple[DecisionCheck, ...]) -> None:
        current = self._decisions.get(signal_id)
        if current is None or not checks:
            return
        self._decisions[signal_id] = replace(current, checks=current.checks + checks)

    # ── reporting ────────────────────────────────────────────────────────────

    def decisions(self) -> tuple[SignalDecision, ...]:
        """Every decision recorded, in the order the signals fired."""
        return tuple(self._decisions[signal_id] for signal_id in self._order)

    def signals(self) -> tuple[BacktestSignal, ...]:
        """The decisions projected onto the report's `BacktestSignal` shape.

        Same type the log-scraper produced, so nothing downstream changes —
        but the `outcome` values are now the Phase 2 vocabulary rather than the
        collapsed one, and they come from the engine's own structured
        recording instead of its prose."""
        return tuple(
            BacktestSignal(
                time=decision.created_at,
                direction=decision.direction,
                outcome=decision.outcome,
                reason=decision.reason,
                price=decision.price,
            )
            for decision in self.decisions()
        )
