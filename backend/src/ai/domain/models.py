"""AI layer domain models: §8.1 (PDF -> StrategySpec -> code) and §8.2
(10-trade self-refinement loop).

Framework-free (no pydantic, no FastAPI). `ai/api/schemas.py` mirrors these
for the wire; `strategies/domain/models.py` has the separate, narrower
`StrategySpec` a `Strategy` instance actually carries at runtime — a
`StrategyDraft` here is upstream of that, still mid-review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DraftStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CODE_GENERATED = "code_generated"


class IndicatorType(StrEnum):
    """The 5 indicator families the chart can actually plot. Anything the
    PDF names outside this set stays in `ExtractedStrategySpec.
    unrecognized_indicators` instead of being force-fit here."""

    EMA = "ema"
    SMA = "sma"
    RSI = "rsi"
    MACD = "macd"
    BOLLINGER = "bollinger"


@dataclass(frozen=True)
class IndicatorSpec:
    """One indicator the source text names, structured enough to actually
    compute and plot. `period` is each family's primary lookback (EMA/SMA
    span, RSI span, Bollinger's SMA period, or MACD's fast period); `params`
    holds the remaining family-specific knobs (macd: slow/signal, bollinger:
    std_dev). `label` keeps the PDF's own notation (e.g. "EMA200") for
    display/audit regardless of how it was parsed.
    """

    type: IndicatorType
    period: int
    label: str
    source: str = "close"
    params: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> IndicatorSpec:
        return IndicatorSpec(
            type=IndicatorType(data["type"]),
            period=int(data["period"]),
            label=str(data.get("label", data["type"])),
            source=str(data.get("source", "close")),
            params={k: float(v) for k, v in dict(data.get("params", {})).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "period": self.period,
            "label": self.label,
            "source": self.source,
            "params": dict(self.params),
        }


class AnnotationType(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    LEVEL = "level"  # explicit numeric level with no clear support/resistance framing


@dataclass(frozen=True)
class PriceLevelAnnotation:
    """An explicit numeric price level the text states outright (e.g.
    "resistance at 2050") — the only kind of drawing-tool mention this
    pipeline ever turns into chart geometry. Never inferred or estimated."""

    type: AnnotationType
    price: float
    label: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> PriceLevelAnnotation:
        return PriceLevelAnnotation(
            type=AnnotationType(data["type"]),
            price=float(data["price"]),
            label=str(data.get("label", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "price": self.price, "label": self.label}


_LEGACY_INDICATOR_TOKEN_RE = re.compile(r"^(EMA|SMA|RSI)\s*\(?(\d+)\)?$", re.IGNORECASE)


def _legacy_indicator_from_token(token: str) -> IndicatorSpec | None:
    """Best-effort upgrade of an old plain-string indicator (e.g. "EMA200",
    "RSI(14)") — the shape written before indicators were structured —
    into `IndicatorSpec`. Returns None for anything it can't confidently
    parse; callers route those into `unrecognized_indicators` instead.
    """
    match = _LEGACY_INDICATOR_TOKEN_RE.match(token.strip())
    if not match:
        return None
    family, period = match.group(1).upper(), int(match.group(2))
    return IndicatorSpec(type=IndicatorType(family.lower()), period=period, label=token)


@dataclass(frozen=True)
class ExtractedStrategySpec:
    """What the `extract_method_from_pdf` prompt produces — the human-reviewable
    contract between the PDF and the generated code. Never executed directly.
    """

    name: str
    symbols: tuple[str, ...]
    entry_timeframe: str
    confirmation_timeframes: tuple[str, ...]
    indicators: tuple[IndicatorSpec, ...]
    entry_rules: str
    exit_rules: str
    risk_notes: str
    params: dict[str, Any] = field(default_factory=dict)
    unrecognized_indicators: tuple[str, ...] = ()
    price_levels: tuple[PriceLevelAnnotation, ...] = ()
    chart_notes: tuple[str, ...] = ()

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ExtractedStrategySpec:
        indicators: list[IndicatorSpec] = []
        unrecognized: list[str] = list(data.get("unrecognized_indicators", []))
        for entry in data.get("indicators", []):
            if isinstance(entry, dict):
                indicators.append(IndicatorSpec.from_dict(entry))
                continue
            # Legacy shape: a plain string like "EMA200" from before indicators
            # were structured (old drafts/versions persisted this way).
            parsed = _legacy_indicator_from_token(str(entry))
            if parsed is not None:
                indicators.append(parsed)
            else:
                unrecognized.append(str(entry))

        return ExtractedStrategySpec(
            name=str(data["name"]),
            symbols=tuple(data.get("symbols", [])),
            entry_timeframe=str(data.get("entry_timeframe", "M5")),
            confirmation_timeframes=tuple(data.get("confirmation_timeframes", [])),
            indicators=tuple(indicators),
            entry_rules=str(data.get("entry_rules", "")),
            exit_rules=str(data.get("exit_rules", "")),
            risk_notes=str(data.get("risk_notes", "")),
            params=dict(data.get("params", {})),
            unrecognized_indicators=tuple(unrecognized),
            price_levels=tuple(
                PriceLevelAnnotation.from_dict(level) for level in data.get("price_levels", [])
            ),
            chart_notes=tuple(data.get("chart_notes", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "symbols": list(self.symbols),
            "entry_timeframe": self.entry_timeframe,
            "confirmation_timeframes": list(self.confirmation_timeframes),
            "indicators": [i.to_dict() for i in self.indicators],
            "entry_rules": self.entry_rules,
            "exit_rules": self.exit_rules,
            "risk_notes": self.risk_notes,
            "params": dict(self.params),
            "unrecognized_indicators": list(self.unrecognized_indicators),
            "price_levels": [level.to_dict() for level in self.price_levels],
            "chart_notes": list(self.chart_notes),
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
