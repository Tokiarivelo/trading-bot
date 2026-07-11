"""Wire models for the PDF -> StrategySpec pipeline (§8.1). Mirrors
`ai/domain/models.py`; the domain stays framework-free."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.ai.domain.models import DraftStatus, ExtractedStrategySpec, GeneratedCode, StrategyDraft


class ExtractedStrategySpecSchema(BaseModel):
    """A trading method as structured data — used both as the AI's raw
    extraction and as the shape of a user's edits to it."""

    name: str = Field(description="Short snake_case slug, e.g. 'gold_ema_pullback'.")
    symbols: list[str] = Field(
        description="Symbols this method applies to (subset of XAUUSD/XAGUSD/BTCUSD)."
    )
    entry_timeframe: str = Field(
        description="Entry timeframe — always 'M5' for this project regardless of what the "
        "source document describes."
    )
    confirmation_timeframes: list[str] = Field(
        description="Higher timeframes used to confirm an M5 entry, e.g. ['H1', 'H4']."
    )
    indicators: list[str] = Field(description="Indicator names used, e.g. ['EMA200', 'RSI14'].")
    entry_rules: str = Field(description="Plain-English entry logic, precise enough to implement.")
    exit_rules: str = Field(description="Plain-English stop-loss/take-profit/exit logic.")
    risk_notes: str = Field(
        description="Position-sizing/risk notes from the source document — informational only; "
        "actual risk caps always come from configs/risk.yaml, never from strategy text."
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Numeric parameters mentioned in the method (lookback periods, R-multiples).",
    )

    @staticmethod
    def from_domain(spec: ExtractedStrategySpec) -> ExtractedStrategySpecSchema:
        return ExtractedStrategySpecSchema(**spec.to_dict())

    def to_domain(self) -> ExtractedStrategySpec:
        return ExtractedStrategySpec.from_dict(self.model_dump())


class StrategyDraftOut(BaseModel):
    id: str = Field(description="Draft id, used in every other /ai/pdf-strategy/drafts/ endpoint.")
    source_filename: str = Field(description="Name of the uploaded PDF this draft came from.")
    created_at: int = Field(description="Draft creation time, epoch seconds UTC.")
    status: DraftStatus = Field(
        description="pending_review -> approved -> code_generated, or rejected at any point "
        "before code_generated."
    )
    extracted_spec: ExtractedStrategySpecSchema = Field(
        description="The AI's raw extraction from the PDF — never mutated by edits."
    )
    edited_spec: ExtractedStrategySpecSchema | None = Field(
        description="The user's edited spec, if any edits were made via PATCH."
    )
    effective_spec: ExtractedStrategySpecSchema = Field(
        description="What code generation will actually use: edited_spec if set, else "
        "extracted_spec."
    )

    @staticmethod
    def from_domain(draft: StrategyDraft) -> StrategyDraftOut:
        return StrategyDraftOut(
            id=draft.id,
            source_filename=draft.source_filename,
            created_at=int(draft.created_at.timestamp()),
            status=draft.status,
            extracted_spec=ExtractedStrategySpecSchema.from_domain(draft.extracted_spec),
            edited_spec=(
                ExtractedStrategySpecSchema.from_domain(draft.edited_spec)
                if draft.edited_spec
                else None
            ),
            effective_spec=ExtractedStrategySpecSchema.from_domain(draft.effective_spec),
        )


class UpdateDraftSpecIn(BaseModel):
    edited_spec: ExtractedStrategySpecSchema = Field(
        description="Full replacement spec after the user's review edits."
    )


class GeneratedCodeOut(BaseModel):
    draft_id: str = Field(description="The draft this code was generated from.")
    code: str = Field(description="The generated Python source, whether or not it validated.")
    is_valid: bool = Field(description="True if the code passed sandbox validation.")
    sandbox_errors: list[str] = Field(
        description="Why the code was rejected — empty when is_valid is true."
    )
    version_id: str | None = Field(
        description="The new StrategyVersion id if validation passed, else null. Its status is "
        "'validated', not 'active' — activating it is a separate user action via "
        "POST /strategies/versions/{id}/activate."
    )
    backtest_report_id: str | None = Field(
        description="Id of the automatic backtest report (GET /backtest/reports/{id}), or null "
        "if validation failed or no candle history was available yet to run one."
    )

    @staticmethod
    def from_domain(result: GeneratedCode) -> GeneratedCodeOut:
        return GeneratedCodeOut(
            draft_id=result.draft_id,
            code=result.code,
            is_valid=result.is_valid,
            sandbox_errors=list(result.sandbox_errors),
            version_id=result.version_id,
            backtest_report_id=result.backtest_report_id,
        )
