from datetime import UTC, datetime, timedelta

from src.news.domain.models import ImpactLevel, NewsEvent, NewsWindow

EVENT_TIME = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)


def make_window(before_min=30, after_min=60) -> NewsWindow:
    event = NewsEvent(name="Non-Farm Payrolls", time=EVENT_TIME, impact=ImpactLevel.HIGH)
    return NewsWindow(
        event=event,
        skill="nfp",
        window_start=EVENT_TIME - timedelta(minutes=before_min),
        window_end=EVENT_TIME + timedelta(minutes=after_min),
    )


def test_contains_before_and_after_event():
    window = make_window()
    assert window.contains(EVENT_TIME - timedelta(minutes=10))
    assert window.contains(EVENT_TIME)
    assert window.contains(EVENT_TIME + timedelta(minutes=10))
    assert not window.contains(EVENT_TIME - timedelta(minutes=31))
    assert not window.contains(EVENT_TIME + timedelta(minutes=61))


def test_is_pre_only_strictly_before_event_time():
    window = make_window()
    assert window.is_pre(EVENT_TIME - timedelta(minutes=1))
    assert not window.is_pre(EVENT_TIME)
    assert not window.is_pre(EVENT_TIME + timedelta(minutes=1))


def test_is_post_from_event_time_inclusive():
    window = make_window()
    assert window.is_post(EVENT_TIME)
    assert window.is_post(EVENT_TIME + timedelta(minutes=1))
    assert not window.is_post(EVENT_TIME - timedelta(minutes=1))
