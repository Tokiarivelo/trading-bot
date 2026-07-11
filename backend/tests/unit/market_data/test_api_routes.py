"""Broker symbol browsing endpoint (`GET /market-data/broker-symbols`) —
chart/watchlist only, never touches configs/app.yaml or the engine."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.routes import router
from src.market_data.application.history import CandleHistoryService

CANDLE_WIRE = {
    "time": 1_752_100_500,
    "open": 2400.0,
    "high": 2401.0,
    "low": 2399.0,
    "close": 2400.5,
    "tick_volume": 1000,
    "spread": 25,
}

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


def _candles_api(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    gateway_client = httpx.AsyncClient(transport=transport, base_url="http://gw")
    app = FastAPI()
    app.include_router(router)
    # Repository is never touched here — the fake gateway handler always
    # succeeds, so the DB fallback path in CandleHistoryService is unused.
    app.state.container = SimpleNamespace(
        candle_history=CandleHistoryService(GatewayMarketData(gateway_client), repository=None)
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend")


async def test_candles_omits_before_when_not_requested():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "before" not in request.url.params
        return httpx.Response(200, json=[CANDLE_WIRE])

    async with _candles_api(handler) as client:
        response = await client.get(
            "/market-data/candles", params={"symbol": "XAUUSD", "timeframe": "M5"}
        )
    assert response.status_code == 200
    assert response.json()[0]["time"] == 1_752_100_500


async def test_candles_forwards_before_as_epoch_seconds():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["before"] == "1752100000"
        return httpx.Response(200, json=[CANDLE_WIRE])

    async with _candles_api(handler) as client:
        response = await client.get(
            "/market-data/candles",
            params={"symbol": "XAUUSD", "timeframe": "M5", "before": 1_752_100_000},
        )
    assert response.status_code == 200


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
