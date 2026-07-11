"""Broker symbol browsing endpoint (`GET /market-data/broker-symbols`) —
chart/watchlist only, never touches configs/app.yaml or the engine."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.routes import router

SYMBOLS_WIRE = [
    {"name": "XAUUSD", "description": "Gold vs US Dollar", "path": "Metals", "visible": True},
    {
        "name": "EURUSD",
        "description": "Euro vs US Dollar",
        "path": "Forex\\Majors",
        "visible": False,
    },
]


def _api(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    gateway_client = httpx.AsyncClient(transport=transport, base_url="http://gw")
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(market_data=GatewayMarketData(gateway_client))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend")


async def test_broker_symbols_lists_catalog():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/symbols"
        return httpx.Response(200, json={"items": SYMBOLS_WIRE, "total": len(SYMBOLS_WIRE)})

    async with _api(handler) as client:
        response = await client.get("/market-data/broker-symbols")
    assert response.status_code == 200
    body = response.json()
    assert {s["name"] for s in body["items"]} == {"XAUUSD", "EURUSD"}
    assert body["total"] == 2


async def test_broker_symbols_forwards_search_limit_and_offset():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search"] == "gold"
        assert request.url.params["limit"] == "10"
        assert request.url.params["offset"] == "5"
        return httpx.Response(200, json={"items": SYMBOLS_WIRE[:1], "total": 1})

    async with _api(handler) as client:
        response = await client.get(
            "/market-data/broker-symbols", params={"search": "gold", "limit": 10, "offset": 5}
        )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_broker_symbols_maps_gateway_unavailable_to_503():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with _api(handler) as client:
        response = await client.get("/market-data/broker-symbols")
    assert response.status_code == 503
