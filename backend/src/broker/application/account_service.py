"""Account connection use cases: connect, status, disconnect, auto-reconnect."""

from __future__ import annotations

import logging
from typing import Any

from src.broker.domain.account import (
    AccountInfo,
    BrokerUnavailable,
    LoginRejected,
    Mt5Credentials,
)
from src.broker.ports.account import AccountGatewayPort, CredentialStorePort

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, gateway: AccountGatewayPort, store: CredentialStorePort) -> None:
        self._gateway = gateway
        self._store = store

    async def connect(self, credentials: Mt5Credentials, remember: bool = True) -> AccountInfo:
        logger.info("connecting to MT5: login=%s server=%s", credentials.login, credentials.server)
        info = await self._gateway.login(credentials)
        logger.info("connected: account=%s balance=%s %s", info.login, info.balance, info.currency)
        if remember:
            try:
                self._store.save(credentials)
            except Exception:
                # Persisting is convenience, not correctness — stay connected.
                logger.exception("could not persist credentials (keyring unavailable?)")
        return info

    async def disconnect(self, forget: bool = False) -> None:
        await self._gateway.logout()
        if forget:
            self._store.clear()
        logger.info("disconnected from MT5%s", " and forgot credentials" if forget else "")

    async def status(self) -> dict[str, Any]:
        health = await self._gateway.health()
        return {
            "gateway_up": health.gateway_up,
            "connected": health.terminal_connected,
            "account": health.account.__dict__ if health.account else None,
            "has_saved_credentials": self._store.load() is not None,
        }

    async def reconnect_from_stored(self) -> bool:
        """Best-effort silent reconnect at startup. True if connected."""
        try:
            credentials = self._store.load()
        except Exception:
            logger.exception("could not read stored credentials")
            return False
        if credentials is None:
            return False
        try:
            await self.connect(credentials, remember=False)
            return True
        except (BrokerUnavailable, LoginRejected) as exc:
            logger.warning("auto-reconnect skipped: %s", exc)
            return False
