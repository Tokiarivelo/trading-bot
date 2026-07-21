from datetime import UTC, datetime

from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill, SessionWindow, magic_number


def make_skill(
    sessions: tuple[SessionWindow, ...] = (), name: str = "normal/xauusd/breakout_v1"
) -> NormalSkill:
    return NormalSkill(
        name=name,
        symbol="XAUUSD",
        strategy="breakout_v1",
        risk_multiplier=0.8,
        sessions=sessions,
    )


def test_selects_allowed_skill_within_session():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": [skill]}, timezone="UTC")
    (decision,) = selector.select_all("XAUUSD", datetime(2026, 7, 11, 10, 0, tzinfo=UTC))

    assert decision.allowed
    assert decision.strategy_name == "breakout_v1"
    assert decision.risk_multiplier == 0.8
    assert decision.skill_name == "normal/xauusd/breakout_v1"
    assert decision.magic == magic_number("XAUUSD", "normal/xauusd/breakout_v1")


def test_blocks_outside_session():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": [skill]}, timezone="UTC")
    (decision,) = selector.select_all("XAUUSD", datetime(2026, 7, 11, 20, 0, tzinfo=UTC))

    assert not decision.allowed
    assert "session" in decision.reason


def test_no_sessions_means_always_active():
    skill = make_skill(sessions=())
    selector = SkillSelector({"XAUUSD": [skill]}, timezone="UTC")
    (decision,) = selector.select_all("XAUUSD", datetime(2026, 7, 11, 3, 0, tzinfo=UTC))

    assert decision.allowed


def test_no_skill_configured_returns_empty():
    selector = SkillSelector({}, timezone="UTC")
    decisions = selector.select_all("BTCUSD", datetime.now(UTC))

    assert decisions == []


def test_timezone_conversion_applied():
    skill = make_skill(sessions=(SessionWindow.parse("09:00", "12:00"),))
    selector = SkillSelector({"XAUUSD": [skill]}, timezone="America/New_York")
    # 14:00 UTC == 10:00 New York in July (EDT, UTC-4) -> inside the session.
    (decision,) = selector.select_all("XAUUSD", datetime(2026, 7, 11, 14, 0, tzinfo=UTC))

    assert decision.allowed


def test_multiple_bots_on_one_symbol_each_get_their_own_decision():
    breakout = make_skill(name="normal/xauusd/breakout_v1")
    reversion = NormalSkill(
        name="normal/xauusd/mean_reversion",
        symbol="XAUUSD",
        strategy="mean_reversion_v1",
        risk_multiplier=1.0,
        sessions=(),
    )
    selector = SkillSelector({"XAUUSD": [breakout, reversion]}, timezone="UTC")

    decisions = selector.select_all("XAUUSD", datetime.now(UTC))

    assert {d.skill_name for d in decisions} == {
        "normal/xauusd/breakout_v1",
        "normal/xauusd/mean_reversion",
    }
    assert {d.strategy_name for d in decisions} == {"breakout_v1", "mean_reversion_v1"}
    # Distinct magic numbers so the broker can tell the two bots' positions apart.
    magics = {d.magic for d in decisions}
    assert len(magics) == 2


def test_decision_carries_param_and_htf_veto_overrides():
    skill = NormalSkill(
        name="normal/xauusd/breakout_v1",
        symbol="XAUUSD",
        strategy="breakout_v1",
        risk_multiplier=1.0,
        sessions=(),
        param_overrides={"lookback": 30},
        htf_veto_override=False,
    )
    selector = SkillSelector({"XAUUSD": [skill]}, timezone="UTC")

    (decision,) = selector.select_all("XAUUSD", datetime.now(UTC))

    assert decision.param_overrides == {"lookback": 30}
    assert decision.htf_veto_override is False


def test_add_hot_swaps_a_new_bot():
    selector = SkillSelector({}, timezone="UTC")
    skill = make_skill()

    selector.set(skill)

    (decision,) = selector.select_all("XAUUSD", datetime.now(UTC))
    assert decision.strategy_name == "breakout_v1"


def test_set_replaces_existing_bot_by_slug():
    selector = SkillSelector({"XAUUSD": [make_skill()]}, timezone="UTC")
    replacement = NormalSkill(
        name="normal/xauusd/breakout_v1",
        symbol="XAUUSD",
        strategy="gold_ema_pullback",
        risk_multiplier=1.0,
        sessions=(),
    )

    selector.set(replacement)

    (decision,) = selector.select_all("XAUUSD", datetime.now(UTC))
    assert decision.strategy_name == "gold_ema_pullback"


def test_remove_drops_one_bot_without_affecting_others():
    breakout = make_skill(name="normal/xauusd/breakout_v1")
    reversion = NormalSkill(
        name="normal/xauusd/mean_reversion",
        symbol="XAUUSD",
        strategy="mean_reversion_v1",
        risk_multiplier=1.0,
        sessions=(),
    )
    selector = SkillSelector({"XAUUSD": [breakout, reversion]}, timezone="UTC")

    selector.remove("XAUUSD", "breakout_v1")

    (decision,) = selector.select_all("XAUUSD", datetime.now(UTC))
    assert decision.strategy_name == "mean_reversion_v1"
