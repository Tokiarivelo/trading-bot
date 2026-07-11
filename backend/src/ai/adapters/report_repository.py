"""Analysis report & refinement proposal persistence (§8.2), sync SQLAlchemy;
call via asyncio.to_thread — mirrors `ai/adapters/repository.py`'s DraftRepository.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.ai.adapters.orm import AnalysisReportRow, RefinementProposalRow
from src.ai.domain.models import AnalysisReport, ProposalStatus, RefinementProposal, ReportVerdict


class AnalysisReportRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, report: AnalysisReport) -> None:
        row = _report_to_row(report)
        with self._session_factory() as session:
            session.merge(row)
            session.commit()

    def get(self, report_id: str) -> AnalysisReport | None:
        with self._session_factory() as session:
            row = session.get(AnalysisReportRow, report_id)
        return _report_to_domain(row) if row else None

    def list_all(self, symbol: str | None = None) -> list[AnalysisReport]:
        query = select(AnalysisReportRow).order_by(AnalysisReportRow.created_at.desc())
        if symbol is not None:
            query = query.where(AnalysisReportRow.symbol == symbol)
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_report_to_domain(row) for row in rows]


class RefinementProposalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, proposal: RefinementProposal) -> None:
        row = _proposal_to_row(proposal)
        with self._session_factory() as session:
            session.merge(row)
            session.commit()

    def get(self, proposal_id: str) -> RefinementProposal | None:
        with self._session_factory() as session:
            row = session.get(RefinementProposalRow, proposal_id)
        return _proposal_to_domain(row) if row else None

    def list_by_report(self, report_id: str) -> list[RefinementProposal]:
        query = select(RefinementProposalRow).where(
            RefinementProposalRow.report_id == report_id
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_proposal_to_domain(row) for row in rows]

    def list_by_strategy(self, strategy_name: str) -> list[RefinementProposal]:
        query = select(RefinementProposalRow).where(
            RefinementProposalRow.strategy_name == strategy_name
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_proposal_to_domain(row) for row in rows]


def _report_to_row(report: AnalysisReport) -> AnalysisReportRow:
    return AnalysisReportRow(
        id=report.id,
        symbol=report.symbol,
        strategy_name=report.strategy_name,
        base_version_id=report.base_version_id,
        trade_ids=list(report.trade_ids),
        created_at=int(report.created_at.timestamp()),
        win_rate=report.win_rate,
        avg_r=report.avg_r,
        common_failure_pattern=report.common_failure_pattern,
        session_or_news_correlation=report.session_or_news_correlation,
        verdict=report.verdict.value,
        raw_llm_response=report.raw_llm_response,
        proposal_id=report.proposal_id,
    )


def _report_to_domain(row: AnalysisReportRow) -> AnalysisReport:
    return AnalysisReport(
        id=row.id,
        symbol=row.symbol,
        strategy_name=row.strategy_name,
        base_version_id=row.base_version_id,
        trade_ids=tuple(row.trade_ids),
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        win_rate=row.win_rate,
        avg_r=row.avg_r,
        common_failure_pattern=row.common_failure_pattern,
        session_or_news_correlation=row.session_or_news_correlation,
        verdict=ReportVerdict(row.verdict),
        raw_llm_response=row.raw_llm_response,
        proposal_id=row.proposal_id,
    )


def _proposal_to_row(proposal: RefinementProposal) -> RefinementProposalRow:
    return RefinementProposalRow(
        id=proposal.id,
        report_id=proposal.report_id,
        strategy_name=proposal.strategy_name,
        base_version_id=proposal.base_version_id,
        rationale=proposal.rationale,
        proposed_code=proposal.proposed_code,
        status=proposal.status.value,
        created_at=int(proposal.created_at.timestamp()),
        sandbox_errors=list(proposal.sandbox_errors),
        new_version_id=proposal.new_version_id,
        baseline_backtest_report_id=proposal.baseline_backtest_report_id,
        candidate_backtest_report_id=proposal.candidate_backtest_report_id,
        improvement_pct=proposal.improvement_pct,
        applied_mode=proposal.applied_mode,
    )


def _proposal_to_domain(row: RefinementProposalRow) -> RefinementProposal:
    return RefinementProposal(
        id=row.id,
        report_id=row.report_id,
        strategy_name=row.strategy_name,
        base_version_id=row.base_version_id,
        rationale=row.rationale,
        proposed_code=row.proposed_code,
        status=ProposalStatus(row.status),
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        sandbox_errors=tuple(row.sandbox_errors),
        new_version_id=row.new_version_id,
        baseline_backtest_report_id=row.baseline_backtest_report_id,
        candidate_backtest_report_id=row.candidate_backtest_report_id,
        improvement_pct=row.improvement_pct,
        applied_mode=row.applied_mode,
    )
