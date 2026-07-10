"""AccountGatewayPort adapter over the MT5 gateway HTTP API."""

from __future__ import annotations

import httpx

from src.broker.domain.account import (
    AccountInfo,
    BrokerUnavailable,
    GatewayHealth,
    LoginRejected,
    Mt5Credentials,
)


class GatewayAccount:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def login(self, credentials: Mt5Credentials) -> AccountInfo:
        try:
            response = await self._client.post(
                "/login",
                json={
                    "login": credentials.login,
                    "password": credentials.password,
                    "server": credentials.server,
                },
            )
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code == 502:
            raise LoginRejected(response.json().get("detail", "login rejected"))
        if response.status_code != 200:
            raise BrokerUnavailable(f"gateway /login -> {response.status_code}: {response.text}")
        return AccountInfo(**response.json())

    async def logout(self) -> None:
        try:
            await self._client.post("/logout")
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc

    async def health(self) -> GatewayHealth:
        try:
            response = await self._client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError:
            return GatewayHealth(gateway_up=False, terminal_connected=False)
        body = response.json()
        account = body.get("account")
        return GatewayHealth(
            gateway_up=True,
            terminal_connected=body["terminal_connected"],
            account=AccountInfo(**account) if account else None,
        )
