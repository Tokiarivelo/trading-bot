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
