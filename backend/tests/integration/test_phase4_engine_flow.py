"""Phase 4 end-to-end (paper mode, no real MT5): a CandleClosed(M5) event
drives the full engine pipe — skill selection, the real breakout_v1 strategy,
HTF confirmation, risk sizing, and order placement through the broker API —
then confirms the trade lands in the journal with strategy/skill attribution.

Mirrors tests/integration/test_phase3_broker_flow.py's fake-gateway approach.
"""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.broker.adapters.paper import PaperBroker
from src.broker.api.routes import router as account_router
from src.broker.api.trading_routes import router as trading_router
from src.broker.application.account_service import AccountService
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.engine.api.routes import router as engine_router
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.application.trade_loop import TradeEngine
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
from src.shared.events.definitions import CandleClosed, PositionClosed, PositionOpened
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill
from src.strategies.generated.breakout_v1 import BreakoutV1
from src.strategies.registry import StrategyRegistry

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
RISK_CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=2,
    max_trades_per_day=8,
    consecutive_loss_pause=5,
)


def make_fake_gateway() -> FastAPI:
    """M5 candles form a clean 20-bar range followed by a breakout bar; H1/H4
    only get a handful of bars so `mtf_confirm` skips (insufficient history)
    instead of vetoing on trend."""
    gw = FastAPI()
    account = {
        "login": 123456,
        "server": "Demo-Server",
        "name": "Test User",
        "currency": "USD",
        "balance": 10_000.0,
        "equity": 10_000.0,
        "leverage": 100,
    }

    @gw.get("/health")
    def health():
        return {"status": "ok", "terminal_connected": True, "account": account}

    @gw.get("/candles")
    def candles(symbol: str, timeframe: str, count: int = 300):
        latest_open = int(time.time()) // M5 * M5
        if timeframe == "M5":
            n = 21
            bars = [
                {
                    "time": latest_open - (n - 1 - i) * M5,
                    "open": 2400.0,
                    "high": 2401.0,
                    "low": 2399.0,
                    "close": 2400.0,
                    "tick_volume": 1000,
                    "spread": 25,
                }
                for i in range(n - 1)
            ]
            bars.append(
                {
                    "time": latest_open - M5,
                    "open": 2401.0,
                    "high": 2411.0,
                    "low": 2400.5,
                    "close": 2410.0,
                    "tick_volume": 1500,
                    "spread": 25,
                }
            )
            return bars
        n = 5
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
    def __init__(self, tmp_path):
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
        self.account = AccountService(gateway=_FakeAccountGateway(), store=_NullStore())

        journal_repository = JournalRepository(session_factory)
        market_context = CandleRepositoryMarketContext(candle_repository)
        self.trade_journal = TradeJournalService(
            repository=journal_repository,
            market_context=market_context,
            event_bus=self.event_bus,
            review_every_n_trades=10,
        )
        self.event_bus.subscribe(PositionOpened, self.trade_journal.on_position_opened)
        self.event_bus.subscribe(PositionClosed, self.trade_journal.on_position_closed)

        risk_manager = RiskManager(caps=RISK_CAPS, timezone="UTC")
        position_manager = PositionManager(self.order_service, self.market_data)
        strategy_registry = StrategyRegistry()
        strategy_registry.register(BreakoutV1())
        skill_selector = SkillSelector(
            skills={
                "XAUUSD": NormalSkill(
                    name="normal/xauusd", symbol="XAUUSD", strategy="breakout_v1", sessions=()
                )
            },
            timezone="UTC",
        )
        self.trade_engine = TradeEngine(
            market_data=self.market_data,
            order_service=self.order_service,
            account=self.account,
            risk_manager=risk_manager,
            position_manager=position_manager,
            skill_selector=skill_selector,
            strategy_source=strategy_registry,
            entry_timeframe="M5",
            confirmation_timeframes=("H1", "H4"),
            context_bars=30,
        )
        self.event_bus.subscribe(CandleClosed, self.trade_engine.on_candle_closed)
        self.event_bus.subscribe(PositionClosed, self.trade_engine.on_position_closed)


class _FakeAccountGateway:
    async def login(self, credentials):  # pragma: no cover - unused in this test
        raise NotImplementedError

    async def logout(self) -> None:  # pragma: no cover - unused in this test
        raise NotImplementedError

    async def health(self):
        from src.broker.domain.account import AccountInfo, GatewayHealth

        return GatewayHealth(
            gateway_up=True,
            terminal_connected=True,
            account=AccountInfo(
                login=123456,
                server="Demo-Server",
                name="Test User",
                currency="USD",
                balance=10_000.0,
                equity=10_000.0,
                leverage=100,
            ),
        )


class _NullStore:
    def save(self, credentials) -> None:  # pragma: no cover - unused in this test
        pass

    def load(self):
        return None

    def clear(self) -> None:  # pragma: no cover - unused in this test
        pass


@pytest.fixture
async def api(tmp_path):
    app = FastAPI()
    app.include_router(account_router)
    app.include_router(market_data_router)
    app.include_router(trading_router)
    app.include_router(journal_router)
    app.include_router(engine_router)
    container = ContainerForTest(tmp_path)
    app.state.container = container
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        client.container = container
        yield client


async def test_candle_close_drives_full_entry_through_the_engine(api):
    await api.container.trade_engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "XAUUSD"
    assert positions[0]["side"] == "buy"

    trades = (await api.get("/journal/trades", params={"symbol": "XAUUSD"})).json()
    assert len(trades) == 1
    assert trades[0]["strategy_version"] == "breakout_v1:v1"
    assert trades[0]["skill"] == "normal/xauusd"

    status = (await api.get("/engine/status")).json()
    assert status["trades_today"] == 1
    assert not status["paused"]


async def test_kill_switch_endpoint_pauses_and_closes_positions(api):
    await api.container.trade_engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    assert len((await api.get("/broker/positions")).json()) == 1

    killed = await api.post("/engine/kill")
    assert killed.status_code == 200
    assert killed.json()["paused"] is True

    assert (await api.get("/broker/positions")).json() == []

    resumed = await api.post("/engine/resume")
    assert resumed.json()["paused"] is False


async def test_engine_does_not_reenter_once_max_open_positions_reached(api):
    await api.container.trade_engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    # RISK_CAPS allows 2 open positions; feed the same breakout candle again —
    # the strategy would signal again, but this asserts the pipe runs
    # end-to-end a second time without error and caps eventually apply.
    await api.container.trade_engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 2  # exactly at the cap, not beyond

    await api.container.trade_engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    positions = (await api.get("/broker/positions")).json()
    assert len(positions) == 2  # third attempt blocked by max_open_positions
