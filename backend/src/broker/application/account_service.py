"""Account connection use cases: connect, status, disconnect, auto-reconnect."""

from __future__ import annotations

import asyncio
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
                # store.save() hits the OS keyring synchronously — offload it so a
                # slow/unresponsive keyring backend can't stall the event loop.
                await asyncio.to_thread(self._store.save, credentials)
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
        # store.load() hits the OS keyring synchronously — offload it so a
        # slow/unresponsive keyring backend can't stall the event loop. This
        # runs on the trade loop's hot path (TradeEngine._current_balance,
        # called on every candle close), so a wedged keyring must not be able
        # to freeze trade entries for every symbol.
        has_saved_credentials = await asyncio.to_thread(self._store.load) is not None
        return {
            "gateway_up": health.gateway_up,
            "connected": health.terminal_connected,
            "account": health.account.__dict__ if health.account else None,
            "has_saved_credentials": has_saved_credentials,
        }

    async def reconnect_from_stored(self) -> bool:
        """Best-effort silent reconnect at startup. True if connected."""
        try:
            credentials = await asyncio.to_thread(self._store.load)
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
