"""AI persistence tables: §8.1 PDF-derived drafts, §8.2 10-trade
self-refinement analysis reports/proposals, and settings-page per-task
provider overrides (AI_PROVIDER_SETTINGS_PLAN.md §6.3)."""

from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class AiDraftRow(Base):
    __tablename__ = "ai_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    extracted_spec: Mapped[dict] = mapped_column(JSON)
    edited_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AnalysisReportRow(Base):
    __tablename__ = "ai_analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    base_version_id: Mapped[str] = mapped_column(String(36))
    trade_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[float] = mapped_column(Float)
    avg_r: Mapped[float] = mapped_column(Float)
    common_failure_pattern: Mapped[str] = mapped_column(Text)
    session_or_news_correlation: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(32))
    raw_llm_response: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class RefinementProposalRow(Base):
    __tablename__ = "ai_refinement_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    base_version_id: Mapped[str] = mapped_column(String(36))
    rationale: Mapped[str] = mapped_column(Text)
    proposed_code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    sandbox_errors: Mapped[list] = mapped_column(JSON)
    new_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    baseline_backtest_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_backtest_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    improvement_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    applied_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)


class TaskProviderOverrideRow(Base):
    __tablename__ = "ai_task_provider_override"

    task: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[int] = mapped_column(Integer)
