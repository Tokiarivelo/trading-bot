"""Symbol -> strategy routing (§6.6): reassigning a symbol must persist to
disk, take effect in the live SkillSelector immediately, and refuse to route
to a symbol or strategy family that doesn't actually exist/isn't live. A
symbol not yet in configs/app.yaml must be durably and immediately activated
for live trading — the real "Apply" action, not just a routing reassignment
(§ dynamic symbol activation)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.broker.application.spread_gate import SpreadGate
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.domain.models import Timeframe
from src.shared.events.bus import EventBus
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


class FakeMarketData:
    async def get_candles(self, symbol, timeframe, count):
        return []


class FakeRepository:
    def upsert_many(self, candles):
        return 0


class FakeBroadcaster:
    async def broadcast(self, message):
        pass


def _make_candle_stream(symbols: list[str]) -> CandleStreamService:
    return CandleStreamService(
        market_data=FakeMarketData(),
        repository=FakeRepository(),
        event_bus=EventBus(),
        broadcaster=FakeBroadcaster(),
        symbols=symbols,
        timeframes=[Timeframe.M5],
    )


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


def _write_app_config(configs_dir: Path, symbols: list[str]) -> None:
    configs_dir.mkdir(parents=True, exist_ok=True)
    symbols_literal = ", ".join(f'"{s}"' if " " in s else s for s in symbols)
    (configs_dir / "app.yaml").write_text(
        "# Global app configuration. Hot-reloadable.\n"
        "mode: live              # paper | live  — NEVER switch to live before Phase 9 criteria\n"
        f"symbols: [{symbols_literal}]\n"
    )


@pytest.fixture
def setup(tmp_path):
    configs_dir = tmp_path / "configs"
    skills_dir = tmp_path / "skills" / "normal"
    _write_symbol_config(configs_dir, "XAUUSD")
    _write_app_config(configs_dir, ["XAUUSD"])
    _write_skill_yaml(skills_dir, "XAUUSD", "breakout_v1")

    repository = NormalSkillRepository(skills_dir)
    selector = SkillSelector(repository.load_all(["XAUUSD"]), timezone="UTC")
    registry = StrategyRegistry()
    registry.register("breakout_v1", FakeStrategy())
    registry.register("gold_ema_pullback", FakeStrategy())
    candle_stream = _make_candle_stream(["XAUUSD"])
    spread_gate = SpreadGate({})
    service = SkillAssignmentService(
        repository=repository,
        selector=selector,
        strategy_registry=registry,
        candle_stream=candle_stream,
        spread_gate=spread_gate,
        configs_dir=configs_dir,
    )
    return service, repository, selector, skills_dir, candle_stream, spread_gate, configs_dir


async def test_assign_persists_and_hot_swaps(setup):
    service, repository, selector, skills_dir, *_ = setup

    result = await service.assign("XAUUSD", "gold_ema_pullback")

    assert result.skill.strategy == "gold_ema_pullback"
    # Existing sessions/risk_multiplier/name are preserved, not reset.
    assert result.skill.risk_multiplier == 0.8
    assert result.skill.sessions == (SessionWindow.parse("09:00", "12:00"),)
    assert result.skill.name == "normal/xauusd"
    # XAUUSD was already live-traded — this is a reroute, not an activation.
    assert result.newly_activated is False

    # Persisted to disk.
    on_disk = repository.get("XAUUSD")
    assert on_disk.strategy == "gold_ema_pullback"

    # Live selector reflects the change without any restart — strategy_name
    # is populated whether or not "now" falls inside a session window.
    decision = selector.select("XAUUSD")
    assert decision.strategy_name == "gold_ema_pullback"


async def test_assign_unknown_symbol_rejected(setup):
    service, *_ = setup
    with pytest.raises(UnknownSymbolError):
        await service.assign("EURUSD", "gold_ema_pullback")


async def test_assign_unknown_strategy_rejected(setup):
    service, *_ = setup
    with pytest.raises(UnknownStrategyError):
        await service.assign("XAUUSD", "does_not_exist")


async def test_assign_paused_strategy_rejected(setup):
    service, *_ = setup
    registry: StrategyRegistry = service._strategy_registry
    registry.pause("gold_ema_pullback")
    with pytest.raises(UnknownStrategyError):
        await service.assign("XAUUSD", "gold_ema_pullback")


async def test_list_assignments_returns_one_per_symbol(setup):
    service, *_ = setup
    assignments = await service.list_assignments()
    assert [a.symbol for a in assignments] == ["XAUUSD"]


async def test_assign_to_new_symbol_activates_it_live(setup):
    # The actual "Apply to <symbol>" flow for a symbol not yet in
    # configs/app.yaml — this must durably and immediately activate it, with
    # no restart, matching what TradeEngine._try_enter and the spread gate
    # need to actually trade it.
    service, repository, selector, skills_dir, candle_stream, spread_gate, configs_dir = setup
    _write_symbol_config(configs_dir, "Volatility 75 Index")
    registry: StrategyRegistry = service._strategy_registry
    registry.register("pob_price_action_snd for vix75", FakeStrategy())

    result = await service.assign("Volatility 75 Index", "pob_price_action_snd for vix75")

    assert result.newly_activated is True
    # Durable: persisted to configs/app.yaml.
    app_config = yaml.safe_load((configs_dir / "app.yaml").read_text())
    assert "Volatility 75 Index" in app_config["symbols"]
    # The load-bearing safety comment survives the write untouched.
    assert "NEVER switch to live" in (configs_dir / "app.yaml").read_text()
    # Immediate: hot-added to candle streaming and the spread gate, no
    # restart needed.
    assert "Volatility 75 Index" in candle_stream.active_symbols
    # The real configs/symbols/volatility 75 index.yaml cap (35pts, per
    # _write_symbol_config) is enforced immediately — not the unconfigured
    # fallback of no cap at all.
    veto = spread_gate.check(
        "Volatility 75 Index", spread_points=40, point=0.01, sl_distance=None, tp_distance=None
    )
    assert veto is not None
    assert "max 35pts" in veto.reason
    # And routed live via the selector, same as any other assignment.
    decision = selector.select("Volatility 75 Index")
    assert decision.allowed is True
    assert decision.strategy_name == "pob_price_action_snd for vix75"
    # And reported by list_assignments() without needing a restart.
    assignments = await service.list_assignments()
    assert "Volatility 75 Index" in [a.symbol for a in assignments]


async def test_assign_to_new_symbol_twice_does_not_duplicate_or_re_report_activation(setup):
    service, _repository, _selector, _skills_dir, _candle_stream, _spread_gate, configs_dir = setup
    _write_symbol_config(configs_dir, "Volatility 75 Index")
    registry: StrategyRegistry = service._strategy_registry
    registry.register("pob_price_action_snd for vix75", FakeStrategy())

    first = await service.assign("Volatility 75 Index", "pob_price_action_snd for vix75")
    second = await service.assign("Volatility 75 Index", "pob_price_action_snd for vix75")

    assert first.newly_activated is True
    assert second.newly_activated is False
    app_config = yaml.safe_load((configs_dir / "app.yaml").read_text())
    assert app_config["symbols"].count("Volatility 75 Index") == 1


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
