"""Ports for account connection and credential persistence."""

from __future__ import annotations

from typing import Protocol

from src.broker.domain.account import AccountInfo, GatewayHealth, Mt5Credentials


class AccountGatewayPort(Protocol):
    async def login(self, credentials: Mt5Credentials) -> AccountInfo: ...

    async def logout(self) -> None: ...

    async def health(self) -> GatewayHealth: ...


class CredentialStorePort(Protocol):
    def save(self, credentials: Mt5Credentials) -> None: ...

    def load(self) -> Mt5Credentials | None: ...

    def clear(self) -> None: ...
