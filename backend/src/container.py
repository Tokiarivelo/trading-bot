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
from src.alerting.adapters.composite import CompositeAlertAdapter
from src.alerting.adapters.email import EmailAlertAdapter
from src.alerting.adapters.noop import NoopAlertAdapter
from src.alerting.adapters.telegram import TelegramAlertAdapter
from src.alerting.application.alert_service import AlertService
from src.alerting.ports.alert import AlertPort
from src.broker.adapters.credential_store import FernetCredentialStore
from src.broker.adapters.mt5_gateway import GatewayAccount, GatewayBroker
from src.broker.adapters.paper import PaperBroker
from src.broker.application.account_service import AccountService
from src.broker.application.health_monitor import GatewayHealthMonitor
from src.broker.application.order_service import OrderService
from src.broker.application.reconciliation import ReconciliationService
from src.broker.application.spread_gate import SpreadGate
from src.broker.ports.trading import BrokerPort
from src.engine.application.manual_trading import ManualTradeGate
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
from src.news.adapters.finnhub import FinnhubCalendar
from src.news.adapters.forexfactory import ForexFactoryCalendar
from src.news.application.news_window_service import NewsWindowService
from src.news.domain.models import WindowSpec
from src.news.ports.calendar import NewsCalendarPort
from src.shared.auth.session import SessionTokenIssuer
from src.shared.config.loaders import (
    load_alerting_config,
    load_llm_provider_config,
    load_news_config,
    load_refinement_config,
    load_risk_caps,
    load_symbol_trading_config,
)
from src.shared.config.settings import Settings, load_yaml_config
from src.shared.db.base import make_session_factory
from src.shared.events.bus import EventBus
from src.shared.events.definitions import (
    CandleClosed,
    CircuitBreakerTripped,
    GatewayHealthChanged,
    NewsWindowEntered,
    PositionClosed,
    PositionOpened,
    RefinementCompleted,
    TenTradesCompleted,
)
from src.skills.application.news_skill_selector import NewsSkillSelector
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import (
    NewsActivation,
    NewsActivationWindow,
    NewsSkill,
    NormalSkill,
    PostEventRules,
    PreEventRules,
    SessionWindow,
)
from src.skills.ports.skill_selector import SkillSelectorPort
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.generated.breakout_v1 import BreakoutV1
from src.strategies.registry import StrategyRegistry

_SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "normal"
_NEWS_SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "news"
_STRATEGIES_GENERATED_DIR = Path(__file__).resolve().parent / "strategies" / "generated"


@dataclass
class Container:
    settings: Settings
    event_bus: EventBus
    session_issuer: SessionTokenIssuer
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
    manual_trade_gate: ManualTradeGate
    reconciliation: ReconciliationService
    health_monitor: GatewayHealthMonitor
    trade_journal: TradeJournalService
    trade_engine: TradeEngine
    strategy_registry: StrategyRegistry
    strategy_versions: StrategyVersionService
    skill_selector: SkillSelectorPort
    pdf_to_strategy: PdfToStrategyService
    refinement_loop: RefinementLoopService
    news_client: httpx.AsyncClient
    news_window_service: NewsWindowService

    _closers: list = field(default_factory=list)
    alert_telegram_client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        await self.candle_stream.stop()
        await self.live_candle.stop()
        await self.news_window_service.stop()
        await self.health_monitor.stop()
        await self.gateway_client.aclose()
        await self.news_client.aclose()
        if self.alert_telegram_client is not None:
            await self.alert_telegram_client.aclose()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    event_bus = EventBus()
    session_issuer = SessionTokenIssuer()
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

    alerting_config = load_alerting_config(settings.configs_dir)
    alert_adapters: list[AlertPort] = []
    alert_telegram_client: httpx.AsyncClient | None = None
    if alerting_config.telegram_enabled and settings.telegram_bot_token:
        alert_telegram_client = httpx.AsyncClient(base_url="https://api.telegram.org", timeout=10.0)
        alert_adapters.append(
            TelegramAlertAdapter(
                alert_telegram_client, settings.telegram_bot_token, settings.telegram_chat_id
            )
        )
    if alerting_config.email_enabled and alerting_config.smtp_host:
        alert_adapters.append(
            EmailAlertAdapter(
                smtp_host=alerting_config.smtp_host,
                smtp_port=alerting_config.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                from_address=alerting_config.from_address,
                to_address=alerting_config.to_address,
            )
        )
    alert_port: AlertPort = (
        CompositeAlertAdapter(alert_adapters) if alert_adapters else NoopAlertAdapter()
    )
    alert_service = AlertService(port=alert_port, config=alerting_config)
    event_bus.subscribe(PositionOpened, alert_service.on_position_opened)
    event_bus.subscribe(PositionClosed, alert_service.on_position_closed)
    event_bus.subscribe(CircuitBreakerTripped, alert_service.on_circuit_breaker_tripped)
    event_bus.subscribe(RefinementCompleted, alert_service.on_refinement_completed)
    event_bus.subscribe(GatewayHealthChanged, alert_service.on_gateway_health_changed)

    timezone = app_config.get("timezone", "UTC")
    engine_config = app_config.get("engine", {})
    risk_caps = load_risk_caps(settings.configs_dir)
    risk_manager = RiskManager(caps=risk_caps, timezone=timezone)
    manual_trade_gate = ManualTradeGate(order_service=order_service, risk_manager=risk_manager)

    reconciliation = ReconciliationService(
        broker=broker, journal=trade_journal, event_bus=event_bus
    )
    health_monitor = GatewayHealthMonitor(
        account=account, reconciliation=reconciliation, event_bus=event_bus
    )
    position_manager = PositionManager(
        order_service=order_service,
        market_data=market_data,
        reconciliation=reconciliation,
        risk_manager=risk_manager,
    )

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

    normal_skill_selector = SkillSelector(
        skills={symbol: _load_normal_skill(symbol) for symbol in symbols}, timezone=timezone
    )

    news_config = load_news_config(settings.configs_dir)
    news_skills = _load_news_skills()
    window_specs = {
        name: WindowSpec(
            skill_name=name,
            before_min=skill.activation.window.before_min,
            after_min=skill.activation.window.after_min,
            symbols=skill.activation.symbols,
            close_all=skill.pre_event.close_all,
        )
        for name, skill in news_skills.items()
    }
    news_client = httpx.AsyncClient(
        base_url=(
            settings.finnhub_calendar_url
            if news_config.calendar_source == "finnhub"
            else settings.forexfactory_calendar_url
        ),
        timeout=15.0,
    )
    news_calendar: NewsCalendarPort = (
        FinnhubCalendar(news_client, settings.finnhub_api_key)
        if news_config.calendar_source == "finnhub"
        else ForexFactoryCalendar(news_client)
    )
    news_window_service = NewsWindowService(
        calendar=news_calendar,
        config=news_config,
        window_specs=window_specs,
        event_bus=event_bus,
    )
    skill_selector: SkillSelectorPort = NewsSkillSelector(
        normal_selector=normal_skill_selector,
        news_skills=news_skills,
        window_source=news_window_service,
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
        event_bus=event_bus,
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
        event_bus=event_bus,
        enabled=engine_config.get("enabled", True),
    )
    event_bus.subscribe(CandleClosed, trade_engine.on_candle_closed)
    event_bus.subscribe(PositionClosed, trade_engine.on_position_closed)
    event_bus.subscribe(NewsWindowEntered, trade_engine.on_news_window_entered)

    return Container(
        settings=settings,
        event_bus=event_bus,
        session_issuer=session_issuer,
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
        manual_trade_gate=manual_trade_gate,
        reconciliation=reconciliation,
        health_monitor=health_monitor,
        trade_journal=trade_journal,
        trade_engine=trade_engine,
        strategy_registry=strategy_registry,
        strategy_versions=strategy_versions,
        skill_selector=skill_selector,
        pdf_to_strategy=pdf_to_strategy,
        refinement_loop=refinement_loop,
        news_client=news_client,
        news_window_service=news_window_service,
        alert_telegram_client=alert_telegram_client,
    )


def _load_normal_skill(symbol: str) -> NormalSkill:
    path = _SKILLS_DIR / f"{symbol.lower()}.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    sessions = tuple(SessionWindow.parse(s["start"], s["end"]) for s in data.get("sessions", []))
    return NormalSkill(
        name=data["name"],
        symbol=data["symbol"],
        strategy=data["strategy"],
        risk_multiplier=data.get("risk_multiplier", 1.0),
        sessions=sessions,
    )


def _load_news_skills() -> dict[str, NewsSkill]:
    skills: dict[str, NewsSkill] = {}
    for path in sorted(_NEWS_SKILLS_DIR.glob("*.yaml")):
        with path.open() as f:
            data = yaml.safe_load(f)
        activation = data["activation"]
        window = activation["window"]
        pre = data["rules"]["pre_event"]
        post = data["rules"]["post_event"]
        skill = NewsSkill(
            name=data["name"],
            activation=NewsActivation(
                calendar_events=tuple(activation["calendar_event"]),
                window=NewsActivationWindow(
                    before_min=window["before_min"], after_min=window["after_min"]
                ),
                symbols=tuple(activation["symbols"]),
            ),
            pre_event=PreEventRules(
                close_all=pre.get("close_all", False),
                block_new_entries=pre.get("block_new_entries", True),
            ),
            post_event=PostEventRules(
                wait_candles_m5=post.get("wait_candles_m5", 0),
                strategy_override=post.get("strategy_override", ""),
                max_spread_points=post.get("max_spread_points", 0),
                risk_multiplier=post.get("risk_multiplier", 1.0),
            ),
        )
        skills[skill.name] = skill
    return skills
