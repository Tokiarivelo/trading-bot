"""Strategy version listing/activation endpoints (§6.5, §8.1) — activation
doubles as rollback: activating an older version archives whatever was
active and reactivates that exact file."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.api.routes import router
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


@pytest.fixture
def service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    registry = StrategyRegistry()
    return StrategyVersionService(
        StrategyVersionRepository(session_factory), registry, generated_dir
    ), registry


@pytest.fixture
async def api(service):
    strategy_versions, _ = service
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(strategy_versions=strategy_versions)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


async def test_list_versions_empty(api):
    response = await api.get("/strategies/versions")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_and_get_version(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )

    list_response = await api.get("/strategies/versions")
    assert list_response.status_code == 200
    (summary,) = list_response.json()
    assert summary["id"] == v1.id
    assert summary["status"] == "validated"

    detail_response = await api.get(f"/strategies/versions/{v1.id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["code"] == VALID_CODE


async def test_get_version_not_found(api):
    response = await api.get("/strategies/versions/does-not-exist")
    assert response.status_code == 404


async def test_activate_registers_and_archives_previous(api, service):
    strategy_versions, registry = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    activate_response = await api.post(f"/strategies/versions/{v1.id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"
    assert registry.get("sample") is not None

    v2 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    await api.post(f"/strategies/versions/{v2.id}/activate")

    v1_after = await api.get(f"/strategies/versions/{v1.id}")
    assert v1_after.json()["status"] == "archived"


async def test_activate_is_rollback(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    await api.post(f"/strategies/versions/{v1.id}/activate")
    v2 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    await api.post(f"/strategies/versions/{v2.id}/activate")

    rollback_response = await api.post(f"/strategies/versions/{v1.id}/activate")
    assert rollback_response.status_code == 200
    assert rollback_response.json()["status"] == "active"


async def test_activate_not_found(api):
    response = await api.post("/strategies/versions/does-not-exist/activate")
    assert response.status_code == 404


async def test_duplicate_version(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    response = await api.post(
        f"/strategies/versions/{v1.id}/duplicate", json={"name": "sample_fork"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "sample_fork"
    assert body["version"] == 1
    assert body["parent_version_id"] is None


async def test_duplicate_version_name_conflict(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    response = await api.post(f"/strategies/versions/{v1.id}/duplicate", json={"name": "sample"})
    assert response.status_code == 409


async def test_duplicate_version_not_found(api):
    response = await api.post(
        "/strategies/versions/does-not-exist/duplicate", json={"name": "sample_fork"}
    )
    assert response.status_code == 404


async def test_rename_version(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    response = await api.patch(
        f"/strategies/versions/{v1.id}/rename", json={"name": "renamed_sample"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "renamed_sample"

    listed = await api.get("/strategies/versions")
    (summary,) = listed.json()
    assert summary["name"] == "renamed_sample"


async def test_rename_version_name_conflict(api, service):
    strategy_versions, _ = service
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    strategy_versions.save_generated_code(
        name="other", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    response = await api.patch(f"/strategies/versions/{v1.id}/rename", json={"name": "other"})
    assert response.status_code == 409


async def test_rename_version_not_found(api):
    response = await api.patch(
        "/strategies/versions/does-not-exist/rename", json={"name": "renamed"}
    )
    assert response.status_code == 404
