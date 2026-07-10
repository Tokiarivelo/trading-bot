"""Composition root.

The only place where concrete adapters are chosen and wired to ports.
Modules receive their dependencies from here — they never construct
adapters themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from src.broker.adapters.credential_store import FernetCredentialStore
from src.broker.adapters.mt5_gateway import GatewayAccount
from src.broker.application.account_service import AccountService
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.mt5_gateway import GatewayMarketData
from src.market_data.api.ws import WsBroadcaster
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.application.history import CandleHistoryService
from src.market_data.domain.models import Timeframe
from src.shared.config.settings import Settings, load_yaml_config
from src.shared.db.base import make_session_factory
from src.shared.events.bus import EventBus


@dataclass
class Container:
    settings: Settings
    event_bus: EventBus
    symbols: list[str]
    gateway_client: httpx.AsyncClient
    market_data: GatewayMarketData
    candle_history: CandleHistoryService
    candle_stream: CandleStreamService
    ws_broadcaster: WsBroadcaster
    account: AccountService

    # Later phases add wired module services here, e.g.:
    #   engine: TradeEngine              (Phase 4)
    #   ai: AiService                    (Phase 6)
    _closers: list = field(default_factory=list)

    async def aclose(self) -> None:
        await self.candle_stream.stop()
        await self.gateway_client.aclose()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    event_bus = EventBus()
    symbols = list(load_yaml_config("app", settings.configs_dir)["symbols"])

    gateway_client = httpx.AsyncClient(
        base_url=settings.gateway_url,
        headers={"X-Gateway-Secret": settings.gateway_shared_secret},
        timeout=10.0,
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

    account = AccountService(
        gateway=GatewayAccount(gateway_client),
        store=FernetCredentialStore(Path("data/credentials.enc")),
    )

    return Container(
        settings=settings,
        event_bus=event_bus,
        symbols=symbols,
        gateway_client=gateway_client,
        market_data=market_data,
        candle_history=candle_history,
        candle_stream=candle_stream,
        ws_broadcaster=ws_broadcaster,
        account=account,
    )
