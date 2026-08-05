import asyncio

from src.broker.application.reconciliation_poller import ReconciliationPoller


class FakeReconciliation:
    def __init__(self, error: Exception | None = None) -> None:
        self.reconcile_all_calls = 0
        self._error = error

    async def reconcile_all(self) -> None:
        self.reconcile_all_calls += 1
        if self._error is not None:
            raise self._error


async def test_poll_once_calls_reconcile_all():
    reconciliation = FakeReconciliation()
    poller = ReconciliationPoller(reconciliation=reconciliation)

    await poller.poll_once()

    assert reconciliation.reconcile_all_calls == 1


async def test_poll_once_swallows_unexpected_errors_so_the_loop_keeps_running():
    reconciliation = FakeReconciliation(error=RuntimeError("boom"))
    poller = ReconciliationPoller(reconciliation=reconciliation)

    await poller.poll_once()  # must not raise

    assert reconciliation.reconcile_all_calls == 1


async def test_start_runs_poll_once_repeatedly_until_stopped():
    reconciliation = FakeReconciliation()
    poller = ReconciliationPoller(reconciliation=reconciliation, poll_interval_s=0.01)

    poller.start()
    try:
        for _ in range(50):
            if reconciliation.reconcile_all_calls >= 3:
                break
            await asyncio.sleep(0.01)
        assert reconciliation.reconcile_all_calls >= 3
    finally:
        await poller.stop()


async def test_stop_before_start_is_a_no_op():
    reconciliation = FakeReconciliation()
    poller = ReconciliationPoller(reconciliation=reconciliation)

    await poller.stop()  # must not raise
