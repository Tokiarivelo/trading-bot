"""Phase 3 end-to-end (paper mode, no real MT5): open a position through the
broker API, confirm it's journaled with a market-context snapshot, close it,
and confirm the journal reflects the close and (after enough trades) fires
TenTradesCompleted.

Mirrors tests/integration/test_phase1_flow.py's fake-gateway approach.
"""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.broker.adapters.paper import PaperBroker
from src.broker.api.routes import router as account_router
from src.broker.api.trading_routes import router as trading_router
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.journal.adapters.market_context import CandleRepositoryMarketContext
from src.journal.adapters.repository import JournalRepository
from src.journal.api.routes import router as journal_router
from src.journal.application.trade_journal import TradeJournalService
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.routes import router as market_data_router
from src.market_data.api.ws import WsBroadcaster
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.application.history import CandleHistoryService
from src.market_data.domain.models import Timeframe
from src.shared.db.base import Base
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened, TenTradesCompleted

M5 = 300
XAUUSD_CONFIG = SymbolTradingConfig(
    symbol="XAUUSD",
    max_spread_points=35,
    min_rr=1.5,
    contract_size=100,
    point=0.01,
    digits=2,
    stops_level=0,
    volume_min=0.01,
    volume_max=50,
    volume_step=0.01,
)


def make_fake_gateway() -> FastAPI:
    gw = FastAPI()
    state = {"connected": True}
    account = {
        "login": 123456,
        "server": "Demo-Server",
        "name": "Test User",
        "currency": "USD",
        "balance": 10_000.0,
        "equity": 10_050.0,
        "leverage": 100,
    }

    @gw.get("/health")
    def health():
        return {"status": "ok", "terminal_connected": True, "account": account}

    @gw.get("/candles")
    def candles(symbol: str, timeframe: str, count: int = 300):
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
    def __init__(self, tmp_path, review_every_n_trades: int = 2):
        gateway_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_fake_gateway()), base_url="http://gw"
        )
        engine = create_engine(f"sqlite:///{tmp_path}/test.db")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        self.event_bus = EventBus()
        self.symbols = ["XAUUSD"]
        self.gateway_client = gateway_client
        self.market_data = GatewayMarketData(gateway_client)
        candle_repository = CandleRepository(session_factory)
        self.ws_broadcaster = WsBroadcaster()
        self.candle_history = CandleHistoryService(self.market_data, candle_repository)
        self.candle_stream = CandleStreamService(
            market_data=self.market_data,
            repository=candle_repository,
            event_bus=self.event_bus,
            broadcaster=self.ws_broadcaster,
            symbols=self.symbols,
            timeframes=[Timeframe.M5],
        )

        broker = PaperBroker(self.market_data)
        spread_gate = SpreadGate({"XAUUSD": XAUUSD_CONFIG})
        self.order_service = OrderService(
            broker=broker,
            market_data=self.market_data,
            spread_gate=spread_gate,
            event_bus=self.event_bus,
        )

        journal_repository = JournalRepository(session_factory)
        market_context = CandleRepositoryMarketContext(candle_repository)
        self.trade_journal = TradeJournalService(
            repository=journal_repository,
            market_context=market_context,
            event_bus=self.event_bus,
            review_every_n_trades=review_every_n_trades,
        )
        self.event_bus.subscribe(PositionOpened, self.trade_journal.on_position_opened)
        self.event_bus.subscribe(PositionClosed, self.trade_journal.on_position_closed)

        self.review_events: list[TenTradesCompleted] = []

        async def _capture_review(event: TenTradesCompleted) -> None:
            self.review_events.append(event)

        self.event_bus.subscribe(TenTradesCompleted, _capture_review)


@pytest.fixture
async def api(tmp_path):
    app = FastAPI()
    app.include_router(account_router)
    app.include_router(market_data_router)
    app.include_router(trading_router)
    app.include_router(journal_router)
    container = ContainerForTest(tmp_path)
    app.state.container = container
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        client.container = container  # test-only convenience accessor
        yield client


async def _backfill_market_context(api) -> None:
    # Journal snapshots read from the candle repository — seed it once so
    # "capture" has something to serve.
    await api.post("/market-data/backfill", json={"count": 5})


async def test_open_position_is_journaled_with_snapshot(api):
    await _backfill_market_context(api)

    opened = await api.post(
        "/broker/orders",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
    )
    assert opened.status_code == 200
    body = opened.json()
    assert body["price"] == 2400.35
    ticket = body["ticket"]

    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 1
    assert positions[0]["ticket"] == ticket

    trades = (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json()
    assert len(trades) == 1
    assert trades[0]["id"] == str(ticket)
    assert trades[0]["close_time"] is None


async def test_rejected_order_is_not_journaled(api):
    await _backfill_market_context(api)

    # No sl/tp → fails the spread/RR gate.
    rejected = await api.post(
        "/broker/orders", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1}
    )
    assert rejected.status_code == 422

    assert (await api.get("/broker/positions")).json() == []
    assert (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json() == []


async def test_close_position_updates_journal_and_markers(api):
    await _backfill_market_context(api)

    opened = await api.post(
        "/broker/orders",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
    )
    ticket = opened.json()["ticket"]

    closed = await api.post(f"/broker/positions/{ticket}/close")
    assert closed.status_code == 200
    assert closed.json()["price"] == 2400.10

    assert (await api.get("/broker/positions")).json() == []

    markers = (await api.get("/journal/markers", params={"symbol": "XAUUSD"})).json()
    assert len(markers) == 1
    assert markers[0]["close_price"] == 2400.10
    assert markers[0]["close_time"] is not None
    assert markers[0]["profit"] is not None


async def test_ten_trade_review_fires_after_threshold(api):
    """ContainerForTest is built with review_every_n_trades=2 for a fast test."""
    await _backfill_market_context(api)

    for _ in range(2):
        opened = await api.post(
            "/broker/orders",
            json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
        )
        ticket = opened.json()["ticket"]
        await api.post(f"/broker/positions/{ticket}/close")

    trades = (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json()
    assert len(trades) == 2
    assert all(t["close_time"] is not None for t in trades)

    assert len(api.container.review_events) == 1
    assert api.container.review_events[0].symbol == "XAUUSD"
    assert len(api.container.review_events[0].trade_ids) == 2
