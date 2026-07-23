"""PDF -> StrategySpec API endpoints (§8.1) — every step human-gated, wired
through a real `PdfToStrategyService` with a fake LLM router so no network
call happens in tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import fitz
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.adapters.repository import DraftRepository
from src.ai.api.routes import router
from src.ai.application.pdf_to_strategy import PdfToStrategyService
from src.ai.ports.llm import LLMCallError
from src.market_data.adapters import orm as market_data_orm  # noqa: F401
from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.registry import StrategyRegistry

EXTRACTED_SPEC = {
    "name": "gold_ema_pullback",
    "symbols": ["XAUUSD"],
    "entry_timeframe": "M5",
    "confirmation_timeframes": ["H1"],
    "indicators": ["EMA200"],
    "entry_rules": "Buy pullbacks to EMA200 in an uptrend.",
    "exit_rules": "SL below swing low, TP at 2R.",
    "risk_notes": "0.5% risk per trade.",
    "params": {"ema_period": 200},
}

VALID_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class GoldEmaPullback:
    def __init__(self):
        self.spec = StrategySpec(
            name="gold_ema_pullback", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=("H1",), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""

INVALID_CODE = "import os\nx = 1\n"


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, message, *, max_tokens=4096):
        return self.response


class FailingLLM:
    """Simulates a provider call that fails outright, e.g. the claude_code
    adapter's subprocess timing out (backend/src/ai/adapters/claude_code.py)."""

    async def complete(self, message, *, max_tokens=4096):
        raise LLMCallError("claude code call exceeded 480s timeout and was killed")


class FakeRouter:
    def __init__(self, code: str = VALID_CODE, codegen=None) -> None:
        self._extraction = FakeLLM(json.dumps(EXTRACTED_SPEC))
        self._codegen = codegen or FakeLLM(code)

    def for_task(self, task: str):
        return {"pdf_extraction": self._extraction, "code_generation": self._codegen}[task]


def _fake_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Buy EMA200 pullbacks in an uptrend on M5.")
    data = doc.tobytes()
    doc.close()
    return data


def _build_service(tmp_path, code: str = VALID_CODE, codegen=None) -> PdfToStrategyService:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()

    candles_engine = create_engine(f"sqlite:///{tmp_path}/candles.db")
    Base.metadata.create_all(candles_engine)

    strategy_versions = StrategyVersionService(
        StrategyVersionRepository(session_factory), StrategyRegistry(), generated_dir
    )
    return PdfToStrategyService(
        DraftRepository(session_factory),
        strategy_versions,
        FakeRouter(code, codegen),
        backtest_database_url=f"sqlite:///{tmp_path}/candles.db",
    )


@pytest.fixture
async def api(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        accounts={"default": SimpleNamespace(pdf_to_strategy=_build_service(tmp_path))}
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


async def _upload(client) -> dict:
    response = await client.post(
        "/accounts/default/ai/pdf-strategy/upload",
        files={"file": ("method.pdf", _fake_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    return response.json()


async def test_upload_extracts_draft(api):
    draft = await _upload(api)
    assert draft["status"] == "pending_review"
    assert draft["extracted_spec"]["name"] == "gold_ema_pullback"
    assert draft["edited_spec"] is None


async def test_upload_with_symbol_overrides_extraction(api):
    response = await api.post(
        "/accounts/default/ai/pdf-strategy/upload",
        files={"file": ("method.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"symbol": "EURUSD"},
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["extracted_spec"]["symbols"] == ["XAUUSD"]
    assert draft["edited_spec"]["symbols"] == ["EURUSD"]
    assert draft["effective_spec"]["symbols"] == ["EURUSD"]


async def test_upload_rejects_non_pdf(api):
    response = await api.post(
        "/accounts/default/ai/pdf-strategy/upload",
        files={"file": ("method.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 400


STRUCTURED_SPEC = {
    **EXTRACTED_SPEC,
    "indicators": [{"type": "ema", "period": 200, "label": "EMA200"}],
}


async def test_from_spec_creates_draft_without_llm_call(api):
    response = await api.post(
        "/accounts/default/ai/pdf-strategy/from-spec", json={"spec": STRUCTURED_SPEC}
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["status"] == "pending_review"
    assert draft["extracted_spec"]["name"] == "gold_ema_pullback"
    assert draft["edited_spec"] is None
    assert draft["source_filename"] == "(uploaded JSON)"


async def test_from_spec_with_symbol_overrides_spec(api):
    response = await api.post(
        "/accounts/default/ai/pdf-strategy/from-spec",
        json={"spec": STRUCTURED_SPEC, "symbol": "EURUSD"},
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["extracted_spec"]["symbols"] == ["XAUUSD"]
    assert draft["edited_spec"]["symbols"] == ["EURUSD"]
    assert draft["effective_spec"]["symbols"] == ["EURUSD"]


async def test_from_spec_rejects_malformed_json(api):
    response = await api.post(
        "/accounts/default/ai/pdf-strategy/from-spec", json={"spec": {"name": "x"}}
    )
    assert response.status_code == 422


async def test_get_draft_not_found(api):
    response = await api.get("/accounts/default/ai/pdf-strategy/drafts/does-not-exist")
    assert response.status_code == 404


async def test_list_drafts(api):
    await _upload(api)
    response = await api.get("/accounts/default/ai/pdf-strategy/drafts")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_edit_then_approve_flow(api):
    draft = await _upload(api)
    edited_spec = {**draft["extracted_spec"], "name": "renamed_strategy"}

    patch_response = await api.patch(
        f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}", json={"edited_spec": edited_spec}
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["effective_spec"]["name"] == "renamed_strategy"

    approve_response = await api.post(
        f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/approve"
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    # Approving an already-approved draft conflicts.
    conflict = await api.post(f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/approve")
    assert conflict.status_code == 409


async def test_reject_draft(api):
    draft = await _upload(api)
    response = await api.post(f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


async def test_generate_code_requires_approval(api):
    draft = await _upload(api)
    response = await api.post(
        f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/generate-code"
    )
    assert response.status_code == 409


async def test_generate_code_success(api):
    draft = await _upload(api)
    await api.post(f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/approve")

    response = await api.post(
        f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/generate-code"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is True
    assert body["version_id"] is not None
    assert body["sandbox_errors"] == []


async def test_generate_code_llm_call_failure_returns_504(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        accounts={
            "default": SimpleNamespace(
                pdf_to_strategy=_build_service(tmp_path, codegen=FailingLLM())
            )
        }
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        draft = await _upload(client)
        await client.post(f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/approve")

        response = await client.post(
            f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/generate-code"
        )
        assert response.status_code == 504
        assert "timeout" in response.json()["detail"]


async def test_generate_code_surfaces_sandbox_errors(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        accounts={
            "default": SimpleNamespace(pdf_to_strategy=_build_service(tmp_path, INVALID_CODE))
        }
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        draft = await _upload(client)
        await client.post(f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/approve")

        response = await client.post(
            f"/accounts/default/ai/pdf-strategy/drafts/{draft['id']}/generate-code"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_valid"] is False
        assert body["version_id"] is None
        assert any("os" in e for e in body["sandbox_errors"])
