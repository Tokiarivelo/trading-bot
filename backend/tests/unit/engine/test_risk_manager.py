from datetime import UTC, datetime

from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps

CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=2,
    max_trades_per_day=8,
    consecutive_loss_pause=3,
)


def make_manager(caps: RiskCaps = CAPS) -> RiskManager:
    return RiskManager(caps=caps, timezone="UTC")


def test_size_position_computes_lots_from_risk_pct():
    manager = make_manager()
    decision = manager.size_position(
        balance=10_000.0,
        sl_distance_price=5.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    assert decision.approved
    assert decision.volume == 0.1  # (10000*0.005) / (5*100)


def test_size_position_clamps_to_broker_minimum():
    manager = make_manager()
    decision = manager.size_position(
        balance=10.0,  # tiny risk budget -> below volume_min
        sl_distance_price=50.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    assert not decision.approved
    assert "minimum" in decision.reason


def test_size_position_rejects_non_positive_sl_distance():
    manager = make_manager()
    decision = manager.size_position(
        balance=10_000.0,
        sl_distance_price=0.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    assert not decision.approved


def test_check_pretrade_blocks_at_max_open_positions():
    manager = make_manager()
    decision = manager.check_pretrade(open_positions_count=2)
    assert not decision.approved
    assert "max open positions" in decision.reason


def test_check_pretrade_blocks_at_max_trades_per_day():
    manager = make_manager()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    for _ in range(8):
        manager.record_trade_opened(now)
    decision = manager.check_pretrade(open_positions_count=0, now=now)
    assert not decision.approved
    assert "max trades per day" in decision.reason


def test_consecutive_losses_trip_circuit_breaker():
    manager = make_manager()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    for _ in range(2):
        manager.record_trade_closed(-10.0, now=now)
    assert not manager.paused
    manager.record_trade_closed(-10.0, now=now)
    assert manager.paused
    assert "consecutive losses" in manager.status.pause_reason


def test_a_win_resets_consecutive_loss_counter():
    manager = make_manager()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    manager.record_trade_closed(-10.0, now=now)
    manager.record_trade_closed(-10.0, now=now)
    manager.record_trade_closed(50.0, now=now)
    assert manager.status.consecutive_losses == 0
    manager.record_trade_closed(-10.0, now=now)
    manager.record_trade_closed(-10.0, now=now)
    assert not manager.paused  # only 2 in a row since the win


def test_daily_loss_limit_trips_circuit_breaker():
    manager = make_manager()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    manager.record_trade_closed(-250.0, balance=10_000.0, now=now)  # 2.5% > 2% cap
    assert manager.paused
    assert "daily loss" in manager.status.pause_reason


def test_pretrade_blocked_while_paused():
    manager = make_manager()
    manager.kill("test pause")
    decision = manager.check_pretrade(open_positions_count=0)
    assert not decision.approved
    assert "engine paused" in decision.reason


def test_resume_clears_pause_and_consecutive_losses():
    manager = make_manager()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    for _ in range(3):
        manager.record_trade_closed(-10.0, now=now)
    assert manager.paused
    manager.resume()
    assert not manager.paused
    assert manager.status.consecutive_losses == 0


def test_daily_counters_reset_on_new_day():
    manager = make_manager()
    day_one = datetime(2026, 7, 11, 23, 55, tzinfo=UTC)
    day_two = datetime(2026, 7, 12, 0, 5, tzinfo=UTC)
    manager.record_trade_opened(day_one)
    assert manager.status.trades_today == 1
    manager.record_trade_opened(day_two)
    assert manager.status.trades_today == 1  # reset, then incremented once
