"""Phase 1 end-to-end (no real MT5): frontend-facing API → services → adapters
→ fake gateway speaking the exact gateway wire protocol.

Covers the F11 login flow, candle serving with DB fallback, and backfill.
"""

from __future__ import annotations

import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.broker.adapters.credential_store import FernetCredentialStore
from src.broker.adapters.mt5_gateway import GatewayAccount
from src.broker.api.routes import router as account_router
from src.broker.application.account_service import AccountService
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.routes import router as market_data_router
from src.market_data.api.ws import WsBroadcaster
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.application.history import CandleHistoryService
from src.market_data.domain.models import Timeframe
from src.shared.db.base import Base
from src.shared.events.bus import EventBus

M5 = 300


def make_fake_gateway() -> FastAPI:
    """Mimics gateway/src/gateway/main.py shapes (see its contract tests)."""
    gw = FastAPI()
    state = {"connected": False}
    account = {
        "login": 123456,
        "server": "Demo-Server",
        "name": "Test User",
        "currency": "USD",
        "balance": 10_000.0,
        "equity": 10_050.0,
        "leverage": 100,
    }

    @gw.post("/login")
    def login(body: dict):
        if body["password"] != "good-pw":
            raise HTTPException(status_code=502, detail="login rejected: Authorization failed")
        state["connected"] = True
        return account

    @gw.post("/logout")
    def logout():
        state["connected"] = False
        return {"status": "ok"}

    @gw.get("/health")
    def health():
        return {
            "status": "ok",
            "terminal_connected": state["connected"],
            "account": account if state["connected"] else None,
        }

    @gw.get("/candles")
    def candles(symbol: str, timeframe: str, count: int = 300):
        if not state["connected"]:
            raise HTTPException(status_code=502, detail="not logged in — POST /login first")
        latest_open = int(time.time()) // M5 * M5
        n = min(count, 5)
        return [
            {
                "time": latest_open - (n - 1 - i) * M5,
                "open": 2400.0 + i,
                "high": 2401.0 + i,
                "low": 2399.0 + i,
                "close": 2400.5 + i,
                "tick_volume": 1000,
                "spread": 25,
            }
            for i in range(n)
        ]

    @gw.get("/symbol_info")
    def symbol_info(symbol: str):
        if not state["connected"]:
            raise HTTPException(status_code=502, detail="not logged in — POST /login first")
        return {
            "symbol": symbol,
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

    return gw


class ContainerForTest:
    """Hand-wired composition mirroring src.container.build_container, with the
    gateway HTTP client routed into the in-process fake gateway."""

    def __init__(self, tmp_path):
        gateway_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_fake_gateway()), base_url="http://gw"
        )
        engine = create_engine(f"sqlite:///{tmp_path}/test.db")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        self.settings = None
        self.event_bus = EventBus()
        self.symbols = ["XAUUSD"]
        self.gateway_client = gateway_client
        self.market_data = GatewayMarketData(gateway_client)
        repository = CandleRepository(session_factory)
        self.ws_broadcaster = WsBroadcaster()
        self.candle_history = CandleHistoryService(self.market_data, repository)
        self.candle_stream = CandleStreamService(
            market_data=self.market_data,
            repository=repository,
            event_bus=self.event_bus,
            broadcaster=self.ws_broadcaster,
            symbols=self.symbols,
            timeframes=[Timeframe.M5],
        )
        key = Fernet.generate_key()
        self.account = AccountService(
            gateway=GatewayAccount(gateway_client),
            store=FernetCredentialStore(tmp_path / "credentials.enc", key_provider=lambda: key),
        )


@pytest.fixture
async def api(tmp_path):
    app = FastAPI()
    app.include_router(account_router)
    app.include_router(market_data_router)
    app.state.container = ContainerForTest(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


async def _connect(api, password="good-pw", remember=True):
    return await api.post(
        "/account/connect",
        json={"login": 123456, "password": password, "server": "Demo-Server", "remember": remember},
    )


async def test_login_flow_end_to_end(api):
    status = (await api.get("/account/status")).json()
    assert status == {
        "gateway_up": True,
        "connected": False,
        "account": None,
        "has_saved_credentials": False,
    }

    response = await _connect(api)
    assert response.status_code == 200
    assert response.json()["account"]["balance"] == 10_000.0

    status = (await api.get("/account/status")).json()
    assert status["connected"] is True
    assert status["has_saved_credentials"] is True

    response = await api.post("/account/disconnect", json={"forget": True})
    assert response.status_code == 200
    status = (await api.get("/account/status")).json()
    assert status["connected"] is False
    assert status["has_saved_credentials"] is False


async def test_bad_credentials_return_401_and_store_nothing(api):
    response = await _connect(api, password="wrong")
    assert response.status_code == 401
    assert "Authorization failed" in response.json()["detail"]
    assert (await api.get("/account/status")).json()["has_saved_credentials"] is False


async def test_candles_flow_live_and_db_fallback(api):
    await _connect(api)

    live = await api.get(
        "/market-data/candles", params={"symbol": "XAUUSD", "timeframe": "M5", "count": 5}
    )
    assert live.status_code == 200
    candles = live.json()
    assert len(candles) == 5
    assert candles[0]["time"] % M5 == 0
    assert candles[-1]["spread_points"] == 25

    stored = await api.post("/market-data/backfill", json={"count": 5})
    assert stored.json() == {
        "stored": {"XAUUSD:M1": 5, "XAUUSD:M5": 5, "XAUUSD:H1": 5, "XAUUSD:H4": 5, "XAUUSD:D1": 5}
    }

    # Gateway loses the session → candles now come from the DB.
    await api.post("/account/disconnect", json={})
    fallback = await api.get(
        "/market-data/candles", params={"symbol": "XAUUSD", "timeframe": "M5", "count": 3}
    )
    assert fallback.status_code == 200
    assert len(fallback.json()) == 3


async def test_symbol_info_reports_live_spread(api):
    await _connect(api)
    info = (await api.get("/market-data/symbol-info", params={"symbol": "XAUUSD"})).json()
    assert info["spread_points"] == 25
    assert info["stops_level"] == 10


async def test_symbol_info_unavailable_when_not_connected(api):
    response = await api.get("/market-data/symbol-info", params={"symbol": "XAUUSD"})
    assert response.status_code == 503
