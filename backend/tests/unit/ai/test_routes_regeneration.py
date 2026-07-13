"""User-triggered AI code regeneration endpoint (§6.5 code editor) — wired
through a real `CodeRegenerationService` with a fake LLM router so no
network call happens in tests."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.api.routes_regeneration import router
from src.ai.application.code_regeneration import CodeRegenerationService
from src.ai.application.llm_router import LLMProviderNotConfiguredError
from src.ai.ports.llm import LLMCallError
from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.domain.versioning import CodeSource
from src.strategies.registry import StrategyRegistry

VALID_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class Sample:
    def __init__(self):
        self.spec = StrategySpec(
            name="sample", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""

REGENERATED_CODE = VALID_CODE + "\n# regenerated\n"


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, message, *, max_tokens=4096):
        return self.response


class FailingLLM:
    async def complete(self, message, *, max_tokens=4096):
        raise LLMCallError("provider call failed")


class UnconfiguredRouter:
    def for_task(self, task: str):
        raise LLMProviderNotConfiguredError("no key set")


class FakeRouter:
    def __init__(self, code: str = REGENERATED_CODE) -> None:
        self._llm = FakeLLM(f"```python\n{code}\n```")

    def for_task(self, task: str):
        assert task == "code_generation"
        return self._llm


@pytest.fixture
def strategy_versions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    return StrategyVersionService(
        StrategyVersionRepository(session_factory), StrategyRegistry(), generated_dir
    )


def _api(strategy_versions, llm_router):
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        code_regeneration=CodeRegenerationService(strategy_versions, llm_router)
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://backend")


async def test_regenerate_version_code(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "only trade during the London session"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is True
    assert body["new_version_id"] is not None
    assert body["code"] == REGENERATED_CODE.strip()


async def test_regenerate_version_code_invalid_returns_valid_false(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, FakeRouter(code="import os\nx = 1\n")) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "add an os import"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["new_version_id"] is None
    assert body["sandbox_errors"]


async def test_regenerate_version_code_not_found(strategy_versions):
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            "/ai/strategies/versions/does-not-exist/regenerate",
            json={"instructions": "tighten the stop loss"},
        )
    assert response.status_code == 404


async def test_regenerate_version_code_llm_call_error_returns_504(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )

    class FailingRouter:
        def for_task(self, task: str):
            return FailingLLM()

    async with _api(strategy_versions, FailingRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "tighten the stop loss"},
        )
    assert response.status_code == 504


async def test_regenerate_version_code_provider_not_configured_returns_503(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, UnconfiguredRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "tighten the stop loss"},
        )
    assert response.status_code == 503


async def test_regenerate_version_code_blank_instructions_rejected(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate", json={"instructions": ""}
        )
    assert response.status_code == 422


SPEC_OVERRIDE = {
    "name": "sample",
    "symbols": ["XAUUSD"],
    "entry_timeframe": "M5",
    "confirmation_timeframes": [],
    "indicators": [],
    "entry_rules": "edited entry rule",
    "exit_rules": "",
    "risk_notes": "",
}


async def test_regenerate_version_code_with_spec_override(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "tighten the stop loss", "spec": SPEC_OVERRIDE},
        )
    assert response.status_code == 200
    new_version_id = response.json()["new_version_id"]
    new_version = strategy_versions.get_version(new_version_id)
    assert new_version.spec["entry_rules"] == "edited entry rule"


async def test_regenerate_version_code_with_new_name_forks(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "tighten the stop loss", "new_name": "sample_fork"},
        )
    assert response.status_code == 200
    new_version_id = response.json()["new_version_id"]
    new_version = strategy_versions.get_version(new_version_id)
    assert new_version.name == "sample_fork"
    assert new_version.version == 1
    assert new_version.parent_version_id is None


async def test_regenerate_version_code_new_name_conflict_returns_409(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    strategy_versions.save_generated_code(
        name="other", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    async with _api(strategy_versions, FakeRouter()) as api:
        response = await api.post(
            f"/ai/strategies/versions/{v1.id}/regenerate",
            json={"instructions": "tighten the stop loss", "new_name": "other"},
        )
    assert response.status_code == 409
