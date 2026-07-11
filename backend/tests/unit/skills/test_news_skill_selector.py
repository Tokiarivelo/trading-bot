from datetime import UTC, datetime, timedelta

from src.news.domain.models import ImpactLevel, NewsEvent, NewsWindow
from src.skills.application.news_skill_selector import NewsSkillSelector
from src.skills.domain.models import (
    NewsActivation,
    NewsActivationWindow,
    NewsSkill,
    PostEventRules,
    PreEventRules,
)
from src.skills.ports.skill_selector import SkillDecision

EVENT_TIME = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)


class FakeNormalSelector:
    def __init__(self, decision: SkillDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[str, datetime]] = []

    def select(self, symbol: str, now: datetime | None = None) -> SkillDecision:
        self.calls.append((symbol, now))
        return self.decision


class FakeWindowSource:
    def __init__(self, window: NewsWindow | None) -> None:
        self.window = window

    def active_window_for(self, symbol: str, now: datetime) -> NewsWindow | None:
        return self.window


def make_window(before_min=30, after_min=60, skill="nfp") -> NewsWindow:
    event = NewsEvent(name="Non-Farm Payrolls", time=EVENT_TIME, impact=ImpactLevel.HIGH)
    return NewsWindow(
        event=event,
        skill=skill,
        window_start=EVENT_TIME - timedelta(minutes=before_min),
        window_end=EVENT_TIME + timedelta(minutes=after_min),
    )


def make_skill(
    *,
    block_new_entries=True,
    close_all=True,
    wait_candles_m5=3,
    strategy_override="",
    max_spread_points=0,
    risk_multiplier=0.5,
) -> NewsSkill:
    return NewsSkill(
        name="nfp",
        activation=NewsActivation(
            calendar_events=("Non-Farm Payrolls",),
            window=NewsActivationWindow(before_min=30, after_min=60),
            symbols=("XAUUSD",),
        ),
        pre_event=PreEventRules(close_all=close_all, block_new_entries=block_new_entries),
        post_event=PostEventRules(
            wait_candles_m5=wait_candles_m5,
            strategy_override=strategy_override,
            max_spread_points=max_spread_points,
            risk_multiplier=risk_multiplier,
        ),
    )


def test_no_active_window_falls_through_to_normal():
    normal_decision = SkillDecision(
        allowed=True, skill_name="normal/xauusd", strategy_name="breakout_v1"
    )
    normal = FakeNormalSelector(normal_decision)
    selector = NewsSkillSelector(normal, {}, FakeWindowSource(None))

    decision = selector.select("XAUUSD", EVENT_TIME)

    assert decision is normal_decision
    assert normal.calls == [("XAUUSD", EVENT_TIME)]


def test_pre_event_blocks_new_entries_when_configured():
    window = make_window()
    skill = make_skill(block_new_entries=True)
    normal = FakeNormalSelector(SkillDecision(allowed=True, strategy_name="breakout_v1"))
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME - timedelta(minutes=10))

    assert not decision.allowed
    assert decision.skill_name == "nfp"
    assert "pre-event block" in decision.reason
    assert normal.calls == []  # never consulted once blocked


def test_pre_event_falls_through_when_not_blocking():
    window = make_window()
    skill = make_skill(block_new_entries=False)
    normal_decision = SkillDecision(allowed=True, strategy_name="breakout_v1")
    normal = FakeNormalSelector(normal_decision)
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME - timedelta(minutes=10))

    assert decision is normal_decision


def test_post_event_blocks_during_wait_candles_cooldown():
    window = make_window()
    skill = make_skill(wait_candles_m5=3)  # 15 minute cooldown
    normal = FakeNormalSelector(SkillDecision(allowed=True, strategy_name="breakout_v1"))
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME + timedelta(minutes=10))

    assert not decision.allowed
    assert "cooldown" in decision.reason
    assert normal.calls == []


def test_post_event_after_cooldown_uses_strategy_override():
    window = make_window()
    skill = make_skill(wait_candles_m5=3, strategy_override="news_breakout", max_spread_points=80)
    normal = FakeNormalSelector(SkillDecision(allowed=True, strategy_name="breakout_v1"))
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME + timedelta(minutes=16))

    assert decision.allowed
    assert decision.strategy_name == "news_breakout"
    assert decision.risk_multiplier == 0.5
    assert decision.max_spread_points == 80
    assert normal.calls == []  # override never needs the normal skill


def test_post_event_after_cooldown_without_override_falls_back_to_normal_strategy():
    window = make_window()
    skill = make_skill(wait_candles_m5=0, strategy_override="", max_spread_points=80)
    normal = FakeNormalSelector(SkillDecision(allowed=True, strategy_name="breakout_v1"))
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME + timedelta(minutes=1))

    assert decision.allowed
    assert decision.strategy_name == "breakout_v1"  # from the normal skill
    assert decision.risk_multiplier == 0.5  # from the news skill's post_event rules
    assert decision.max_spread_points == 80


def test_post_event_returns_normal_blocked_decision_when_no_override():
    window = make_window()
    skill = make_skill(wait_candles_m5=0, strategy_override="")
    blocked = SkillDecision(allowed=False, reason="outside trading session")
    normal = FakeNormalSelector(blocked)
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME + timedelta(minutes=1))

    assert decision is blocked


def test_zero_max_spread_points_means_no_override():
    window = make_window()
    skill = make_skill(wait_candles_m5=0, strategy_override="news_breakout", max_spread_points=0)
    normal = FakeNormalSelector(SkillDecision(allowed=True, strategy_name="breakout_v1"))
    selector = NewsSkillSelector(normal, {"nfp": skill}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME + timedelta(minutes=1))

    assert decision.max_spread_points is None


def test_unregistered_skill_falls_through_to_normal():
    window = make_window(skill="unknown")
    normal_decision = SkillDecision(allowed=True, strategy_name="breakout_v1")
    normal = FakeNormalSelector(normal_decision)
    selector = NewsSkillSelector(normal, {}, FakeWindowSource(window))

    decision = selector.select("XAUUSD", EVENT_TIME)

    assert decision is normal_decision
