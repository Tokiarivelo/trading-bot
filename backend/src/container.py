"""Composition root.

The only place where concrete adapters are chosen and wired to ports.
Modules receive their dependencies from here — they never construct
adapters themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.shared.config.settings import Settings
from src.shared.events.bus import EventBus


@dataclass
class Container:
    settings: Settings
    event_bus: EventBus

    # Later phases add wired module services here, e.g.:
    #   market_data: MarketDataService   (Phase 1)
    #   broker: BrokerService            (Phase 3)
    #   engine: TradeEngine              (Phase 4)
    #   ai: AiService                    (Phase 6)


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    return Container(settings=settings, event_bus=EventBus())
