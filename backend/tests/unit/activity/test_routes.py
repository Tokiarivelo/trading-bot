"""GET /activity/history — filtered, paginated activity log."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.activity.adapters.repository import ActivityLogRepository
from src.activity.api.routes import router
from src.activity.application.activity_log_service import ActivityLogService
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> ActivityLogRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return ActivityLogRepository(sessionmaker(bind=engine, expire_on_commit=False))


@pytest.fixture
async def api(repository):
    service = ActivityLogService(repository)
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(activity_log=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


@pytest.fixture(autouse=True)
def _seed(repository):
    repository.save(
        created_at=100,
        level="INFO",
        logger="src.engine.application.trade_loop",
        message="signal: XAUUSD buy strategy=breakout_v1 reason=breakout",
    )
    repository.save(
        created_at=200,
        level="WARNING",
        logger="src.broker.application.order_service",
        message="signal vetoed: buy XAUUSD spread=40pts reason=spread too wide",
    )
    repository.save(
        created_at=300,
        level="INFO",
        logger="src.engine.application.risk_manager",
        message="engine resumed by operator",
    )


async def test_returns_all_entries_with_total(api):
    response = await api.get("/activity/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [e["created_at"] for e in body["items"]] == [300, 200, 100]  # newest first


async def test_filters_by_level(api):
    response = await api.get("/activity/history", params={"level": "WARNING"})
    body = response.json()
    assert body["total"] == 1
    assert "spread too wide" in body["items"][0]["message"]


async def test_filters_by_logger_substring(api):
    response = await api.get("/activity/history", params={"logger_contains": "risk_manager"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["message"] == "engine resumed by operator"


async def test_filters_by_message_text(api):
    response = await api.get("/activity/history", params={"q": "XAUUSD"})
    body = response.json()
    assert body["total"] == 2


async def test_pagination_limit_offset(api):
    response = await api.get("/activity/history", params={"limit": 1, "offset": 1})
    body = response.json()
    assert body["total"] == 3
    assert body["items"][0]["created_at"] == 200


async def test_delete_by_ids_removes_only_given_rows(api):
    history = await api.get("/activity/history")
    target_id = next(
        e["id"] for e in history.json()["items"] if e["message"] == "engine resumed by operator"
    )

    response = await api.post("/activity/history/delete-by-ids", json={"ids": [target_id]})

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    remaining = await api.get("/activity/history")
    assert remaining.json()["total"] == 2


async def test_delete_by_ids_requires_at_least_one_id(api):
    response = await api.post("/activity/history/delete-by-ids", json={"ids": []})
    assert response.status_code == 422


async def test_delete_by_filter_removes_matching_rows_only(api):
    response = await api.post("/activity/history/delete-by-filter", json={"level": "WARNING"})

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    remaining = await api.get("/activity/history")
    assert remaining.json()["total"] == 2


async def test_delete_by_filter_with_no_body_fields_deletes_everything(api):
    response = await api.post("/activity/history/delete-by-filter", json={})

    assert response.status_code == 200
    assert response.json() == {"deleted": 3}
    remaining = await api.get("/activity/history")
    assert remaining.json()["total"] == 0
