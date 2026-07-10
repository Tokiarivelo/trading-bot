"""GatewayMarketData against the exact wire shapes of gateway/schemas.py."""

from datetime import UTC, datetime

import httpx
import pytest

from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.domain.models import MarketDataUnavailable, Timeframe

CANDLE_WIRE = {
    "time": 1_752_100_500,
    "open": 2400.0,
    "high": 2401.0,
    "low": 2399.0,
    "close": 2400.5,
    "tick_volume": 1000,
    "spread": 25,
}


def adapter_with(handler) -> GatewayMarketData:
    transport = httpx.MockTransport(handler)
    return GatewayMarketData(httpx.AsyncClient(transport=transport, base_url="http://gw"))


async def test_get_candles_parses_wire_format():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/candles"
        assert request.url.params["timeframe"] == "M5"
        return httpx.Response(200, json=[CANDLE_WIRE])

    candles = await adapter_with(handler).get_candles("XAUUSD", Timeframe.M5, 10)
    (candle,) = candles
    assert candle.symbol == "XAUUSD"
    assert candle.time == datetime.fromtimestamp(1_752_100_500, tz=UTC)
    assert candle.time.tzinfo is UTC
    assert candle.spread_points == 25


async def test_gateway_error_becomes_market_data_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "not logged in — POST /login first"})

    with pytest.raises(MarketDataUnavailable, match="not logged in"):
        await adapter_with(handler).get_candles("XAUUSD", Timeframe.M5, 10)


async def test_connection_failure_becomes_market_data_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(MarketDataUnavailable, match="unreachable"):
        await adapter_with(handler).get_tick("XAUUSD")


async def test_symbol_info_maps_all_fields():
    payload = {
        "symbol": "XAUUSD",
        "bid": 2400.10,
        "ask": 2400.35,
        "spread_points": 25,
        "point": 0.01,
        "digits": 2,
        "stops_level": 10,
        "contract_size": 100.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
    }
    info = await adapter_with(lambda r: httpx.Response(200, json=payload)).get_symbol_info("XAUUSD")
    assert info.spread_points == 25
    assert info.stops_level == 10
