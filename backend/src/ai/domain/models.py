"""AI layer domain models: §8.1 (PDF -> StrategySpec -> code) and §8.2
(10-trade self-refinement loop).

Framework-free (no pydantic, no FastAPI). `ai/api/schemas.py` mirrors these
for the wire; `strategies/domain/models.py` has the separate, narrower
`StrategySpec` a `Strategy` instance actually carries at runtime — a
`StrategyDraft` here is upstream of that, still mid-review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DraftStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CODE_GENERATED = "code_generated"


@dataclass(frozen=True)
class ExtractedStrategySpec:
    """What the `extract_method_from_pdf` prompt produces — the human-reviewable
    contract between the PDF and the generated code. Never executed directly.
    """

    name: str
    symbols: tuple[str, ...]
    entry_timeframe: str
    confirmation_timeframes: tuple[str, ...]
    indicators: tuple[str, ...]
    entry_rules: str
    exit_rules: str
    risk_notes: str
    params: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ExtractedStrategySpec:
        return ExtractedStrategySpec(
            name=str(data["name"]),
            symbols=tuple(data.get("symbols", [])),
            entry_timeframe=str(data.get("entry_timeframe", "M5")),
            confirmation_timeframes=tuple(data.get("confirmation_timeframes", [])),
            indicators=tuple(data.get("indicators", [])),
            entry_rules=str(data.get("entry_rules", "")),
            exit_rules=str(data.get("exit_rules", "")),
            risk_notes=str(data.get("risk_notes", "")),
            params=dict(data.get("params", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "symbols": list(self.symbols),
            "entry_timeframe": self.entry_timeframe,
            "confirmation_timeframes": list(self.confirmation_timeframes),
            "indicators": list(self.indicators),
            "entry_rules": self.entry_rules,
            "exit_rules": self.exit_rules,
            "risk_notes": self.risk_notes,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class StrategyDraft:
    """A PDF-derived spec awaiting human review (§8.1). Never a source of
    trades on its own — only `generate_code` after `APPROVED` produces
    something the sandbox/backtest/engine can touch.
    """

    id: str
    source_filename: str
    created_at: datetime
    extracted_spec: ExtractedStrategySpec
    status: DraftStatus = DraftStatus.PENDING_REVIEW
    edited_spec: ExtractedStrategySpec | None = None

    @property
    def effective_spec(self) -> ExtractedStrategySpec:
        """The spec code generation must use: the user's edits if any, else
        the raw extraction. Editing never mutates `extracted_spec` — that
        stays the original AI output for audit."""
        return self.edited_spec or self.extracted_spec


@dataclass(frozen=True)
class GeneratedCode:
    """Output of `generate_strategy_code` for an approved draft, after sandbox
    validation. `sandbox_errors` non-empty means the code was rejected and
    `version_id`/`backtest_report_id` stay unset.
    """

    draft_id: str
    code: str
    sandbox_errors: tuple[str, ...] = ()
    version_id: str | None = None
    backtest_report_id: str | None = None

    @property
    def is_valid(self) -> bool:
        return not self.sandbox_errors


@dataclass(frozen=True, kw_only=True)
class RefinementConfig:
    """Mirrors `configs/ai.yaml: refinement` — the self-refinement loop's
    apply policy. User-owned like `RiskCaps`; the refinement loop reads it,
    never writes it."""

    mode: str = "suggest"  # "suggest" | "auto"
    auto_apply_min_improvement_pct: float = 10.0
    max_auto_refinements_per_day: int = 1


class ReportVerdict(StrEnum):
    NO_ACTION = "no_action"
    REFINEMENT_PROPOSED = "refinement_proposed"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    BACKTESTED = "backtested"
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True, kw_only=True)
class AnalysisReport:
    """Output of `review_ten_trades` (§8.2): the AI's read on the last N
    closed trades for one symbol, triggered by `TenTradesCompleted`. Always
    persisted, even when `verdict` is `NO_ACTION` — this is the audit trail
    of every review, not just the ones that led somewhere.
    """

    id: str
    symbol: str
    strategy_name: str
    base_version_id: str
    trade_ids: tuple[str, ...]
    created_at: datetime
    win_rate: float
    avg_r: float
    common_failure_pattern: str
    session_or_news_correlation: str
    verdict: ReportVerdict
    raw_llm_response: str
    proposal_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class RefinementProposal:
    """A candidate code change from `refine_strategy_code`, sandbox-validated
    and backtested against the version it's based on before any apply
    decision is made. `improvement_pct` is the candidate's avg_r percent
    delta over the baseline's — the sole metric the auto-apply policy gates
    on (bounded, always defined; profit_factor blows up to infinity with
    zero losing trades in a small sample, so it's shown as context only).
    """

    id: str
    report_id: str
    strategy_name: str
    base_version_id: str
    rationale: str
    proposed_code: str
    status: ProposalStatus
    created_at: datetime
    sandbox_errors: tuple[str, ...] = ()
    new_version_id: str | None = None
    baseline_backtest_report_id: str | None = None
    candidate_backtest_report_id: str | None = None
    improvement_pct: float | None = None
    applied_mode: str | None = None
