"""Symbol -> bots routing endpoints (§6.6) — GET lists every bot on every
symbol, POST activates a new bot, PUT reassigns one bot's strategy, DELETE
stops one bot. A symbol may have several bots active at once."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.broker.application.spread_gate import SpreadGate
from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.domain.models import Timeframe
from src.shared.events.bus import EventBus
from src.skills.adapters.normal_skill_repository import NormalSkillRepository
from src.skills.api.routes import router
from src.skills.application.skill_assignment import SkillAssignmentService
from src.skills.application.skill_selector import SkillSelector
from src.strategies.domain.models import StrategySpec
from src.strategies.registry import StrategyRegistry


class FakeStrategy:
    def __init__(self, params: dict | None = None, htf_veto: bool = True) -> None:
        self.spec = StrategySpec(
            name="fake",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params=params if params is not None else {"lookback": 20, "use_filter": False},
            htf_veto=htf_veto,
        )

    def evaluate(self, ctx):
        return None


class FakeMarketData:
    async def get_candles(self, symbol, timeframe, count):
        return []


class FakeRepository:
    def upsert_many(self, candles):
        return 0


class FakeBroadcaster:
    async def broadcast(self, message):
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


def _write_skill_yaml(skills_dir, symbol: str, bot_slug: str, strategy: str) -> None:
    symbol_dir = skills_dir / symbol.lower()
    symbol_dir.mkdir(parents=True, exist_ok=True)
    (symbol_dir / f"{bot_slug}.yaml").write_text(
        f"name: normal/{symbol.lower()}/{bot_slug}\nsymbol: {symbol}\nstrategy: {strategy}\n"
    )


def _write_app_config(configs_dir, symbols: list[str]) -> None:
    configs_dir.mkdir(parents=True, exist_ok=True)
    symbols_literal = ", ".join(f'"{s}"' if " " in s else s for s in symbols)
    (configs_dir / "app.yaml").write_text(
        "mode: live              # paper | live  — NEVER switch to live before Phase 9 criteria\n"
        f"symbols: [{symbols_literal}]\n"
    )


@pytest.fixture
async def api(tmp_path):
    configs_dir = tmp_path / "configs"
    skills_dir = tmp_path / "skills"
    _write_symbol_config(configs_dir, "XAUUSD")
    _write_app_config(configs_dir, ["XAUUSD"])
    _write_skill_yaml(skills_dir, "XAUUSD", "breakout_v1", "breakout_v1")

    repository = NormalSkillRepository(skills_dir)
    selector = SkillSelector(repository.load_all(["XAUUSD"]), timezone="UTC")
    registry = StrategyRegistry()
    registry.register("breakout_v1", FakeStrategy())
    registry.register("gold_ema_pullback", FakeStrategy())
    registry.register("mean_reversion_v1", FakeStrategy())
    candle_stream = CandleStreamService(
        market_data=FakeMarketData(),
        repository=FakeRepository(),
        event_bus=EventBus(),
        broadcaster=FakeBroadcaster(),
        symbols=["XAUUSD"],
        timeframes=[Timeframe.M5],
    )
    spread_gate = SpreadGate({})
    service = SkillAssignmentService(
        repository=repository,
        selector=selector,
        strategy_registry=registry,
        candle_stream=candle_stream,
        spread_gate=spread_gate,
        configs_dir=configs_dir,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(skill_assignment=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        # Attached for the tests that need to activate a brand-new symbol or
        # bot mid-test (register its strategy, write its symbol config).
        client.configs_dir = configs_dir
        client.registry = registry
        yield client


async def test_list_normal_skills(api):
    response = await api.get("/skills/normal")
    assert response.status_code == 200
    (body,) = response.json()
    assert body["symbol"] == "XAUUSD"
    assert body["strategy"] == "breakout_v1"
    assert body["bot_name"] == "breakout_v1"
    assert body["newly_activated"] is False
    assert body["param_overrides"] == {}
    assert body["htf_veto_override"] is None
    assert body["strategy_default_params"] == {"lookback": 20, "use_filter": False}
    assert body["strategy_default_htf_veto"] is True


async def test_list_normal_skills_excludes_non_scalar_strategy_params(api):
    # Regression: some real strategies (e.g. pob_snd_zones_xauusd) carry a
    # structured param like session_windows: tuple[tuple[int, int], ...] —
    # including it verbatim in strategy_default_params (typed
    # dict[str, float | int | str | bool]) 500s on Pydantic response
    # validation instead of just being skipped.
    api.registry.register(
        "structured_params_strategy",
        FakeStrategy(params={"lookback": 20, "session_windows": ((420, 720), (780, 1020))}),
    )
    response = await api.post(
        "/skills/normal/XAUUSD/bots", json={"strategy_name": "structured_params_strategy"}
    )
    assert response.status_code == 200
    assert response.json()["strategy_default_params"] == {"lookback": 20}

    listing = await api.get("/skills/normal")
    assert listing.status_code == 200
    body = next(s for s in listing.json() if s["strategy"] == "structured_params_strategy")
    assert body["strategy_default_params"] == {"lookback": 20}


async def test_add_bot_alongside_existing_bot(api):
    response = await api.post(
        "/skills/normal/XAUUSD/bots", json={"strategy_name": "mean_reversion_v1"}
    )
    assert response.status_code == 200
    assert response.json()["strategy"] == "mean_reversion_v1"
    assert response.json()["bot_name"] == "mean_reversion_v1"
    # XAUUSD was already live — adding a second bot isn't a new activation.
    assert response.json()["newly_activated"] is False

    listing = await api.get("/skills/normal")
    assert sorted(s["strategy"] for s in listing.json()) == ["breakout_v1", "mean_reversion_v1"]


async def test_add_bot_unknown_symbol_404s(api):
    response = await api.post(
        "/skills/normal/EURUSD/bots", json={"strategy_name": "gold_ema_pullback"}
    )
    assert response.status_code == 404


async def test_add_bot_unknown_strategy_422s(api):
    response = await api.post(
        "/skills/normal/XAUUSD/bots", json={"strategy_name": "does_not_exist"}
    )
    assert response.status_code == 422


async def test_add_bot_duplicate_name_409s(api):
    response = await api.post(
        "/skills/normal/XAUUSD/bots",
        json={"strategy_name": "gold_ema_pullback", "bot_name": "breakout_v1"},
    )
    assert response.status_code == 409


async def test_update_bot_succeeds(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1", json={"strategy_name": "gold_ema_pullback"}
    )
    assert response.status_code == 200
    assert response.json()["strategy"] == "gold_ema_pullback"


async def test_update_bot_unknown_bot_404s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/does_not_exist", json={"strategy_name": "gold_ema_pullback"}
    )
    assert response.status_code == 404


async def test_update_bot_unknown_strategy_422s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1", json={"strategy_name": "does_not_exist"}
    )
    assert response.status_code == 422


async def test_remove_bot_succeeds(api):
    response = await api.delete("/skills/normal/XAUUSD/bots/breakout_v1")
    assert response.status_code == 204

    listing = await api.get("/skills/normal")
    assert listing.json() == []


async def test_remove_bot_unknown_bot_404s(api):
    response = await api.delete("/skills/normal/XAUUSD/bots/does_not_exist")
    assert response.status_code == 404


async def test_add_bot_to_new_symbol_activates_it_and_reports_it(api):
    # This is the actual "Apply to <symbol>" flow for a symbol not yet
    # configured for live trading — must show up as newly_activated and be
    # visible in GET /skills/normal immediately after, no restart.
    _write_symbol_config(api.configs_dir, "Volatility 75 Index")
    api.registry.register("pob_price_action_snd_for_vix75", FakeStrategy())

    response = await api.post(
        "/skills/normal/Volatility%2075%20Index/bots",
        json={"strategy_name": "pob_price_action_snd_for_vix75"},
    )

    assert response.status_code == 200
    assert response.json()["newly_activated"] is True

    listing = await api.get("/skills/normal")
    assert "Volatility 75 Index" in [s["symbol"] for s in listing.json()]


async def test_update_bot_config_succeeds(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1/config",
        json={
            "risk_multiplier": 1.5,
            "sessions": [{"start": "08:00", "end": "10:00"}],
            "param_overrides": {"lookback": 30},
            "htf_veto_override": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_multiplier"] == 1.5
    assert body["sessions"] == [{"start": "08:00", "end": "10:00"}]
    assert body["param_overrides"] == {"lookback": 30}
    assert body["htf_veto_override"] is False


async def test_update_bot_config_unknown_bot_404s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/does_not_exist/config",
        json={"risk_multiplier": 1.0, "sessions": [], "param_overrides": {}},
    )
    assert response.status_code == 404


async def test_update_bot_config_unknown_param_422s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1/config",
        json={
            "risk_multiplier": 1.0,
            "sessions": [],
            "param_overrides": {"not_a_real_param": 1},
        },
    )
    assert response.status_code == 422


async def test_update_bot_config_wrong_type_422s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1/config",
        json={
            "risk_multiplier": 1.0,
            "sessions": [],
            "param_overrides": {"lookback": "thirty"},
        },
    )
    assert response.status_code == 422


async def test_update_bot_config_invalid_session_422s(api):
    response = await api.put(
        "/skills/normal/XAUUSD/bots/breakout_v1/config",
        json={
            "risk_multiplier": 1.0,
            "sessions": [{"start": "not-a-time", "end": "12:00"}],
            "param_overrides": {},
        },
    )
    assert response.status_code == 422
