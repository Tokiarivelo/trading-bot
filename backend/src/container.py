"""Composition root.

The only place where concrete adapters are chosen and wired to ports.
Modules receive their dependencies from here — they never construct
adapters themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from src.ai.adapters.report_repository import AnalysisReportRepository, RefinementProposalRepository
from src.ai.adapters.repository import DraftRepository
from src.ai.application.llm_router import LLMRouter
from src.ai.application.pdf_to_strategy import PdfToStrategyService
from src.ai.application.refinement_loop import RefinementLoopService
from src.broker.adapters.credential_store import FernetCredentialStore
from src.broker.adapters.mt5_gateway import GatewayAccount, GatewayBroker
from src.broker.adapters.paper import PaperBroker
from src.broker.application.account_service import AccountService
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.ports.trading import BrokerPort
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.application.trade_loop import TradeEngine
from src.journal.adapters.market_context import CandleRepositoryMarketContext
from src.journal.adapters.repository import JournalRepository
from src.journal.application.trade_journal import TradeJournalService
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.ws import WsBroadcaster
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.application.history import CandleHistoryService
from src.market_data.application.live_candle import LiveCandleService
from src.market_data.domain.models import Timeframe
from src.shared.config.loaders import (
    load_llm_provider_config,
    load_refinement_config,
    load_risk_caps,
    load_symbol_trading_config,
)
from src.shared.config.settings import Settings, load_yaml_config
from src.shared.db.base import make_session_factory
from src.shared.events.bus import EventBus
from src.shared.events.definitions import (
    CandleClosed,
    PositionClosed,
    PositionOpened,
    TenTradesCompleted,
)
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill, SessionWindow
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.generated.breakout_v1 import BreakoutV1
from src.strategies.registry import StrategyRegistry

_SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "normal"
_STRATEGIES_GENERATED_DIR = Path(__file__).resolve().parent / "strategies" / "generated"


@dataclass
class Container:
    settings: Settings
    event_bus: EventBus
    symbols: list[str]
    gateway_client: httpx.AsyncClient
    market_data: GatewayMarketData
    candle_history: CandleHistoryService
    candle_stream: CandleStreamService
    live_candle: LiveCandleService
    ws_broadcaster: WsBroadcaster
    account: AccountService
    broker: BrokerPort
    order_service: OrderService
    trade_journal: TradeJournalService
    trade_engine: TradeEngine
    strategy_registry: StrategyRegistry
    strategy_versions: StrategyVersionService
    skill_selector: SkillSelector
    pdf_to_strategy: PdfToStrategyService
    refinement_loop: RefinementLoopService

    _closers: list = field(default_factory=list)

    async def aclose(self) -> None:
        await self.candle_stream.stop()
        await self.live_candle.stop()
        await self.gateway_client.aclose()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    event_bus = EventBus()
    app_config = load_yaml_config("app", settings.configs_dir)
    symbols = list(app_config["symbols"])
    mode = app_config.get("mode", "paper")

    gateway_client = httpx.AsyncClient(
        base_url=settings.gateway_url,
        headers={"X-Gateway-Secret": settings.gateway_shared_secret},
        # 30 s: the Wine-hosted gateway can take 15-25 s on the first
        # mt5.initialize() call while the terminal completes its IPC handshake.
        timeout=30.0,
    )

    session_factory = make_session_factory(settings.database_url)
    market_data = GatewayMarketData(gateway_client)
    candle_repository = CandleRepository(session_factory)
    ws_broadcaster = WsBroadcaster()
    candle_stream = CandleStreamService(
        market_data=market_data,
        repository=candle_repository,
        event_bus=event_bus,
        broadcaster=ws_broadcaster,
        symbols=symbols,
        timeframes=list(Timeframe),
    )
    candle_history = CandleHistoryService(market_data, candle_repository)
    live_candle = LiveCandleService(market_data=market_data, broadcaster=ws_broadcaster)

    account = AccountService(
        gateway=GatewayAccount(gateway_client),
        store=FernetCredentialStore(Path("data/credentials.enc")),
    )

    # mode: paper (default, always safe) | live (real orders via the gateway).
    broker: BrokerPort = (
        GatewayBroker(gateway_client) if mode == "live" else PaperBroker(market_data)
    )

    symbol_configs = {
        symbol: load_symbol_trading_config(symbol, settings.configs_dir) for symbol in symbols
    }
    spread_gate = SpreadGate(symbol_configs)
    order_service = OrderService(
        broker=broker, market_data=market_data, spread_gate=spread_gate, event_bus=event_bus
    )

    journal_repository = JournalRepository(session_factory)
    market_context = CandleRepositoryMarketContext(candle_repository)
    review_every_n_trades = load_yaml_config("ai", settings.configs_dir).get(
        "review_every_n_trades", 10
    )
    trade_journal = TradeJournalService(
        repository=journal_repository,
        market_context=market_context,
        event_bus=event_bus,
        review_every_n_trades=review_every_n_trades,
    )
    event_bus.subscribe(PositionOpened, trade_journal.on_position_opened)
    event_bus.subscribe(PositionClosed, trade_journal.on_position_closed)

    timezone = app_config.get("timezone", "UTC")
    engine_config = app_config.get("engine", {})
    risk_caps = load_risk_caps(settings.configs_dir)
    risk_manager = RiskManager(caps=risk_caps, timezone=timezone)
    position_manager = PositionManager(order_service=order_service, market_data=market_data)

    strategy_registry = StrategyRegistry()
    strategy_registry.register(BreakoutV1())

    strategy_version_repository = StrategyVersionRepository(session_factory)
    strategy_versions = StrategyVersionService(
        repository=strategy_version_repository,
        registry=strategy_registry,
        generated_dir=_STRATEGIES_GENERATED_DIR,
    )
    # Restores whichever AI-generated versions were active before a restart;
    # runs after the baseline registration above so a same-named AI version
    # (unlikely, but possible) wins, matching what the DB says is live.
    strategy_versions.load_active_into_registry()

    llm_router = LLMRouter(
        load_llm_provider_config(settings.configs_dir),
        anthropic_api_key=settings.anthropic_api_key,
        ollama_url=settings.ollama_url,
    )
    draft_repository = DraftRepository(session_factory)
    pdf_to_strategy = PdfToStrategyService(
        draft_repository=draft_repository,
        strategy_versions=strategy_versions,
        llm_router=llm_router,
    )

    skill_selector = SkillSelector(
        skills={symbol: _load_normal_skill(symbol) for symbol in symbols}, timezone=timezone
    )

    refinement_loop = RefinementLoopService(
        report_repository=AnalysisReportRepository(session_factory),
        proposal_repository=RefinementProposalRepository(session_factory),
        journal_repository=journal_repository,
        strategy_versions=strategy_versions,
        strategy_registry=strategy_registry,
        skill_selector=skill_selector,
        llm_router=llm_router,
        refinement_config=load_refinement_config(settings.configs_dir),
        timezone=timezone,
    )
    event_bus.subscribe(TenTradesCompleted, refinement_loop.on_ten_trades_completed)

    trade_engine = TradeEngine(
        market_data=market_data,
        order_service=order_service,
        account=account,
        risk_manager=risk_manager,
        position_manager=position_manager,
        skill_selector=skill_selector,
        strategy_source=strategy_registry,
        entry_timeframe=engine_config.get("entry_timeframe", "M5"),
        confirmation_timeframes=tuple(engine_config.get("confirmation_timeframes", ["H1", "H4"])),
        enabled=engine_config.get("enabled", True),
    )
    event_bus.subscribe(CandleClosed, trade_engine.on_candle_closed)
    event_bus.subscribe(PositionClosed, trade_engine.on_position_closed)

    return Container(
        settings=settings,
        event_bus=event_bus,
        symbols=symbols,
        gateway_client=gateway_client,
        market_data=market_data,
        candle_history=candle_history,
        candle_stream=candle_stream,
        live_candle=live_candle,
        ws_broadcaster=ws_broadcaster,
        account=account,
        broker=broker,
        order_service=order_service,
        trade_journal=trade_journal,
        trade_engine=trade_engine,
        strategy_registry=strategy_registry,
        strategy_versions=strategy_versions,
        skill_selector=skill_selector,
        pdf_to_strategy=pdf_to_strategy,
        refinement_loop=refinement_loop,
    )


def _load_normal_skill(symbol: str) -> NormalSkill:
    path = _SKILLS_DIR / f"{symbol.lower()}.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    sessions = tuple(
        SessionWindow.parse(s["start"], s["end"]) for s in data.get("sessions", [])
    )
    return NormalSkill(
        name=data["name"],
        symbol=data["symbol"],
        strategy=data["strategy"],
        risk_multiplier=data.get("risk_multiplier", 1.0),
        sessions=sessions,
    )
