"""Symbol -> strategy routing (§6.6): reassigning a symbol must persist to
disk, take effect in the live SkillSelector immediately, and refuse to route
to a symbol or strategy family that doesn't actually exist/isn't live."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.skills.adapters.normal_skill_repository import NormalSkillRepository
from src.skills.application.skill_assignment import (
    SkillAssignmentService,
    UnknownStrategyError,
    UnknownSymbolError,
)
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill, SessionWindow
from src.strategies.registry import StrategyRegistry


class FakeStrategy:
    pass


def _write_symbol_config(configs_dir: Path, symbol: str) -> None:
    (configs_dir / "symbols").mkdir(parents=True, exist_ok=True)
    (configs_dir / "symbols" / f"{symbol.lower()}.yaml").write_text(
        f"symbol: {symbol}\n"
        "max_spread_points: 35\n"
        "min_rr: 1.5\n"
        "contract_size: 100\n"
        "point: 0.01\n"
        "digits: 2\n"
        "stops_level: 0\n"
        "volume_min: 0.01\n"
        "volume_max: 50\n"
        "volume_step: 0.01\n"
    )


def _write_skill_yaml(skills_dir: Path, symbol: str, strategy: str) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / f"{symbol.lower()}.yaml").write_text(
        f"name: normal/{symbol.lower()}\n"
        f"symbol: {symbol}\n"
        f"strategy: {strategy}\n"
        "risk_multiplier: 0.8\n"
        'sessions:\n  - { start: "09:00", end: "12:00" }\n'
    )


@pytest.fixture
def setup(tmp_path):
    configs_dir = tmp_path / "configs"
    skills_dir = tmp_path / "skills" / "normal"
    _write_symbol_config(configs_dir, "XAUUSD")
    _write_skill_yaml(skills_dir, "XAUUSD", "breakout_v1")

    repository = NormalSkillRepository(skills_dir)
    selector = SkillSelector(repository.load_all(["XAUUSD"]), timezone="UTC")
    registry = StrategyRegistry()
    registry.register("breakout_v1", FakeStrategy())
    registry.register("gold_ema_pullback", FakeStrategy())
    service = SkillAssignmentService(
        repository=repository,
        selector=selector,
        strategy_registry=registry,
        symbols=["XAUUSD"],
        configs_dir=configs_dir,
    )
    return service, repository, selector, skills_dir


def test_assign_persists_and_hot_swaps(setup):
    service, repository, selector, skills_dir = setup

    skill = service.assign("XAUUSD", "gold_ema_pullback")

    assert skill.strategy == "gold_ema_pullback"
    # Existing sessions/risk_multiplier/name are preserved, not reset.
    assert skill.risk_multiplier == 0.8
    assert skill.sessions == (SessionWindow.parse("09:00", "12:00"),)
    assert skill.name == "normal/xauusd"

    # Persisted to disk.
    on_disk = repository.get("XAUUSD")
    assert on_disk.strategy == "gold_ema_pullback"

    # Live selector reflects the change without any restart — strategy_name
    # is populated whether or not "now" falls inside a session window.
    decision = selector.select("XAUUSD")
    assert decision.strategy_name == "gold_ema_pullback"


def test_assign_unknown_symbol_rejected(setup):
    service, *_ = setup
    with pytest.raises(UnknownSymbolError):
        service.assign("EURUSD", "gold_ema_pullback")


def test_assign_unknown_strategy_rejected(setup):
    service, *_ = setup
    with pytest.raises(UnknownStrategyError):
        service.assign("XAUUSD", "does_not_exist")


def test_assign_paused_strategy_rejected(setup):
    service, _repository, _selector, _skills_dir = setup
    registry: StrategyRegistry = service._strategy_registry
    registry.pause("gold_ema_pullback")
    with pytest.raises(UnknownStrategyError):
        service.assign("XAUUSD", "gold_ema_pullback")


def test_list_assignments_returns_one_per_symbol(setup):
    service, *_ = setup
    assignments = service.list_assignments()
    assert [a.symbol for a in assignments] == ["XAUUSD"]


def test_normal_skill_repository_save_round_trips(tmp_path):
    skills_dir = tmp_path / "skills"
    repository = NormalSkillRepository(skills_dir)
    skill = NormalSkill(
        name="normal/eurusd",
        symbol="EURUSD",
        strategy="breakout_v1",
        risk_multiplier=1.2,
        sessions=(SessionWindow.parse("08:00", "17:00"),),
    )
    repository.save(skill)

    loaded = repository.get("EURUSD")
    assert loaded == skill


def test_normal_skill_repository_get_missing_returns_none(tmp_path):
    repository = NormalSkillRepository(tmp_path / "skills")
    assert repository.get("EURUSD") is None
