"""Engine domain: risk caps, trade plans, and circuit-breaker state.

Pure values — no I/O. `RiskCaps` mirrors `configs/risk.yaml` (user-owned,
read-only from here — see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class RiskCaps:
    risk_per_trade_pct: float
    daily_loss_limit_pct: float
    max_open_positions: int
    max_trades_per_day: int
    consecutive_loss_pause: int
    # Broker-minimum-lot fallback (see RiskManager.size_position): when the
    # balance is too small for risk_per_trade_pct to reach volume_min,
    # sizing normally rejects outright. Setting min_lot_fallback_enabled
    # trades the broker minimum lot instead, as long as *that lot's*
    # effective risk stays under max_risk_per_trade_pct (None falls back to
    # risk_per_trade_pct itself as the ceiling).
    min_lot_fallback_enabled: bool = False
    max_risk_per_trade_pct: float | None = None


@dataclass(frozen=True, kw_only=True)
class RiskDecision:
    approved: bool
    volume: float = 0.0
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class EngineStatus:
    enabled: bool
    paused: bool
    pause_reason: str = ""
    consecutive_losses: int = 0
    trades_today: int = 0
    daily_pnl: float = 0.0
