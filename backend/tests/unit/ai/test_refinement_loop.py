"""10-trade self-refinement loop (§8.2): review -> optional refinement
proposal -> sandbox validate -> backtest before/after -> suggest/auto apply
policy. Backtests are faked (monkeypatched `run_backtest`/`write_report`) so
these tests exercise the service's own logic, not the full engine replay —
mirrors `test_pdf_to_strategy.py`'s fake-LLM/in-memory-SQLite style."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.adapters.report_repository import (
    AnalysisReportRepository,
    RefinementProposalRepository,
)
from src.ai.application import refinement_loop as refinement_loop_module
from src.ai.application.refinement_loop import RefinementLoopService
from src.ai.domain.models import (
    ProposalStatus,
    RefinementConfig,
    RefinementProposal,
    ReportVerdict,
)
from src.backtest.domain.models import BacktestReport
from src.journal.adapters.repository import JournalRepository
from src.journal.domain.models import TradeRecord
from src.market_data.adapters import orm as market_data_orm  # noqa: F401 — registers candles table
from src.shared.db.base import Base
from src.shared.events.definitions import TenTradesCompleted
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.domain.versioning import CodeSource, VersionStatus
from src.strategies.registry import StrategyRegistry

VALID_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class Sample:
    def __init__(self):
        self.spec = StrategySpec(
            name="sample", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=("H1",), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""

INVALID_CODE = "import os\nx = 1\n"

NO_ACTION_REVIEW = json.dumps(
    {
        "win_rate": 0.6,
        "avg_r": 0.3,
        "common_failure_pattern": "",
        "session_or_news_correlation": "",
        "verdict": "no_action",
        "refinement_summary": "",
    }
)

REFINE_REVIEW = json.dumps(
    {
        "win_rate": 0.3,
        "avg_r": -0.2,
        "common_failure_pattern": "chasing late breakouts",
        "session_or_news_correlation": "",
        "verdict": "refinement_proposed",
        "refinement_summary": "tighten the entry filter",
    }
)


def _refine_response(code: str = VALID_CODE) -> str:
    return f"RATIONALE: tightened the entry filter to avoid late breakouts.\n\n{code}"


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, message, *, max_tokens: int = 4096) -> str:
        return self.response


class RaisingLLM:
    async def complete(self, message, *, max_tokens: int = 4096) -> str:
        raise RuntimeError("LLM boom")


class RetryThenValidLLM:
    """First completion fails the sandbox (forbidden import); the retry
    prompt (fed the sandbox's error) gets a valid one — mirrors an LLM
    self-correcting once shown what it broke."""

    def __init__(self, bad_response: str, good_response: str) -> None:
        self.bad_response = bad_response
        self.good_response = good_response
        self.calls = 0

    async def complete(self, message, *, max_tokens: int = 4096) -> str:
        self.calls += 1
        return self.bad_response if self.calls == 1 else self.good_response


class FakeRouter:
    def __init__(self, review_response: str, refine_response: str | None = None) -> None:
        self._review = FakeLLM(review_response)
        self._refine = FakeLLM(refine_response or "")

    def for_task(self, task: str):
        return {"ten_trade_review": self._review, "code_refinement": self._refine}[task]


class StatefulRefineRouter:
    """Like `FakeRouter`, but `code_refinement` is served by a caller-supplied
    stateful LLM (e.g. `RetryThenValidLLM`) instead of a fixed response."""

    def __init__(self, review_response: str, refine_llm) -> None:
        self._review = FakeLLM(review_response)
        self._refine = refine_llm

    def for_task(self, task: str):
        return {"ten_trade_review": self._review, "code_refinement": self._refine}[task]


class RaisingRouter:
    def for_task(self, task: str):
        return RaisingLLM()


def _trade(trade_id: str) -> TradeRecord:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    return TradeRecord(
        id=trade_id,
        symbol="XAUUSD",
        side="buy",
        volume=0.1,
        open_price=2400.0,
        open_time=now,
        sl=2390.0,
        tp=2420.0,
        spread_points_at_entry=20,
        close_price=2401.0,
        close_time=now,
        profit=10.0,
    )


def _bt(avg_r: float) -> BacktestReport:
    return BacktestReport(
        strategy="sample",
        symbol="XAUUSD",
        period="2026-01:2026-06",
        starting_balance=10_000.0,
        ending_balance=10_000.0 + avg_r * 100,
        trades=(),
        equity_curve=(),
        win_rate=0.5,
        profit_factor=1.5,
        max_drawdown_pct=1.0,
        avg_r=avg_r,
        worst_losing_streak=0,
    )


def _make(tmp_path, llm_router, refinement_config: RefinementConfig | None = None, timezone="UTC"):
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

    journal_repository = JournalRepository(session_factory)
    trade_ids = tuple(f"t{i}" for i in range(10))
    for trade_id in trade_ids:
        journal_repository.save(_trade(trade_id))

    skill_selector = SkillSelector(
        skills={"XAUUSD": NormalSkill(name="normal-xauusd", symbol="XAUUSD", strategy="sample")}
    )

    proposal_repository = RefinementProposalRepository(session_factory)
    service = RefinementLoopService(
        report_repository=AnalysisReportRepository(session_factory),
        proposal_repository=proposal_repository,
        journal_repository=journal_repository,
        strategy_versions=strategy_versions,
        strategy_registry=registry,
        skill_selector=skill_selector,
        llm_router=llm_router,
        refinement_config=refinement_config or RefinementConfig(),
        timezone=timezone,
        backtest_period="2026-01:2026-06",
        backtest_database_url=f"sqlite:///{tmp_path}/candles.db",
    )
    event = TenTradesCompleted(symbol="XAUUSD", trade_ids=trade_ids)
    return service, strategy_versions, registry, base_version, event, proposal_repository


async def test_no_action_verdict_creates_no_proposal(tmp_path):
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, FakeRouter(NO_ACTION_REVIEW)
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    assert report.verdict == ReportVerdict.NO_ACTION
    assert report.proposal_id is None


async def test_suggest_mode_leaves_proposal_backtested_and_unapplied(tmp_path, monkeypatch):
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, FakeRouter(REFINE_REVIEW, _refine_response())
    )

    async def fake_run_backtest(strategy_name, symbol, period, *, strategy_source=None, **kwargs):
        return _bt(1.0) if strategy_source is registry else _bt(1.5)

    monkeypatch.setattr(refinement_loop_module, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(
        refinement_loop_module, "write_report", lambda report: tmp_path / f"{report.avg_r}.json"
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    assert report.verdict == ReportVerdict.REFINEMENT_PROPOSED
    proposal = await service.get_proposal(report.proposal_id)
    assert proposal.status == ProposalStatus.BACKTESTED
    assert proposal.new_version_id is not None
    assert proposal.improvement_pct == pytest.approx(50.0)
    assert proposal.applied_mode is None

    new_version = strategy_versions.get_version(proposal.new_version_id)
    assert new_version.status == VersionStatus.VALIDATED
    assert new_version.source == CodeSource.AI_REFINED
    # Suggest mode never activates anything itself.
    assert strategy_versions.get_version(base_version.id).status == VersionStatus.ACTIVE


async def test_sandbox_invalid_refined_code_is_rejected(tmp_path):
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, FakeRouter(REFINE_REVIEW, _refine_response(INVALID_CODE))
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    proposal = await service.get_proposal(report.proposal_id)
    assert proposal.status == ProposalStatus.REJECTED
    assert proposal.new_version_id is None
    assert any("os" in e for e in proposal.sandbox_errors)


async def test_refinement_retries_after_sandbox_rejection_then_succeeds(tmp_path, monkeypatch):
    refine_llm = RetryThenValidLLM(
        bad_response=_refine_response(INVALID_CODE), good_response=_refine_response()
    )
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, StatefulRefineRouter(REFINE_REVIEW, refine_llm)
    )

    async def fake_run_backtest(strategy_name, symbol, period, *, strategy_source=None, **kwargs):
        return _bt(1.0) if strategy_source is registry else _bt(1.5)

    monkeypatch.setattr(refinement_loop_module, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(
        refinement_loop_module, "write_report", lambda report: tmp_path / f"{report.avg_r}.json"
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    proposal = await service.get_proposal(report.proposal_id)
    assert proposal.status == ProposalStatus.BACKTESTED
    assert proposal.new_version_id is not None
    assert proposal.sandbox_errors == ()
    assert refine_llm.calls == 2


async def test_auto_mode_activates_when_improvement_meets_threshold(tmp_path, monkeypatch):
    config = RefinementConfig(mode="auto", auto_apply_min_improvement_pct=10.0)
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, FakeRouter(REFINE_REVIEW, _refine_response()), refinement_config=config
    )

    async def fake_run_backtest(strategy_name, symbol, period, *, strategy_source=None, **kwargs):
        return _bt(1.0) if strategy_source is registry else _bt(1.5)  # +50%

    monkeypatch.setattr(refinement_loop_module, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(
        refinement_loop_module, "write_report", lambda report: tmp_path / f"{report.avg_r}.json"
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    proposal = await service.get_proposal(report.proposal_id)
    assert proposal.status == ProposalStatus.APPLIED
    assert proposal.applied_mode == "auto"
    assert strategy_versions.get_version(proposal.new_version_id).status == VersionStatus.ACTIVE
    assert strategy_versions.get_version(base_version.id).status == VersionStatus.ARCHIVED
    assert registry.get("sample") is not None


async def test_auto_mode_rate_limit_blocks_second_refinement_same_day(tmp_path, monkeypatch):
    config = RefinementConfig(mode="auto", auto_apply_min_improvement_pct=10.0)
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, FakeRouter(REFINE_REVIEW, _refine_response()), refinement_config=config
    )
    # An auto-applied refinement for "sample" already happened today -> rate limit hit.
    proposal_repository.save(
        RefinementProposal(
            id=str(uuid.uuid4()),
            report_id="prior-report",
            strategy_name="sample",
            base_version_id=base_version.id,
            rationale="prior refinement",
            proposed_code=VALID_CODE,
            status=ProposalStatus.APPLIED,
            created_at=datetime.now(UTC),
            applied_mode="auto",
        )
    )

    async def fake_run_backtest(strategy_name, symbol, period, *, strategy_source=None, **kwargs):
        return _bt(1.0) if strategy_source is registry else _bt(1.5)

    monkeypatch.setattr(refinement_loop_module, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(
        refinement_loop_module, "write_report", lambda report: tmp_path / f"{report.avg_r}.json"
    )

    await service.on_ten_trades_completed(event)

    (report,) = await service.list_reports()
    proposal = await service.get_proposal(report.proposal_id)
    assert proposal.status == ProposalStatus.BACKTESTED
    assert proposal.applied_mode is None
    assert strategy_versions.get_version(base_version.id).status == VersionStatus.ACTIVE


async def test_llm_failure_does_not_raise_and_leaves_no_partial_report(tmp_path):
    service, strategy_versions, registry, base_version, event, proposal_repository = _make(
        tmp_path, RaisingRouter()
    )

    await service.on_ten_trades_completed(event)  # must not raise

    assert await service.list_reports() == []
