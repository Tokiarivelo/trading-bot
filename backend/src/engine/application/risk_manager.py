"""Risk manager (§6.4, §7.1): lot sizing, pre-trade caps, circuit breakers.

Engine-level code — AI refinement logic must never touch this file (see
CLAUDE.md). `RiskCaps` are read from `configs/risk.yaml` at the composition
root and treated as read-only here.
"""

from __future__ import annotations

import dataclasses
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
            return RiskDecision(
                approved=False,
                reason=f"sl distance must be positive (got {sl_distance_price:.5f})",
            )
        if balance <= 0:
            return RiskDecision(
                approved=False, reason=f"balance must be positive (got {balance:.2f})"
            )
        risk_amount = balance * (self._caps.risk_per_trade_pct / 100) * risk_multiplier
        raw_volume = risk_amount / (sl_distance_price * contract_size)
        steps = math.floor(raw_volume / volume_step)
        volume = round(steps * volume_step, 8)
        if volume < volume_min:
            if not self._caps.min_lot_fallback_enabled:
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"computed volume {volume:.4f} lots < broker minimum {volume_min:.4f} "
                        f"lots (risk_amount=${risk_amount:.2f} = balance ${balance:.2f} x "
                        f"{self._caps.risk_per_trade_pct}% x multiplier {risk_multiplier:.2f}) "
                        "— enable min_lot_fallback_enabled to trade the minimum lot anyway"
                    ),
                )
            # Rounding *up* to volume_min unconditionally would silently risk
            # more than risk_per_trade_pct allows. Instead of always
            # rejecting, fall back to the broker minimum lot as long as *its*
            # effective risk stays under max_risk_per_trade_pct (a wider,
            # user-owned ceiling — see configs/risk.yaml) — this is what lets
            # the bot still trade a small account instead of going silent.
            ceiling = self._caps.max_risk_per_trade_pct
            if ceiling is None:
                ceiling = self._caps.risk_per_trade_pct
            min_lot_risk_amount = volume_min * sl_distance_price * contract_size
            min_lot_risk_pct = min_lot_risk_amount / balance * 100
            if min_lot_risk_pct > ceiling:
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"computed volume {volume:.4f} lots < broker minimum "
                        f"{volume_min:.4f} lots, and the minimum lot's risk "
                        f"({min_lot_risk_pct:.2f}% of balance) exceeds the "
                        f"max_risk_per_trade_pct ceiling ({ceiling:.2f}%) "
                        f"(risk_amount=${risk_amount:.2f} = balance ${balance:.2f} x "
                        f"{self._caps.risk_per_trade_pct}% x multiplier {risk_multiplier:.2f})"
                    ),
                )
            logger.info(
                "risk manager: min-lot fallback — %.4f lots forced (effective risk "
                "%.2f%% of balance $%.2f, vs configured %.2f%%, under ceiling %.2f%%)",
                volume_min,
                min_lot_risk_pct,
                balance,
                self._caps.risk_per_trade_pct,
                ceiling,
            )
            return RiskDecision(approved=True, volume=min(volume_min, volume_max))
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

    @property
    def caps(self) -> RiskCaps:
        return self._caps

    def set_min_lot_fallback(self, *, enabled: bool, max_risk_per_trade_pct: float | None) -> None:
        """Live-updates the min-lot fallback (see `size_position`) on the
        running engine — takes effect on the very next sizing decision.
        Only touches these two fields; every other cap stays whatever
        `configs/risk.yaml` set at startup. Not persisted to disk: a
        restart reverts to the file, which the human edits directly to
        change the default (see CLAUDE.md)."""
        self._caps = dataclasses.replace(
            self._caps,
            min_lot_fallback_enabled=enabled,
            max_risk_per_trade_pct=max_risk_per_trade_pct,
        )
        logger.info(
            "risk manager: min-lot fallback updated live — enabled=%s max_risk_per_trade_pct=%s",
            enabled,
            max_risk_per_trade_pct,
        )
