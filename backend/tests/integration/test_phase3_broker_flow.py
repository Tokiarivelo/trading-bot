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
from src.broker.application.reconciliation import ReconciliationService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.engine.application.manual_trading import ManualTradeGate
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps
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

TEST_RISK_CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=10,
    max_trades_per_day=100,
    consecutive_loss_pause=5,
)

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


def make_fake_gateway() -> tuple[FastAPI, dict]:
    gw = FastAPI()
    state = {"connected": True, "bid": 2400.10, "ask": 2400.35}
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
            "bid": state["bid"],
            "ask": state["ask"],
            "spread_points": 25,
            "point": 0.01,
            "digits": 2,
            "stops_level": 10,
            "contract_size": 100.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
        }

    return gw, state


class ContainerForTest:
    def __init__(self, tmp_path, review_every_n_trades: int = 2, max_open_positions: int = 10):
        gateway_app, self.gateway_state = make_fake_gateway()
        gateway_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway_app), base_url="http://gw"
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
        caps = (
            TEST_RISK_CAPS
            if max_open_positions == 10
            else RiskCaps(
                risk_per_trade_pct=TEST_RISK_CAPS.risk_per_trade_pct,
                daily_loss_limit_pct=TEST_RISK_CAPS.daily_loss_limit_pct,
                max_open_positions=max_open_positions,
                max_trades_per_day=TEST_RISK_CAPS.max_trades_per_day,
                consecutive_loss_pause=TEST_RISK_CAPS.consecutive_loss_pause,
            )
        )
        self.risk_manager = RiskManager(caps=caps, timezone="UTC")
        self.manual_trade_gate = ManualTradeGate(
            order_service=self.order_service, risk_manager=self.risk_manager
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

        self.reconciliation = ReconciliationService(
            broker=broker, journal=self.trade_journal, event_bus=self.event_bus
        )
        self.position_manager = PositionManager(
            order_service=self.order_service,
            market_data=self.market_data,
            reconciliation=self.reconciliation,
            risk_manager=self.risk_manager,
        )

        self.review_events: list[TenTradesCompleted] = []

        async def _capture_review(event: TenTradesCompleted) -> None:
            self.review_events.append(event)

        self.event_bus.subscribe(TenTradesCompleted, _capture_review)


def _make_api_client(container: ContainerForTest):
    app = FastAPI()
    app.include_router(account_router)
    app.include_router(market_data_router)
    app.include_router(trading_router)
    app.include_router(journal_router)
    app.state.container = container
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://backend")


@pytest.fixture
async def api(tmp_path):
    container = ContainerForTest(tmp_path)
    async with _make_api_client(container) as client:
        client.container = container  # test-only convenience accessor
        yield client


@pytest.fixture
async def api_capped(tmp_path):
    """Same as `api` but `max_open_positions=1`, for testing the manual-trade
    risk gate's rejection path without opening 10 positions."""
    container = ContainerForTest(tmp_path, max_open_positions=1)
    async with _make_api_client(container) as client:
        client.container = container
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

    # sl/tp both given but too tight for XAUUSD's min_rr=1.5 → fails the RR gate.
    rejected = await api.post(
        "/broker/orders",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2399.0, "tp": 2400.5},
    )
    assert rejected.status_code == 422

    assert (await api.get("/broker/positions")).json() == []
    assert (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json() == []


async def test_market_order_without_sl_tp_is_allowed(api):
    """sl/tp are optional (F-manual-trading) — a manual trader can open naked
    and set SL/TP later, e.g. by dragging the chart's price lines."""
    await _backfill_market_context(api)

    opened = await api.post(
        "/broker/orders", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1}
    )
    assert opened.status_code == 200
    assert opened.json()["sl"] is None
    assert opened.json()["tp"] is None

    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 1


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


async def test_market_order_rejected_at_max_open_positions(api_capped):
    await _backfill_market_context(api_capped)

    first = await api_capped.post(
        "/broker/orders",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
    )
    assert first.status_code == 200

    second = await api_capped.post(
        "/broker/orders",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
    )
    assert second.status_code == 422
    assert "max open positions" in second.json()["detail"]

    positions = (await api_capped.get("/broker/positions")).json()
    assert len(positions) == 1


async def test_place_list_modify_cancel_pending_order(api):
    placed = await api.post(
        "/broker/orders/pending",
        json={
            "symbol": "XAUUSD",
            "side": "buy",
            "order_type": "limit",
            "volume": 0.1,
            "price": 2395.0,
            "sl": 2390.0,
            "tp": 2415.0,
        },
    )
    assert placed.status_code == 200
    ticket = placed.json()["ticket"]
    assert placed.json()["order_type"] == "limit"

    listed = (await api.get("/broker/orders/pending", params={"symbol": "XAUUSD"})).json()
    assert len(listed) == 1
    assert listed[0]["ticket"] == ticket

    modified = await api.post(
        f"/broker/orders/pending/{ticket}/modify", json={"price": 2394.0, "sl": None, "tp": None}
    )
    assert modified.status_code == 200
    listed = (await api.get("/broker/orders/pending")).json()
    assert listed[0]["price"] == 2394.0

    cancelled = await api.delete(f"/broker/orders/pending/{ticket}")
    assert cancelled.status_code == 200
    assert (await api.get("/broker/orders/pending")).json() == []


async def test_pending_order_above_ask_is_rejected(api):
    # Buy-limit at 2405 is above the current ask (2400.35) — wrong side of
    # market for a limit order, so the paper broker refuses it.
    rejected = await api.post(
        "/broker/orders/pending",
        json={
            "symbol": "XAUUSD",
            "side": "buy",
            "order_type": "limit",
            "volume": 0.1,
            "price": 2405.0,
        },
    )
    assert rejected.status_code == 422


async def test_pending_order_fills_when_price_crosses_and_is_journaled(api):
    await _backfill_market_context(api)

    placed = await api.post(
        "/broker/orders/pending",
        json={
            "symbol": "XAUUSD",
            "side": "buy",
            "order_type": "limit",
            "volume": 0.1,
            "price": 2395.0,
            "sl": 2385.0,
            "tp": 2415.0,
        },
    )
    ticket = placed.json()["ticket"]

    # Price hasn't reached the trigger yet — a candle close should leave it resting.
    await api.container.position_manager.on_candle_closed("XAUUSD")
    assert (await api.get("/broker/orders/pending")).json()[0]["ticket"] == ticket
    assert (await api.get("/broker/positions")).json() == []

    # Now the ask drops through the buy-limit's trigger price.
    api.container.gateway_state["ask"] = 2394.0
    await api.container.position_manager.on_candle_closed("XAUUSD")

    assert (await api.get("/broker/orders/pending")).json() == []
    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 1
    assert positions[0]["open_price"] == 2394.0

    trades = (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json()
    assert len(trades) == 1

    assert api.container.risk_manager.status.trades_today == 1
