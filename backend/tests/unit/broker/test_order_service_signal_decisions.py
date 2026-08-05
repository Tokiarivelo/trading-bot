"""Broker-side of the typed signal-decision trail (OBSERVABILITY_PLAN.md
Phase 1, extended in Phase 2): `open_position` stamps the engine-recorded
decision's terminal outcome — filled, spread-vetoed, RR-gated, or
broker-rejected — and records the spread/RR numbers it saw either way."""

import pytest

from src.activity.domain.models import DecisionCheck
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.trading import OrderRejected, Side
from src.market_data.domain.models import SymbolInfo
from src.shared.events.bus import EventBus
from tests.unit.broker.test_order_service import CONFIG, FakeBroker, FakeMarketData


class RejectingBroker(FakeBroker):
    async def open_position(self, order):
        raise OrderRejected("invalid stops (10016)")


class FakeSignalDecisionSink:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str, str | None]] = []
        self.checks: list[DecisionCheck] = []

    async def record(self, **kwargs) -> None:  # pragma: no cover - engine-side only
        raise AssertionError("the order service never records new decisions")

    async def record_outcome(self, signal_id, outcome, *, reason=None, checks=()) -> None:
        self.outcomes.append((signal_id, outcome, reason))
        self.checks.extend(checks)

    async def record_checks(self, signal_id, checks) -> None:
        self.checks.extend(checks)

    def check(self, name: str) -> DecisionCheck:
        return next(c for c in self.checks if c.name == name)


def make_service(broker=None, market_data=None):
    sink = FakeSignalDecisionSink()
    service = OrderService(
        broker=broker or FakeBroker(),
        market_data=market_data or FakeMarketData(),
        spread_gate=SpreadGate({"XAUUSD": CONFIG}),
        event_bus=EventBus(),
        signal_decisions=sink,
    )
    return service, sink


async def test_a_fill_stamps_opened_without_rewriting_the_reason():
    service, sink = make_service()

    await service.open_position(
        "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, reason="demand retest", signal_id="sig-1"
    )

    assert sink.outcomes == [("sig-1", "opened", None)]
    # A fill records what it cleared the gates by, not just that it cleared.
    spread = sink.check("spread_points")
    assert (spread.value, spread.threshold, spread.comparison, spread.passed) == (
        25.0,
        float(CONFIG.max_spread_points),
        "<=",
        True,
    )
    assert sink.check("risk_reward").passed is True


async def test_a_spread_veto_stamps_spread_veto_with_the_gate_reason_appended():
    wide = SymbolInfo(
        symbol="XAUUSD",
        bid=2400.10,
        ask=2401.35,
        spread_points=125,
        point=0.01,
        digits=2,
        stops_level=10,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    service, sink = make_service(market_data=FakeMarketData(wide))

    with pytest.raises(OrderRejected):
        await service.open_position(
            "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, reason="demand retest", signal_id="sig-1"
        )

    signal_id, outcome, reason = sink.outcomes[0]
    assert (signal_id, outcome) == ("sig-1", "spread_veto")
    assert reason.startswith("demand retest — ")
    spread = sink.check("spread_points")
    assert (spread.value, spread.threshold, spread.passed) == (
        125.0,
        float(CONFIG.max_spread_points),
        False,
    )


async def test_a_broker_rejection_stamps_broker_rejected_with_the_retcode_text():
    service, sink = make_service(broker=RejectingBroker())

    with pytest.raises(OrderRejected):
        await service.open_position(
            "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, reason="demand retest", signal_id="sig-1"
        )

    signal_id, outcome, reason = sink.outcomes[0]
    assert (signal_id, outcome) == ("sig-1", "broker_rejected")
    assert "invalid stops (10016)" in reason


async def test_a_manual_order_with_no_signal_id_stamps_nothing():
    service, sink = make_service()

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert sink.outcomes == []


async def test_a_risk_reward_failure_is_its_own_outcome_not_spread_veto():
    """The RR floor and the spread cap were one collapsed `spread_veto`
    bucket before Phase 2; a TP too close for the configured min_rr is now
    reported as `rr_gate` with the distances it compared."""
    service, sink = make_service()

    with pytest.raises(OrderRejected):
        await service.open_position(
            "XAUUSD",
            Side.BUY,
            0.1,
            sl=2390.0,
            tp=2401.40,  # ~0.05 above the ask vs a ~11.35 SL distance
            reason="demand retest",
            signal_id="sig-1",
        )

    signal_id, outcome, reason = sink.outcomes[0]
    assert (signal_id, outcome) == ("sig-1", "rr_gate")
    assert reason.startswith("demand retest — tp distance ")
    rr = sink.check("risk_reward")
    assert rr.passed is False
    assert rr.value < rr.threshold
