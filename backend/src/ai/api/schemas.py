"""Wire models for the PDF -> StrategySpec pipeline (§8.1) and the 10-trade
self-refinement loop (§8.2). Mirrors `ai/domain/models.py`; the domain stays
framework-free."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.ai.domain.models import (
    AnalysisReport,
    DraftStatus,
    ExtractedStrategySpec,
    GeneratedCode,
    IndicatorSpec,
    PriceLevelAnnotation,
    ProposalStatus,
    RefinementProposal,
    RegeneratedCode,
    ReportVerdict,
    StrategyDraft,
)
from src.ai.domain.provider_config import ProviderTestResult, TaskProviderStatus
from src.backtest.api.schemas import BacktestReportSummaryOut


class IndicatorSpecSchema(BaseModel):
    """One indicator recognized into a plottable family — see `IndicatorType`
    for the 5 supported families (ema/sma/rsi/macd/bollinger)."""

    type: str = Field(description="One of: ema, sma, rsi, macd, bollinger.")
    period: int = Field(
        description="Primary lookback — EMA/SMA/RSI span, Bollinger's SMA period, or MACD's "
        "fast period."
    )
    label: str = Field(description="The indicator as written in the source text, e.g. 'EMA200'.")
    source: str = Field(default="close", description="Candle field the indicator is computed on.")
    params: dict[str, float] = Field(
        default_factory=dict,
        description="Family-specific extra knobs — macd: {slow, signal}; bollinger: {std_dev}.",
    )

    @staticmethod
    def from_domain(spec: IndicatorSpec) -> IndicatorSpecSchema:
        return IndicatorSpecSchema(**spec.to_dict())

    def to_domain(self) -> IndicatorSpec:
        return IndicatorSpec.from_dict(self.model_dump())


class PriceLevelAnnotationSchema(BaseModel):
    """An explicit numeric price level the source text states outright (e.g.
    "resistance at 2050") — never inferred, only extracted from a literal
    number printed in the text."""

    type: str = Field(description="One of: support, resistance, level.")
    price: float = Field(description="The literal price level from the text.")
    label: str = Field(description="The level as written in the source text.")

    @staticmethod
    def from_domain(level: PriceLevelAnnotation) -> PriceLevelAnnotationSchema:
        return PriceLevelAnnotationSchema(**level.to_dict())

    def to_domain(self) -> PriceLevelAnnotation:
        return PriceLevelAnnotation.from_dict(self.model_dump())


class ExtractedStrategySpecSchema(BaseModel):
    """A trading method as structured data — used both as the AI's raw
    extraction and as the shape of a user's edits to it."""

    name: str = Field(description="Short snake_case slug, e.g. 'gold_ema_pullback'.")
    symbols: list[str] = Field(
        description="Broker symbols this method applies to. Empty when the source PDF never "
        "named an instrument and no symbol override was given at upload time — a human must "
        "set one (via PATCH) before code generation's auto-backtest can run."
    )
    entry_timeframe: str = Field(
        description="Entry timeframe — always 'M5' for this project regardless of what the "
        "source document describes."
    )
    confirmation_timeframes: list[str] = Field(
        description="Higher timeframes used to confirm an M5 entry, e.g. ['H1', 'H4']."
    )
    indicators: list[IndicatorSpecSchema] = Field(
        description="Indicators recognized into one of the 5 plottable families, structured "
        "enough to compute and render on the chart."
    )
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
    unrecognized_indicators: list[str] = Field(
        default_factory=list,
        description="Indicator names mentioned that don't map onto one of the 5 plottable "
        "families — kept for display/audit, never rendered on the chart.",
    )
    price_levels: list[PriceLevelAnnotationSchema] = Field(
        default_factory=list,
        description="Explicit numeric support/resistance/pivot levels the text states outright "
        "— rendered as locked horizontal lines on the chart.",
    )
    chart_notes: list[str] = Field(
        default_factory=list,
        description="Other charting/drawing-tool mentions with no explicit number attached (e.g. "
        "'Fibonacci retracement on swing points') — informational only, never rendered as "
        "geometry since there's no concrete level to place it at.",
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


class RegenerateCodeIn(BaseModel):
    instructions: str = Field(
        description="Free-form description of what to change, e.g. 'only trade during the "
        "London session' or 'tighten the stop loss to 1.5x ATR'. Sent to the LLM alongside "
        "the version's current code and spec snapshot.",
        min_length=1,
    )
    spec: ExtractedStrategySpecSchema | None = Field(
        default=None,
        description="Edited spec snapshot to use instead of the version's stored one — both "
        "in the prompt sent to the LLM and on the resulting version. Lets the trader tweak "
        "symbols, timeframes, entry/exit rules, etc. before regenerating. Omit to regenerate "
        "against the version's spec unchanged.",
    )
    new_name: str | None = Field(
        default=None,
        description="Leave unset to save the regenerated code as the next version of this "
        "version's own strategy family (the usual case). Set to a different, not-yet-used "
        "name to fork the result into a brand-new strategy family at version 1 instead — the "
        "'duplicate' save destination, for trying a change without touching the original. "
        "Rejected with 409 if the name is already in use by another family.",
    )


class RegeneratedCodeOut(BaseModel):
    version_id: str = Field(description="The strategy version this regeneration was based on.")
    instructions: str = Field(description="The instructions that were sent to the LLM.")
    code: str = Field(description="The regenerated Python source, whether or not it validated.")
    is_valid: bool = Field(description="True if the code passed sandbox validation.")
    sandbox_errors: list[str] = Field(
        description="Why the code was rejected — empty when is_valid is true."
    )
    new_version_id: str | None = Field(
        description="The new StrategyVersion id if validation passed, else null. Its status is "
        "'validated', not 'active' — activating it is a separate user action via "
        "POST /strategies/versions/{id}/activate."
    )

    @staticmethod
    def from_domain(result: RegeneratedCode) -> RegeneratedCodeOut:
        return RegeneratedCodeOut(
            version_id=result.version_id,
            instructions=result.instructions,
            code=result.code,
            is_valid=result.is_valid,
            sandbox_errors=list(result.sandbox_errors),
            new_version_id=result.new_version_id,
        )


class AnalysisReportOut(BaseModel):
    id: str = Field(description="Report id, used at GET /ai/refinement/reports/{id}.")
    symbol: str = Field(description="Symbol these trades were on.")
    strategy_name: str = Field(description="Strategy family reviewed.")
    base_version_id: str = Field(description="The StrategyVersion active when this review ran.")
    trade_ids: list[str] = Field(description="The closed TradeRecord ids this review covers.")
    created_at: int = Field(description="Epoch seconds UTC.")
    win_rate: float = Field(description="Fraction of the reviewed trades with positive profit.")
    avg_r: float = Field(description="Average profit in R-multiples across the reviewed trades.")
    common_failure_pattern: str = Field(description="AI's finding on the most common loss cause.")
    session_or_news_correlation: str = Field(
        description="AI's finding on whether losses cluster around a session/time window."
    )
    verdict: ReportVerdict = Field(
        description="'no_action' or 'refinement_proposed' — see proposal_id for the latter."
    )
    raw_llm_response: str = Field(description="The full parsed LLM response, kept for audit.")
    proposal_id: str | None = Field(
        description="The RefinementProposal this review produced, if verdict is "
        "'refinement_proposed' — null otherwise."
    )

    @staticmethod
    def from_domain(report: AnalysisReport) -> AnalysisReportOut:
        return AnalysisReportOut(
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
            verdict=report.verdict,
            raw_llm_response=report.raw_llm_response,
            proposal_id=report.proposal_id,
        )


class RefinementProposalDetailOut(BaseModel):
    id: str = Field(description="Proposal id.")
    report_id: str = Field(description="The AnalysisReport that produced this proposal.")
    strategy_name: str = Field(description="Strategy family this proposal revises.")
    base_version_id: str = Field(description="The StrategyVersion this proposal is a diff of.")
    rationale: str = Field(description="The AI's explanation of what it changed and why.")
    proposed_code: str = Field(description="Full revised source, whether or not it was applied.")
    status: ProposalStatus = Field(
        description="'pending' (backtest incomplete), 'backtested' (awaiting a decision), "
        "'applied' (a StrategyVersion was activated), or 'rejected' (sandbox failure, policy "
        "rejection, or a human declined it)."
    )
    created_at: int = Field(description="Epoch seconds UTC.")
    sandbox_errors: list[str] = Field(
        description="Why sandbox validation failed — empty unless status is 'rejected' for that "
        "reason."
    )
    new_version_id: str | None = Field(
        description="The StrategyVersion created from proposed_code, if sandbox validation "
        "passed. Activate it via POST /strategies/versions/{id}/activate — that endpoint is "
        "also how this proposal (or any older version) gets rolled back to later."
    )
    improvement_pct: float | None = Field(
        description="Candidate's avg_r percent improvement over the baseline's, the sole metric "
        "the auto-apply policy gates on. Null if either backtest couldn't run (no candle "
        "history yet)."
    )
    applied_mode: str | None = Field(
        description="'suggest' or 'auto' — which policy mode decided this proposal's status, "
        "null while still awaiting a decision."
    )
    diff: list[str] = Field(
        description="Unified diff of base_version_id's code against proposed_code, computed "
        "fresh on every read (never stored) for the review UI."
    )
    baseline_backtest: BacktestReportSummaryOut | None = Field(
        description="Headline stats for the base version's backtest over the comparison period, "
        "or null if it couldn't run."
    )
    candidate_backtest: BacktestReportSummaryOut | None = Field(
        description="Headline stats for proposed_code's backtest over the same period, or null "
        "if it couldn't run."
    )

    @staticmethod
    def from_domain(
        proposal: RefinementProposal,
        *,
        diff: list[str],
        baseline_backtest: BacktestReportSummaryOut | None,
        candidate_backtest: BacktestReportSummaryOut | None,
    ) -> RefinementProposalDetailOut:
        return RefinementProposalDetailOut(
            id=proposal.id,
            report_id=proposal.report_id,
            strategy_name=proposal.strategy_name,
            base_version_id=proposal.base_version_id,
            rationale=proposal.rationale,
            proposed_code=proposal.proposed_code,
            status=proposal.status,
            created_at=int(proposal.created_at.timestamp()),
            sandbox_errors=list(proposal.sandbox_errors),
            new_version_id=proposal.new_version_id,
            improvement_pct=proposal.improvement_pct,
            applied_mode=proposal.applied_mode,
            diff=diff,
            baseline_backtest=baseline_backtest,
            candidate_backtest=candidate_backtest,
        )


# ── AI settings: per-task provider selection (AI_PROVIDER_SETTINGS_PLAN.md §7) ──


class TaskProviderStatusOut(BaseModel):
    """A task's effective LLM provider/model right now, and whether that's an
    operator-set override or the `configs/ai.yaml` default."""

    task: str = Field(
        description="One of the 4 known AI tasks: pdf_extraction, code_generation, "
        "ten_trade_review, code_refinement."
    )
    provider: str = Field(
        description="One of KNOWN_PROVIDERS: claude, ollama, claude_code, openclaw."
    )
    model: str = Field(description="Model id/name passed to the provider's adapter.")
    source: str = Field(
        description="'override' if a settings-page write is pinning this task, 'default' if "
        "it's still following the configs/ai.yaml default."
    )
    configured: bool = Field(
        description="Whether the resolved provider has its required secret/URL set (checked "
        "without a network call and without revealing the secret itself)."
    )

    @staticmethod
    def from_domain(status: TaskProviderStatus) -> TaskProviderStatusOut:
        return TaskProviderStatusOut(
            task=status.task,
            provider=status.provider,
            model=status.model,
            source=status.source,
            configured=status.configured,
        )


class SetTaskProviderIn(BaseModel):
    provider: str = Field(
        description="One of KNOWN_PROVIDERS: claude, ollama, claude_code, "
        "openclaw. 'Hermes Agent' in the UI is provider=ollama with a hermes3:* model."
    )
    model: str = Field(description="Model id/name to pass to that provider's adapter.")


class ProviderTestIn(BaseModel):
    """Optional body for `POST /ai/settings/providers/{provider}/test`."""

    message: str | None = Field(
        default=None,
        description="Custom message to send instead of the default one-token connectivity "
        "probe, e.g. 'hello'. When set, the provider's actual reply comes back in the "
        "response's `reply` field so the settings page can show a real round-trip, not just "
        "pass/fail.",
    )


class ProviderTestResultOut(BaseModel):
    """Outcome of a live probe against a provider — never a failed HTTP
    request; a failed probe still comes back 200 with ok=false so the
    settings page can render pass/fail inline."""

    provider: str = Field(description="The provider that was probed.")
    ok: bool = Field(description="True if the probe call completed successfully.")
    message: str | None = Field(
        description="Failure detail (missing config, connection error, etc.) — null when ok."
    )
    reply: str | None = Field(
        description="The provider's raw reply text, only populated when the request body "
        "included a custom `message` and the probe succeeded — null for the default "
        "connectivity-only probe or on failure."
    )

    @staticmethod
    def from_domain(result: ProviderTestResult) -> ProviderTestResultOut:
        return ProviderTestResultOut(
            provider=result.provider, ok=result.ok, message=result.message, reply=result.reply
        )


class ProviderPresetModelOut(BaseModel):
    label: str = Field(
        description="Display label for the quick-pick chip, e.g. 'Hermes Agent (8b, default)'."
    )
    model: str = Field(description="The model string the chip sets, e.g. 'hermes3:8b'.")


class ProviderInfoOut(BaseModel):
    """One entry in the catalog of providers the settings page offers —
    display copy plus whether it's usable right now (settings-page key,
    .env fallback, or local URL/binary), never the secret value itself."""

    id: str = Field(description="Provider id, one of KNOWN_PROVIDERS.")
    label: str = Field(description="Display name shown in the settings UI dropdown.")
    description: str = Field(
        description="One-line explanation of what this provider is and when to prefer it."
    )
    needs_secret: bool = Field(
        description="Whether this provider takes an API key at all — true for every provider "
        "except 'ollama' (local server URL only) and 'claude_code' (local CLI binary only)."
    )
    configured: bool = Field(
        description="Whether this provider is usable right now — a settings-page key is set, "
        "its .env fallback is set, or (for ollama/claude_code) its local URL/binary is "
        "reachable — checked without a network call and without revealing any secret."
    )
    preset_models: list[ProviderPresetModelOut] | None = Field(
        default=None,
        description="Quick-pick model presets to show for this provider, e.g. the Hermes Agent "
        "chips for 'ollama' or the curated GPT-5.6 tiers for 'openai'. Null for providers with "
        "no curated presets (e.g. 'openclaw', whose available models depend on the operator's "
        "own deployment).",
    )


class ProviderKeyIn(BaseModel):
    api_key: str = Field(
        description="The provider's API key/secret. Stored Fernet-encrypted at rest (OS "
        "keyring-held key) and never echoed back in any response.",
        min_length=1,
    )
