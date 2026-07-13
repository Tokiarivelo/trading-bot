"""Symbol -> strategy routing endpoints (§6.6) — GET lists the current
assignments, PUT is the real "apply a bot to a symbol" action."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.skills.adapters.normal_skill_repository import NormalSkillRepository
from src.skills.api.routes import router
from src.skills.application.skill_assignment import SkillAssignmentService
from src.skills.application.skill_selector import SkillSelector
from src.strategies.registry import StrategyRegistry


class FakeStrategy:
    pass


def _write_symbol_config(configs_dir, symbol: str) -> None:
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


def _write_skill_yaml(skills_dir, symbol: str, strategy: str) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / f"{symbol.lower()}.yaml").write_text(
        f"name: normal/{symbol.lower()}\nsymbol: {symbol}\nstrategy: {strategy}\n"
    )


@pytest.fixture
async def api(tmp_path):
    configs_dir = tmp_path / "configs"
    skills_dir = tmp_path / "skills"
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

    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(skill_assignment=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


async def test_list_normal_skills(api):
    response = await api.get("/skills/normal")
    assert response.status_code == 200
    (body,) = response.json()
    assert body["symbol"] == "XAUUSD"
    assert body["strategy"] == "breakout_v1"


async def test_assign_strategy_succeeds(api):
    response = await api.put(
        "/skills/normal/XAUUSD", json={"strategy_name": "gold_ema_pullback"}
    )
    assert response.status_code == 200
    assert response.json()["strategy"] == "gold_ema_pullback"


async def test_assign_strategy_unknown_symbol_404s(api):
    response = await api.put(
        "/skills/normal/EURUSD", json={"strategy_name": "gold_ema_pullback"}
    )
    assert response.status_code == 404


async def test_assign_strategy_unknown_strategy_422s(api):
    response = await api.put("/skills/normal/XAUUSD", json={"strategy_name": "does_not_exist"})
    assert response.status_code == 422
