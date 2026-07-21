"""AccountGatewayPort and BrokerPort adapters over the MT5 gateway HTTP API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from src.broker.domain.account import (
    AccountInfo,
    BrokerUnavailable,
    GatewayHealth,
    LoginRejected,
    Mt5Credentials,
)
from src.broker.domain.trading import (
    ClosedPositionInfo,
    ExecutionResult,
    OrderRejected,
    OrderRequest,
    OrderType,
    PendingOrder,
    PendingOrderRequest,
    Position,
    Side,
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


class GatewayBroker:
    """BrokerPort adapter for live/demo trading over the gateway HTTP API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def open_position(self, order: OrderRequest) -> ExecutionResult:
        payload = await self._post(
            "/order",
            {
                "symbol": order.symbol,
                "side": order.side.value,
                "volume": order.volume,
                "sl": order.sl,
                "tp": order.tp,
                "comment": order.comment,
                "magic": order.magic,
            },
        )
        return _to_execution_result(payload)

    async def close_position(self, ticket: int, volume: float | None = None) -> ExecutionResult:
        payload = await self._post(f"/positions/{ticket}/close", {"volume": volume})
        return _to_execution_result(payload)

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> None:
        await self._post(f"/positions/{ticket}/modify", {"sl": sl, "tp": tp})

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        params = {"symbol": symbol} if symbol else {}
        try:
            response = await self._client.get("/positions", params=params)
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code != 200:
            raise BrokerUnavailable(
                f"gateway /positions -> {response.status_code}: {response.text}"
            )
        return [
            Position(
                ticket=p["ticket"],
                symbol=p["symbol"],
                side=Side(p["side"]),
                volume=p["volume"],
                open_price=p["open_price"],
                sl=p["sl"],
                tp=p["tp"],
                open_time=datetime.fromtimestamp(p["open_time"], tz=UTC),
                profit=p["profit"],
                comment=p["comment"],
                magic=p.get("magic", 0),
            )
            for p in response.json()
        ]

    async def get_close_info(self, ticket: int) -> ClosedPositionInfo | None:
        try:
            response = await self._client.get(f"/positions/{ticket}/history")
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise BrokerUnavailable(
                f"gateway /positions/{ticket}/history -> {response.status_code}: {response.text}"
            )
        payload = response.json()
        return ClosedPositionInfo(
            symbol=payload["symbol"],
            price=payload["close_price"],
            time=datetime.fromtimestamp(payload["close_time"], tz=UTC),
            profit=payload["profit"],
        )

    async def place_pending_order(self, order: PendingOrderRequest) -> PendingOrder:
        payload = await self._post(
            "/orders/pending",
            {
                "symbol": order.symbol,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "volume": order.volume,
                "price": order.price,
                "sl": order.sl,
                "tp": order.tp,
                "comment": order.comment,
            },
        )
        return _to_pending_order(payload)

    async def cancel_pending_order(self, ticket: int) -> None:
        try:
            response = await self._client.delete(f"/orders/pending/{ticket}")
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code == 502:
            raise OrderRejected(response.json().get("detail", "cancel rejected"))
        if response.status_code != 200:
            raise BrokerUnavailable(
                f"gateway /orders/pending/{ticket} -> {response.status_code}: {response.text}"
            )

    async def modify_pending_order(
        self, ticket: int, price: float | None, sl: float | None, tp: float | None
    ) -> None:
        await self._post(f"/orders/pending/{ticket}/modify", {"price": price, "sl": sl, "tp": tp})

    async def get_pending_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        params = {"symbol": symbol} if symbol else {}
        try:
            response = await self._client.get("/orders/pending", params=params)
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code != 200:
            raise BrokerUnavailable(
                f"gateway /orders/pending -> {response.status_code}: {response.text}"
            )
        return [_to_pending_order(o) for o in response.json()]

    @property
    def simulates_pending_fills(self) -> bool:
        return False

    async def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=json)
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"gateway unreachable: {exc}") from exc
        if response.status_code == 502:
            raise OrderRejected(response.json().get("detail", "order rejected"))
        if response.status_code != 200:
            raise BrokerUnavailable(f"gateway {path} -> {response.status_code}: {response.text}")
        return response.json()


def _to_execution_result(payload: dict[str, Any]) -> ExecutionResult:
    return ExecutionResult(
        ticket=payload["ticket"],
        symbol=payload["symbol"],
        side=Side(payload["side"]),
        volume=payload["volume"],
        price=payload["price"],
        sl=payload["sl"],
        tp=payload["tp"],
        time=datetime.fromtimestamp(payload["time"], tz=UTC),
        spread_points=payload["spread_points"],
        comment=payload["comment"],
        magic=payload.get("magic", 0),
        profit=payload["profit"],
    )


def _to_pending_order(payload: dict[str, Any]) -> PendingOrder:
    return PendingOrder(
        ticket=payload["ticket"],
        symbol=payload["symbol"],
        side=Side(payload["side"]),
        order_type=OrderType(payload["order_type"]),
        volume=payload["volume"],
        price=payload["price"],
        sl=payload["sl"],
        tp=payload["tp"],
        placed_time=datetime.fromtimestamp(payload["placed_time"], tz=UTC),
        comment=payload["comment"],
    )
