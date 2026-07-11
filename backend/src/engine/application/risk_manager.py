"""Risk manager (§6.4, §7.1): lot sizing, pre-trade caps, circuit breakers.

Engine-level code — AI refinement logic must never touch this file (see
CLAUDE.md). `RiskCaps` are read from `configs/risk.yaml` at the composition
root and treated as read-only here.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.engine.domain.models import EngineStatus, RiskCaps, RiskDecision

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, caps: RiskCaps, timezone: str = "UTC") -> None:
        self._caps = caps
        self._tz = ZoneInfo(timezone)
        self._paused = False
        self._pause_reason = ""
        self._consecutive_losses = 0
        self._trades_today = 0
        self._daily_pnl = 0.0
        self._today: date | None = None

    @property
    def status(self) -> EngineStatus:
        return EngineStatus(
            enabled=True,
            paused=self._paused,
            pause_reason=self._pause_reason,
            consecutive_losses=self._consecutive_losses,
            trades_today=self._trades_today,
            daily_pnl=self._daily_pnl,
        )

    def _roll_day_if_needed(self, now: datetime) -> None:
        today = now.astimezone(self._tz).date()
        if self._today is None:
            self._today = today
            return
        if today != self._today:
            self._today = today
            self._trades_today = 0
            self._daily_pnl = 0.0
            logger.info("risk manager: new trading day, daily counters reset")

    def check_pretrade(
        self, open_positions_count: int, now: datetime | None = None
    ) -> RiskDecision:
        """Caps that don't depend on lot sizing: pause state, position/trade counts."""
        now = now or datetime.now(self._tz)
        self._roll_day_if_needed(now)
        if self._paused:
            return RiskDecision(approved=False, reason=f"engine paused: {self._pause_reason}")
        if open_positions_count >= self._caps.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"max open positions reached ({self._caps.max_open_positions})",
            )
        if self._trades_today >= self._caps.max_trades_per_day:
            return RiskDecision(
                approved=False,
                reason=f"max trades per day reached ({self._caps.max_trades_per_day})",
            )
        return RiskDecision(approved=True)

    def size_position(
        self,
        *,
        balance: float,
        sl_distance_price: float,
        contract_size: float,
        volume_min: float,
        volume_max: float,
        volume_step: float,
        risk_multiplier: float = 1.0,
    ) -> RiskDecision:
        if sl_distance_price <= 0:
            return RiskDecision(approved=False, reason="sl distance must be positive")
        risk_amount = balance * (self._caps.risk_per_trade_pct / 100) * risk_multiplier
        raw_volume = risk_amount / (sl_distance_price * contract_size)
        steps = math.floor(raw_volume / volume_step)
        volume = round(steps * volume_step, 8)
        # Rounding *up* to volume_min would risk more than risk_per_trade_pct
        # allows, silently exceeding the user-owned cap — reject instead.
        if volume < volume_min:
            return RiskDecision(approved=False, reason="computed volume below broker minimum")
        volume = min(volume, volume_max)
        return RiskDecision(approved=True, volume=volume)

    def record_trade_opened(self, now: datetime | None = None) -> None:
        now = now or datetime.now(self._tz)
        self._roll_day_if_needed(now)
        self._trades_today += 1

    def record_trade_closed(
        self, profit: float, balance: float | None = None, now: datetime | None = None
    ) -> None:
        """Update circuit-breaker counters after a fill closes.

        `balance` (equity after the fill) is optional so callers that only
        care about the consecutive-loss breaker don't need an account
        round-trip; the daily-loss breaker is skipped without it.
        """
        now = now or datetime.now(self._tz)
        self._roll_day_if_needed(now)
        self._daily_pnl += profit
        if profit < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        if self._consecutive_losses >= self._caps.consecutive_loss_pause:
            self._trigger_pause(
                f"{self._consecutive_losses} consecutive losses "
                f"(cap {self._caps.consecutive_loss_pause})"
            )
        elif balance and self._daily_pnl < 0:
            loss_pct = -self._daily_pnl / balance * 100
            if loss_pct >= self._caps.daily_loss_limit_pct:
                self._trigger_pause(
                    f"daily loss {loss_pct:.2f}% >= limit {self._caps.daily_loss_limit_pct}%"
                )

    def _trigger_pause(self, reason: str) -> None:
        if self._paused:
            return
        self._paused = True
        self._pause_reason = reason
        logger.warning("circuit breaker tripped: %s", reason)

    def kill(self, reason: str = "manual kill switch") -> None:
        self._trigger_pause(reason)

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = ""
        self._consecutive_losses = 0
        logger.info("engine resumed by operator")

    @property
    def paused(self) -> bool:
        return self._paused
