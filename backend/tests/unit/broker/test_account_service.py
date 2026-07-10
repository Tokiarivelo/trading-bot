import pytest

from src.broker.application.account_service import AccountService
from src.broker.domain.account import (
    AccountInfo,
    BrokerUnavailable,
    GatewayHealth,
    LoginRejected,
    Mt5Credentials,
)

CREDS = Mt5Credentials(login=123456, password="pw", server="Demo-Server")
ACCOUNT = AccountInfo(
    login=123456,
    server="Demo-Server",
    name="Test User",
    currency="USD",
    balance=10_000.0,
    equity=10_050.0,
    leverage=100,
)


class FakeGateway:
    def __init__(self):
        self.reject = False
        self.down = False
        self.logged_in = False

    async def login(self, credentials):
        if self.down:
            raise BrokerUnavailable("gateway unreachable")
        if self.reject:
            raise LoginRejected("Authorization failed")
        self.logged_in = True
        return ACCOUNT

    async def logout(self):
        self.logged_in = False

    async def health(self):
        if self.down:
            return GatewayHealth(gateway_up=False, terminal_connected=False)
        return GatewayHealth(
            gateway_up=True,
            terminal_connected=self.logged_in,
            account=ACCOUNT if self.logged_in else None,
        )


class FakeStore:
    def __init__(self):
        self.saved = None
        self.fail_on_save = False

    def save(self, credentials):
        if self.fail_on_save:
            raise RuntimeError("no keyring backend")
        self.saved = credentials

    def load(self):
        return self.saved

    def clear(self):
        self.saved = None


@pytest.fixture
def service():
    gateway, store = FakeGateway(), FakeStore()
    return AccountService(gateway, store), gateway, store


async def test_connect_logs_in_and_persists(service):
    svc, gateway, store = service
    info = await svc.connect(CREDS)
    assert info == ACCOUNT
    assert store.saved == CREDS
    assert (await svc.status())["connected"] is True


async def test_connect_without_remember_does_not_persist(service):
    svc, _, store = service
    await svc.connect(CREDS, remember=False)
    assert store.saved is None


async def test_store_failure_does_not_break_connection(service):
    svc, gateway, store = service
    store.fail_on_save = True
    info = await svc.connect(CREDS)
    assert info == ACCOUNT
    assert gateway.logged_in is True


async def test_rejected_login_propagates_and_persists_nothing(service):
    svc, gateway, store = service
    gateway.reject = True
    with pytest.raises(LoginRejected):
        await svc.connect(CREDS)
    assert store.saved is None


async def test_disconnect_keeps_credentials_unless_forget(service):
    svc, gateway, store = service
    await svc.connect(CREDS)
    await svc.disconnect()
    assert store.saved == CREDS
    await svc.disconnect(forget=True)
    assert store.saved is None


async def test_status_when_gateway_down(service):
    svc, gateway, _ = service
    gateway.down = True
    status = await svc.status()
    assert status == {
        "gateway_up": False,
        "connected": False,
        "account": None,
        "has_saved_credentials": False,
    }


async def test_reconnect_from_stored(service):
    svc, gateway, store = service
    assert await svc.reconnect_from_stored() is False  # nothing stored
    store.saved = CREDS
    assert await svc.reconnect_from_stored() is True
    assert gateway.logged_in is True


async def test_reconnect_tolerates_gateway_down(service):
    svc, gateway, store = service
    store.saved = CREDS
    gateway.down = True
    assert await svc.reconnect_from_stored() is False
