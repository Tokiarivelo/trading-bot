"""10-trade refinement loop API endpoints (§8.2, F5) — read-only except
reject; applying/rolling back always goes through the existing
POST /strategies/versions/{id}/activate (see strategies/api/routes.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.adapters.report_repository import (
    AnalysisReportRepository,
    RefinementProposalRepository,
)
from src.ai.api.routes_refinement import router
from src.ai.application.refinement_loop import RefinementLoopService
from src.ai.domain.models import (
    AnalysisReport,
    ProposalStatus,
    RefinementConfig,
    RefinementProposal,
    ReportVerdict,
)
from src.journal.adapters.repository import JournalRepository
from src.shared.db.base import Base
from src.skills.application.skill_selector import SkillSelector
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

REVISED_CODE = VALID_CODE.replace("return None", "return None  # revised")


class NullRouter:
    def for_task(self, task: str):
        raise AssertionError("no LLM call expected in route tests")


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()

    registry = StrategyRegistry()
    strategy_versions = StrategyVersionService(
        StrategyVersionRepository(session_factory), registry, generated_dir
    )
    base_version = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.MANUAL
    )
    strategy_versions.activate_version(base_version.id)

    report_repository = AnalysisReportRepository(session_factory)
    proposal_repository = RefinementProposalRepository(session_factory)
    service = RefinementLoopService(
        report_repository=report_repository,
        proposal_repository=proposal_repository,
        journal_repository=JournalRepository(session_factory),
        strategy_versions=strategy_versions,
        strategy_registry=registry,
        skill_selector=SkillSelector(skills={}),
        llm_router=NullRouter(),
        refinement_config=RefinementConfig(),
    )
    return SimpleNamespace(
        strategy_versions=strategy_versions,
        report_repository=report_repository,
        proposal_repository=proposal_repository,
        refinement_loop=service,
        base_version=base_version,
    )


@pytest.fixture
async def api(env):
    app = FastAPI()
    app.include_router(router)
    app.state.container = env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client


def _report(env, verdict=ReportVerdict.NO_ACTION, proposal_id=None) -> AnalysisReport:
    report = AnalysisReport(
        id=str(uuid.uuid4()),
        symbol="XAUUSD",
        strategy_name="sample",
        base_version_id=env.base_version.id,
        trade_ids=tuple(f"t{i}" for i in range(10)),
        created_at=datetime.now(UTC),
        win_rate=0.4,
        avg_r=0.1,
        common_failure_pattern="chasing breakouts",
        session_or_news_correlation="",
        verdict=verdict,
        raw_llm_response="{}",
        proposal_id=proposal_id,
    )
    env.report_repository.save(report)
    return report


def _proposal(env, status=ProposalStatus.BACKTESTED, new_version_id=None) -> RefinementProposal:
    proposal = RefinementProposal(
        id=str(uuid.uuid4()),
        report_id="r1",
        strategy_name="sample",
        base_version_id=env.base_version.id,
        rationale="tightened entry filter",
        proposed_code=REVISED_CODE,
        status=status,
        created_at=datetime.now(UTC),
        new_version_id=new_version_id,
    )
    env.proposal_repository.save(proposal)
    return proposal


async def test_list_reports_empty(api):
    response = await api.get("/ai/refinement/reports")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_and_get_report(env, api):
    report = _report(env)
    response = await api.get("/ai/refinement/reports")
    assert response.status_code == 200
    (summary,) = response.json()
    assert summary["id"] == report.id
    assert summary["verdict"] == "no_action"

    detail = await api.get(f"/ai/refinement/reports/{report.id}")
    assert detail.status_code == 200
    assert detail.json()["common_failure_pattern"] == "chasing breakouts"


async def test_list_reports_filters_by_symbol(env, api):
    _report(env)
    response = await api.get("/ai/refinement/reports", params={"symbol": "BTCUSD"})
    assert response.status_code == 200
    assert response.json() == []


async def test_get_report_not_found(api):
    response = await api.get("/ai/refinement/reports/does-not-exist")
    assert response.status_code == 404


async def test_get_proposal_includes_diff_and_backtests(env, api):
    proposal = _proposal(env)
    response = await api.get(f"/ai/refinement/proposals/{proposal.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "backtested"
    assert any(line.startswith("+") for line in body["diff"])
    assert body["baseline_backtest"] is None  # no report file written in this test
    assert body["candidate_backtest"] is None


async def test_get_proposal_not_found(api):
    response = await api.get("/ai/refinement/proposals/does-not-exist")
    assert response.status_code == 404


async def test_reject_pending_proposal(env, api):
    proposal = _proposal(env, status=ProposalStatus.PENDING)
    response = await api.post(f"/ai/refinement/proposals/{proposal.id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


async def test_reject_already_applied_conflicts(env, api):
    proposal = _proposal(env, status=ProposalStatus.APPLIED)
    response = await api.post(f"/ai/refinement/proposals/{proposal.id}/reject")
    assert response.status_code == 409


async def test_reject_not_found(api):
    response = await api.post("/ai/refinement/proposals/does-not-exist/reject")
    assert response.status_code == 404
