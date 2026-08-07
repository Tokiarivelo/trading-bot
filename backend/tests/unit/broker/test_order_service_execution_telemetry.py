"""Execution telemetry on the order path (OBSERVABILITY_PLAN.md Phase 3):
requested price, signed slippage, signal→ack latency, and the broker's return
code on both a fill and a rejection.

The slippage sign convention is the load-bearing part: a POSITIVE number must
always mean the fill cost the trader, for longs and shorts alike, or averaging
it across a mixed fleet is meaningless.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.trading import ExecutionResult, OrderRejected, Side, execution_slippage
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionOpened
from tests.unit.broker.test_order_service import CONFIG, XAUUSD_INFO, FakeMarketData

# FakeMarketData serves XAUUSD_INFO: bid 2400.10 / ask 2400.35. A buy's
# requested price is therefore the ask, a sell's the bid.
REQUESTED_BUY = XAUUSD_INFO.ask
REQUESTED_SELL = XAUUSD_INFO.bid


class FillingBroker:
    """Broker stub that fills at an exact price with an exact return code."""

    def __init__(self, fill_price: float, retcode: int | None = 10009) -> None:
        self._fill_price = fill_price
        self._retcode = retcode

    async def open_position(self, order):
        return ExecutionResult(
            ticket=1,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            price=self._fill_price,
            sl=order.sl,
            tp=order.tp,
            time=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
            spread_points=25,
            comment=order.comment,
            magic=order.magic,
            retcode=self._retcode,
        )


class RejectingBroker:
    def __init__(self, retcode: int | None) -> None:
        self._retcode = retcode

    async def open_position(self, order):
        raise OrderRejected("invalid stops — sl/tp too close to price", retcode=self._retcode)


class RecordingSink:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str]] = []
        self.checks: list = []

    async def record(self, **kwargs) -> None:  # pragma: no cover - engine-side only
        raise AssertionError("the order service never records new decisions")

    async def record_outcome(self, signal_id, outcome, *, reason=None, checks=()) -> None:
        self.outcomes.append((signal_id, outcome))
        self.checks.extend(checks)

    async def record_checks(self, signal_id, checks) -> None:
        self.checks.extend(checks)


def make_service(broker, *, now: datetime | None = None):
    bus = EventBus()
    events: list[PositionOpened] = []

    async def collect(event: PositionOpened) -> None:
        events.append(event)

    bus.subscribe(PositionOpened, collect)
    sink = RecordingSink()
    service = OrderService(
        broker=broker,
        market_data=FakeMarketData(),
        spread_gate=SpreadGate({"XAUUSD": CONFIG}),
        event_bus=bus,
        signal_decisions=sink,
        clock=(lambda: now) if now is not None else (lambda: datetime.now(UTC)),
    )
    return service, events, sink


# ── the pure sign convention ──────────────────────────────────────────────


def test_buying_above_the_asked_price_is_positive_slippage():
    assert execution_slippage(Side.BUY, 2400.35, 2400.55) == pytest.approx(0.20)


def test_buying_below_the_asked_price_is_negative_slippage():
    assert execution_slippage(Side.BUY, 2400.35, 2400.25) == pytest.approx(-0.10)


def test_selling_below_the_asked_price_is_positive_slippage():
    """A short filled at 2399.90 when it asked for 2400.10 received LESS —
    the same direction of harm a buy suffers when it pays more."""
    assert execution_slippage(Side.SELL, 2400.10, 2399.90) == pytest.approx(0.20)


def test_selling_above_the_asked_price_is_negative_slippage():
    assert execution_slippage(Side.SELL, 2400.10, 2400.30) == pytest.approx(-0.20)


# ── as measured on a real fill ────────────────────────────────────────────


async def test_a_buy_filled_worse_than_asked_reports_positive_slippage():
    service, events, _ = make_service(FillingBroker(fill_price=2400.55))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert events[0].requested_price == pytest.approx(REQUESTED_BUY)
    assert events[0].slippage == pytest.approx(0.20)


async def test_a_sell_filled_worse_than_asked_reports_positive_slippage():
    service, events, _ = make_service(FillingBroker(fill_price=2399.90))

    await service.open_position("XAUUSD", Side.SELL, 0.1, sl=2410.0, tp=2380.0)

    assert events[0].requested_price == pytest.approx(REQUESTED_SELL)
    assert events[0].slippage == pytest.approx(0.20)


async def test_a_fill_at_exactly_the_asked_price_has_zero_slippage():
    service, events, _ = make_service(FillingBroker(fill_price=REQUESTED_BUY))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert events[0].slippage == pytest.approx(0.0)


# ── latency ───────────────────────────────────────────────────────────────


async def test_latency_spans_signal_emit_to_broker_ack():
    ack = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    service, events, _ = make_service(FillingBroker(fill_price=2400.35), now=ack)

    await service.open_position(
        "XAUUSD",
        Side.BUY,
        0.1,
        sl=2390.0,
        tp=2420.0,
        signal_id="sig-1",
        signal_emitted_at=ack - timedelta(milliseconds=250),
    )

    assert events[0].execution_latency_ms == pytest.approx(250.0)


async def test_an_order_with_no_signal_behind_it_reports_no_latency():
    """Manual/API orders have no emit instant to measure from — None, not 0,
    so they never drag a bot's average latency down."""
    service, events, _ = make_service(FillingBroker(fill_price=2400.35))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert events[0].execution_latency_ms is None


# ── broker return code, on both outcomes ──────────────────────────────────


async def test_a_fill_carries_the_brokers_return_code():
    service, events, _ = make_service(FillingBroker(fill_price=2400.35, retcode=10009))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert events[0].broker_retcode == 10009


async def test_a_paper_fill_with_no_return_code_reports_none():
    service, events, _ = make_service(FillingBroker(fill_price=2400.35, retcode=None))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    assert events[0].broker_retcode is None


async def test_a_broker_rejection_records_its_return_code_on_the_decision_trail():
    """A rejected order produces no trade to journal, so 10016 has to land on
    the signal's decision instead — this is the code that silently killed a
    whole VIX75 fleet."""
    service, _events, sink = make_service(RejectingBroker(retcode=10016))

    with pytest.raises(OrderRejected):
        await service.open_position(
            "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, signal_id="sig-1"
        )

    assert ("sig-1", "broker_rejected") in sink.outcomes
    retcode_check = next(c for c in sink.checks if c.name == "broker_retcode")
    assert retcode_check.value == 10016
    assert retcode_check.passed is False


async def test_a_rejection_with_no_return_code_records_no_retcode_check():
    """The spread/RR gate and the paper broker refuse without a broker code —
    recording a fabricated one would poison the retcode histogram."""
    service, _events, sink = make_service(RejectingBroker(retcode=None))

    with pytest.raises(OrderRejected):
        await service.open_position(
            "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, signal_id="sig-1"
        )

    assert ("sig-1", "broker_rejected") in sink.outcomes
    assert not [c for c in sink.checks if c.name == "broker_retcode"]


# ── transaction cost + regime tagging (OBSERVABILITY_PLAN.md Phase 6) ───────


async def test_transaction_cost_combines_spread_and_slippage_in_account_currency():
    service, events, _ = make_service(FillingBroker(fill_price=2400.55))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    # spread_points=25 * point=0.01 = 0.25 spread cost in price units; the
    # fill at 2400.55 vs requested 2400.35 is +0.20 slippage (see
    # `test_a_buy_filled_worse_than_asked_reports_positive_slippage`).
    # (0.25 + 0.20) * volume(0.1) * contract_size(100.0) = 4.5.
    assert events[0].transaction_cost == pytest.approx(4.5)


async def test_transaction_cost_with_favorable_slippage_can_be_lower_than_pure_spread():
    """Negative slippage (a better-than-asked fill) offsets the spread cost —
    the formula isn't a floor at "spread alone"."""
    service, events, _ = make_service(FillingBroker(fill_price=2400.25))  # -0.10 slippage

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    # (0.25 + (-0.10)) * 0.1 * 100 = 1.5
    assert events[0].transaction_cost == pytest.approx(1.5)


async def test_regime_kwargs_pass_through_to_position_opened():
    service, events, _ = make_service(FillingBroker(fill_price=2400.35))

    await service.open_position(
        "XAUUSD",
        Side.BUY,
        0.1,
        sl=2390.0,
        tp=2420.0,
        regime_volatility="high",
        regime_volatility_percentile=82.5,
        regime_trend="trending",
        regime_adx=27.3,
        regime_session="london",
    )

    event = events[0]
    assert event.regime_volatility == "high"
    assert event.regime_volatility_percentile == pytest.approx(82.5)
    assert event.regime_trend == "trending"
    assert event.regime_adx == pytest.approx(27.3)
    assert event.regime_session == "london"


async def test_regime_kwargs_default_to_none():
    service, events, _ = make_service(FillingBroker(fill_price=2400.35))

    await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)

    event = events[0]
    assert event.regime_volatility is None
    assert event.regime_volatility_percentile is None
    assert event.regime_trend is None
    assert event.regime_adx is None
    assert event.regime_session is None
