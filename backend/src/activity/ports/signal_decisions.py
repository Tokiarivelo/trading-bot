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

from src.activity.domain.models import DecisionCheck


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
        regime_volatility: str | None = None,
        regime_volatility_percentile: float | None = None,
        regime_trend: str | None = None,
        regime_adx: float | None = None,
        regime_session: str | None = None,
    ) -> None:
        """Records a freshly fired signal with no terminal outcome yet
        (`outcome="skipped"`). `regime_*` (OBSERVABILITY_PLAN.md Phase 6) is
        the market-regime snapshot the engine computed at signal time
        (`engine.domain.regime.compute_entry_regime`) — optional and
        defaulted so every pre-Phase-6 caller keeps working unchanged;
        `None` when the entry timeframe had no candles to classify."""

    async def record_outcome(
        self,
        signal_id: str,
        outcome: str,
        *,
        reason: str | None = None,
        checks: tuple[DecisionCheck, ...] = (),
    ) -> None:
        """Sets what the engine/broker finally did with the signal. Must never
        be able to downgrade an already-`opened` decision.

        `checks` are appended to the decision's existing ones, so a gate can
        record the numbers it saw (pass or fail) without knowing what earlier
        gates already stamped. Passing `outcome` unchanged from the current
        value is the way a *passing* gate records its check.
        """

    async def record_checks(
        self, signal_id: str, checks: tuple[DecisionCheck, ...]
    ) -> None:
        """Appends passed-gate checks without touching the outcome — how the
        engine records the gates a signal cleared on its way down."""
