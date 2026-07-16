"""`_auto_resume_daily_breaker` — the backtest-only day-boundary resume of
the daily-loss circuit breaker (live, the operator resumes manually; a
backtest has no operator, so without this a single ≥limit losing day
silently ended the whole run)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.backtest.application.run_backtest import _auto_resume_daily_breaker
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps

NOW = datetime(2026, 3, 8, 6, 40, tzinfo=UTC)


def _caps() -> RiskCaps:
    return RiskCaps(
        risk_per_trade_pct=0.5,
        daily_loss_limit_pct=2.0,
        max_open_positions=100,
        max_trades_per_day=8,
        consecutive_loss_pause=10,
        min_lot_fallback_enabled=True,
        max_risk_per_trade_pct=2.0,
    )


def _trip_daily_loss(rm: RiskManager) -> None:
    # A single -2.5% day on a 10_000 balance trips the 2.0% daily breaker.
    rm.record_trade_closed(profit=-250.0, balance=10_000.0, now=NOW)
    assert rm.paused
    assert rm.status.pause_reason.startswith("daily loss")


def test_resumes_daily_loss_pause():
    rm = RiskManager(caps=_caps())
    _trip_daily_loss(rm)
    _auto_resume_daily_breaker(rm)
    assert not rm.paused


def test_leaves_consecutive_loss_pause_alone():
    rm = RiskManager(caps=_caps())
    for _ in range(10):  # profits small enough not to trip the daily breaker
        rm.record_trade_closed(profit=-1.0, balance=1_000_000.0, now=NOW)
    assert rm.paused
    assert rm.status.pause_reason.startswith("10 consecutive losses")
    _auto_resume_daily_breaker(rm)
    assert rm.paused  # anomaly stop — stays halted


def test_leaves_kill_switch_alone():
    rm = RiskManager(caps=_caps())
    rm.kill()
    _auto_resume_daily_breaker(rm)
    assert rm.paused


def test_noop_when_not_paused():
    rm = RiskManager(caps=_caps())
    _auto_resume_daily_breaker(rm)
    assert not rm.paused
