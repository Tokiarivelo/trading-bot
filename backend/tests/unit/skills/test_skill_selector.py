from datetime import UTC, datetime

from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill, SessionWindow


def make_skill(sessions: tuple[SessionWindow, ...] = ()) -> NormalSkill:
    return NormalSkill(
        name="normal/xauusd",
        symbol="XAUUSD",
        strategy="breakout_v1",
        risk_multiplier=0.8,
        sessions=sessions,
    )


def test_selects_allowed_skill_within_session():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": skill}, timezone="UTC")
    decision = selector.select("XAUUSD", datetime(2026, 7, 11, 10, 0, tzinfo=UTC))

    assert decision.allowed
    assert decision.strategy_name == "breakout_v1"
    assert decision.risk_multiplier == 0.8
    assert decision.skill_name == "normal/xauusd"


def test_blocks_outside_session():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": skill}, timezone="UTC")
    decision = selector.select("XAUUSD", datetime(2026, 7, 11, 20, 0, tzinfo=UTC))

    assert not decision.allowed
    assert "session" in decision.reason


def test_no_sessions_means_always_active():
    skill = make_skill(sessions=())
    selector = SkillSelector({"XAUUSD": skill}, timezone="UTC")
    decision = selector.select("XAUUSD", datetime(2026, 7, 11, 3, 0, tzinfo=UTC))

    assert decision.allowed


def test_no_skill_configured_blocks():
    selector = SkillSelector({}, timezone="UTC")
    decision = selector.select("BTCUSD", datetime.now(UTC))

    assert not decision.allowed
    assert "no skill" in decision.reason


def test_timezone_conversion_applied():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": skill}, timezone="America/New_York")
    # 14:00 UTC == 10:00 New York in July (EDT, UTC-4) -> inside the session.
    decision = selector.select("XAUUSD", datetime(2026, 7, 11, 14, 0, tzinfo=UTC))

    assert decision.allowed
