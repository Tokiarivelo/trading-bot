from datetime import UTC, datetime, timedelta

from src.news.application.news_window_service import NewsWindowService
from src.news.domain.models import ImpactLevel, NewsConfig, NewsEvent, TrackedEvent, WindowSpec
from src.shared.events.bus import EventBus
from src.shared.events.definitions import NewsWindowEntered, NewsWindowExited

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class FakeCalendar:
    def __init__(self, events: list[NewsEvent]) -> None:
        self.events = events
        self.calls = 0

    async def fetch_upcoming(self, days_ahead: int) -> list[NewsEvent]:
        self.calls += 1
        return self.events


def make_config(tracked: tuple[TrackedEvent, ...]) -> NewsConfig:
    return NewsConfig(
        calendar_source="forexfactory",
        refresh_minutes=60,
        tracked_events=tracked,
        default_before_min=30,
        default_after_min=60,
    )


def make_service(events, tracked, specs, event_bus=None) -> NewsWindowService:
    return NewsWindowService(
        calendar=FakeCalendar(events),
        config=make_config(tracked),
        window_specs=specs,
        event_bus=event_bus or EventBus(),
    )


async def test_refresh_populates_cache():
    event = NewsEvent(name="Non-Farm Payrolls", time=NOW, impact=ImpactLevel.HIGH)
    service = make_service([event], (), {})
    await service.refresh(NOW)
    assert service.upcoming(now=NOW - timedelta(hours=1)) == [event]


async def test_active_window_for_matches_exact_tracked_event():
    event = NewsEvent(name="Non-Farm Payrolls", time=NOW, impact=ImpactLevel.HIGH)
    tracked = (TrackedEvent(name="Non-Farm Payrolls", impact=ImpactLevel.HIGH, skill="nfp"),)
    specs = {
        "nfp": WindowSpec(
            skill_name="nfp", before_min=30, after_min=60, symbols=("XAUUSD",), close_all=True
        )
    }
    service = make_service([event], tracked, specs)
    await service.refresh(NOW)

    window = service.active_window_for("XAUUSD", NOW)
    assert window is not None
    assert window.skill == "nfp"
    assert service.active_window_for("BTCUSD", NOW) is None  # not in spec.symbols


async def test_active_window_for_falls_back_to_wildcard():
    event = NewsEvent(name="Some Unlisted Release", time=NOW, impact=ImpactLevel.HIGH)
    tracked = (
        TrackedEvent(name="Non-Farm Payrolls", impact=ImpactLevel.HIGH, skill="nfp"),
        TrackedEvent(name="*", impact=ImpactLevel.HIGH, skill="generic_high_impact"),
    )
    specs = {
        "generic_high_impact": WindowSpec(
            skill_name="generic_high_impact", before_min=15, after_min=30, symbols=("XAUUSD",)
        )
    }
    service = make_service([event], tracked, specs)
    await service.refresh(NOW)

    window = service.active_window_for("XAUUSD", NOW)
    assert window is not None
    assert window.skill == "generic_high_impact"


async def test_no_match_means_no_active_window():
    event = NewsEvent(name="Retail Sales", time=NOW, impact=ImpactLevel.LOW)
    tracked = (TrackedEvent(name="*", impact=ImpactLevel.HIGH, skill="generic_high_impact"),)
    service = make_service([event], tracked, {})
    await service.refresh(NOW)

    assert service.active_window_for("XAUUSD", NOW) is None


async def test_active_window_only_within_before_after_bounds():
    event = NewsEvent(name="Non-Farm Payrolls", time=NOW, impact=ImpactLevel.HIGH)
    tracked = (TrackedEvent(name="Non-Farm Payrolls", impact=ImpactLevel.HIGH, skill="nfp"),)
    specs = {"nfp": WindowSpec(skill_name="nfp", before_min=30, after_min=60, symbols=("XAUUSD",))}
    service = make_service([event], tracked, specs)
    await service.refresh(NOW)

    assert service.active_window_for("XAUUSD", NOW - timedelta(minutes=31)) is None
    assert service.active_window_for("XAUUSD", NOW + timedelta(minutes=61)) is None
    assert service.active_window_for("XAUUSD", NOW + timedelta(minutes=30)) is not None


async def test_check_transitions_publishes_entered_then_exited():
    event = NewsEvent(name="Non-Farm Payrolls", time=NOW, impact=ImpactLevel.HIGH)
    tracked = (TrackedEvent(name="Non-Farm Payrolls", impact=ImpactLevel.HIGH, skill="nfp"),)
    specs = {
        "nfp": WindowSpec(
            skill_name="nfp", before_min=30, after_min=60, symbols=("XAUUSD",), close_all=True
        )
    }
    event_bus = EventBus()
    entered: list[NewsWindowEntered] = []
    exited: list[NewsWindowExited] = []

    async def on_entered(e: NewsWindowEntered) -> None:
        entered.append(e)

    async def on_exited(e: NewsWindowExited) -> None:
        exited.append(e)

    event_bus.subscribe(NewsWindowEntered, on_entered)
    event_bus.subscribe(NewsWindowExited, on_exited)
    service = make_service([event], tracked, specs, event_bus=event_bus)
    await service.refresh(NOW)

    await service._check_transitions(NOW)  # inside the window
    assert len(entered) == 1
    assert entered[0].event_name == "Non-Farm Payrolls"
    assert entered[0].symbols == ("XAUUSD",)
    assert entered[0].close_all is True

    await service._check_transitions(NOW + timedelta(minutes=61))  # outside the window
    assert len(exited) == 1
    assert exited[0].event_name == "Non-Farm Payrolls"
