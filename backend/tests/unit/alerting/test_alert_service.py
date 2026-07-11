from src.alerting.adapters.composite import CompositeAlertAdapter
from src.alerting.application.alert_service import AlertService
from src.alerting.domain.models import AlertEventFlags, AlertingConfig, AlertMessage
from src.shared.events.definitions import (
    CircuitBreakerTripped,
    GatewayHealthChanged,
    PositionClosed,
    PositionOpened,
    RefinementCompleted,
)


class FakeAlertPort:
    def __init__(self) -> None:
        self.sent: list[AlertMessage] = []

    async def send(self, message: AlertMessage) -> None:
        self.sent.append(message)


class RaisingAlertPort:
    async def send(self, message: AlertMessage) -> None:
        raise RuntimeError("channel down")


def _config(**event_overrides) -> AlertingConfig:
    return AlertingConfig(events=AlertEventFlags(**event_overrides))


async def test_position_opened_sends_fill_alert_when_enabled():
    port = FakeAlertPort()
    service = AlertService(port=port, config=_config(fills=True))

    await service.on_position_opened(
        PositionOpened(
            symbol="XAUUSD",
            position_id="1",
            side="buy",
            volume=0.1,
            price=2400.0,
            sl=2395.0,
            tp=2410.0,
            spread_points=30,
        )
    )

    assert len(port.sent) == 1
    assert "XAUUSD" in port.sent[0].title


async def test_position_closed_skipped_when_fills_disabled():
    port = FakeAlertPort()
    service = AlertService(port=port, config=_config(fills=False))

    await service.on_position_closed(
        PositionClosed(symbol="XAUUSD", position_id="1", close_price=2400.0, profit=-5.0)
    )

    assert port.sent == []


async def test_circuit_breaker_tripped_sends_critical_alert():
    port = FakeAlertPort()
    service = AlertService(port=port, config=_config(circuit_breaker=True))

    await service.on_circuit_breaker_tripped(CircuitBreakerTripped(reason="5 consecutive losses"))

    assert len(port.sent) == 1
    assert port.sent[0].level.value == "critical"


async def test_refinement_completed_sends_alert_when_enabled():
    port = FakeAlertPort()
    service = AlertService(port=port, config=_config(refinements=True))

    await service.on_refinement_completed(
        RefinementCompleted(symbol="XAUUSD", verdict="refinement_proposed", proposal_id="p1")
    )

    assert len(port.sent) == 1
    assert "p1" in port.sent[0].body


async def test_gateway_health_changed_sends_alert_on_disconnect():
    port = FakeAlertPort()
    service = AlertService(port=port, config=_config(gateway_disconnect=True))

    await service.on_gateway_health_changed(
        GatewayHealthChanged(gateway_up=False, terminal_connected=False)
    )

    assert len(port.sent) == 1
    assert port.sent[0].level.value == "critical"


async def test_composite_adapter_isolates_one_failing_channel_from_another():
    good = FakeAlertPort()
    bad = RaisingAlertPort()
    composite = CompositeAlertAdapter([bad, good])

    await composite.send(AlertMessage(title="t", body="b"))

    assert len(good.sent) == 1
