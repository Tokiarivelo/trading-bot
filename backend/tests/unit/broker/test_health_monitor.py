from src.broker.application.health_monitor import GatewayHealthMonitor
from src.shared.events.bus import EventBus
from src.shared.events.definitions import GatewayHealthChanged


class FakeAccount:
    def __init__(self, statuses: list[dict]) -> None:
        self._statuses = iter(statuses)
        self.reconnect_calls = 0

    async def status(self) -> dict:
        return next(self._statuses)

    async def reconnect_from_stored(self) -> bool:
        self.reconnect_calls += 1
        return True


class FakeReconciliation:
    def __init__(self) -> None:
        self.reconcile_all_calls = 0

    async def reconcile_all(self) -> None:
        self.reconcile_all_calls += 1


def _collector():
    published: list[GatewayHealthChanged] = []

    async def handler(event: GatewayHealthChanged) -> None:
        published.append(event)

    return published, handler


async def test_first_check_only_establishes_baseline_no_event_no_action():
    account = FakeAccount([{"gateway_up": True, "connected": True}])
    reconciliation = FakeReconciliation()
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(GatewayHealthChanged, handler)
    monitor = GatewayHealthMonitor(
        account=account, reconciliation=reconciliation, event_bus=event_bus
    )

    await monitor._check_once()

    assert published == []
    assert reconciliation.reconcile_all_calls == 0
    assert account.reconnect_calls == 0


async def test_down_to_up_transition_reconnects_and_reconciles_once():
    account = FakeAccount(
        [
            {"gateway_up": False, "connected": False},
            {"gateway_up": True, "connected": True},
        ]
    )
    reconciliation = FakeReconciliation()
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(GatewayHealthChanged, handler)
    monitor = GatewayHealthMonitor(
        account=account, reconciliation=reconciliation, event_bus=event_bus
    )

    await monitor._check_once()  # baseline: down
    await monitor._check_once()  # transition: down -> up

    assert len(published) == 1
    assert published[0].gateway_up is True
    assert account.reconnect_calls == 1
    assert reconciliation.reconcile_all_calls == 1


async def test_repeated_up_polls_do_not_repeat_reconnect_or_reconcile():
    account = FakeAccount(
        [
            {"gateway_up": True, "connected": True},
            {"gateway_up": True, "connected": True},
            {"gateway_up": True, "connected": True},
        ]
    )
    reconciliation = FakeReconciliation()
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(GatewayHealthChanged, handler)
    monitor = GatewayHealthMonitor(
        account=account, reconciliation=reconciliation, event_bus=event_bus
    )

    await monitor._check_once()
    await monitor._check_once()
    await monitor._check_once()

    assert published == []
    assert account.reconnect_calls == 0
    assert reconciliation.reconcile_all_calls == 0


async def test_up_to_down_transition_publishes_event_but_does_not_reconnect():
    account = FakeAccount(
        [
            {"gateway_up": True, "connected": True},
            {"gateway_up": False, "connected": False},
        ]
    )
    reconciliation = FakeReconciliation()
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(GatewayHealthChanged, handler)
    monitor = GatewayHealthMonitor(
        account=account, reconciliation=reconciliation, event_bus=event_bus
    )

    await monitor._check_once()
    await monitor._check_once()

    assert len(published) == 1
    assert published[0].gateway_up is False
    assert account.reconnect_calls == 0
    assert reconciliation.reconcile_all_calls == 0
