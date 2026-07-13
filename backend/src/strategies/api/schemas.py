"""Wire models for strategy versioning/activation (§6.5, §8.1). Mirrors
`strategies/domain/versioning.py`; the domain stays framework-free.

`StrategySpecSnapshotOut` intentionally duplicates the shape of
`ai/api/schemas.py: ExtractedStrategySpecSchema` rather than importing it —
api/schemas.py mirrors this module's own domain, it never reaches into
another module's internals (see CLAUDE.md "Architecture").
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from src.strategies.domain.versioning import CodeSource, StrategyVersion, VersionStatus

# Recognizes the old pre-structured indicator shape ("EMA200", "RSI(14)") so
# `StrategyVersion.spec` rows written before indicators became structured
# objects still deserialize instead of 500ing GET /strategies/versions. Kept
# as an independent copy of `ai/domain/models.py`'s equivalent regex — this
# module never imports from `ai/` (see module docstring above).
_LEGACY_INDICATOR_TOKEN_RE = re.compile(r"^(EMA|SMA|RSI)\s*\(?(\d+)\)?$", re.IGNORECASE)


class IndicatorSpecOut(BaseModel):
    """One indicator recognized into a plottable family (ema/sma/rsi/macd/
    bollinger) — mirrors `ai/api/schemas.py: IndicatorSpecSchema`."""

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


class PriceLevelAnnotationOut(BaseModel):
    """An explicit numeric price level the source text states outright —
    mirrors `ai/api/schemas.py: PriceLevelAnnotationSchema`."""

    type: str = Field(description="One of: support, resistance, level.")
    price: float = Field(description="The literal price level from the text.")
    label: str = Field(description="The level as written in the source text.")


class StrategySpecSnapshotOut(BaseModel):
    name: str = Field(description="Short snake_case slug, e.g. 'gold_ema_pullback'.")
    symbols: list[str] = Field(description="Symbols this method applies to.")
    entry_timeframe: str = Field(description="Entry timeframe — always 'M5' for this project.")
    confirmation_timeframes: list[str] = Field(description="Higher timeframes used to confirm.")
    indicators: list[IndicatorSpecOut] = Field(
        description="Indicators recognized into one of the 5 plottable families."
    )
    entry_rules: str = Field(description="Plain-English entry logic.")
    exit_rules: str = Field(description="Plain-English exit logic.")
    risk_notes: str = Field(description="Informational only — real caps live in risk.yaml.")
    params: dict[str, Any] = Field(default_factory=dict, description="Numeric parameters.")
    unrecognized_indicators: list[str] = Field(
        default_factory=list,
        description="Indicator names that don't map onto one of the 5 plottable families — "
        "display/audit only, never rendered on the chart.",
    )
    price_levels: list[PriceLevelAnnotationOut] = Field(
        default_factory=list,
        description="Explicit numeric support/resistance/pivot levels — rendered as locked "
        "horizontal lines on the chart.",
    )
    chart_notes: list[str] = Field(
        default_factory=list,
        description="Other charting/drawing-tool mentions with no explicit number attached — "
        "informational only, never rendered as geometry.",
    )


def _coerce_legacy_spec_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a `StrategyVersion.spec` dict written before indicators were
    structured (plain `indicators: list[str]`, no `unrecognized_indicators`/
    `price_levels`/`chart_notes`) so it still validates against the current
    `StrategySpecSnapshotOut`. Specs already in the new shape pass through
    unchanged (each `indicators` entry is already a dict)."""
    indicators = raw.get("indicators", [])
    if indicators and all(isinstance(entry, str) for entry in indicators):
        parsed: list[dict[str, Any]] = []
        unrecognized: list[str] = list(raw.get("unrecognized_indicators", []))
        for token in indicators:
            match = _LEGACY_INDICATOR_TOKEN_RE.match(str(token).strip())
            if match:
                family, period = match.group(1).lower(), int(match.group(2))
                parsed.append({"type": family, "period": period, "label": token})
            else:
                unrecognized.append(str(token))
        return {**raw, "indicators": parsed, "unrecognized_indicators": unrecognized}
    return raw


class StrategyVersionOut(BaseModel):
    id: str = Field(description="Version id, used in every other /strategies/versions endpoint.")
    name: str = Field(description="Strategy family name — versions of the same strategy share it.")
    version: int = Field(description="1-based version number within this name.")
    file_path: str = Field(description="Path under backend/ where the source file lives.")
    code_hash: str = Field(description="SHA-256 of the source, for change detection/audit.")
    source: CodeSource = Field(
        description="'ai_generated' (via PDF pipeline), 'ai_refined' (via the 10-trade "
        "self-refinement loop), or 'manual'."
    )
    status: VersionStatus = Field(
        description="'validated' (passed the sandbox, not live), 'active' (registered in the "
        "StrategyRegistry and tradeable), or 'archived' (was active, superseded)."
    )
    paused: bool = Field(
        description="Only meaningful while status is 'active': true if the version is "
        "suspended from live evaluation via POST .../pause without being deactivated. "
        "Distinct from the engine-wide kill switch, which pauses every strategy at once."
    )
    created_at: int = Field(description="Epoch seconds UTC.")
    parent_version_id: str | None = Field(
        description="The version this one supersedes, if any — the rollback/diff chain."
    )
    draft_id: str | None = Field(
        description="The AI draft this came from, if source is ai_generated."
    )
    spec: StrategySpecSnapshotOut | None = Field(
        description="The StrategySpec this version was generated from, if source is ai_generated."
    )
    backtest_report_id: str | None = Field(
        description="Id of the backtest run when this version was generated (GET "
        "/backtest/reports/{id}), if one was run."
    )

    @staticmethod
    def from_domain(version: StrategyVersion) -> StrategyVersionOut:
        return StrategyVersionOut(
            id=version.id,
            name=version.name,
            version=version.version,
            file_path=version.file_path,
            code_hash=version.code_hash,
            source=version.source,
            status=version.status,
            paused=version.paused,
            created_at=int(version.created_at.timestamp()),
            parent_version_id=version.parent_version_id,
            draft_id=version.draft_id,
            spec=(
                StrategySpecSnapshotOut(**_coerce_legacy_spec_dict(version.spec))
                if version.spec
                else None
            ),
            backtest_report_id=version.backtest_report_id,
        )


class DuplicateVersionRequest(BaseModel):
    name: str = Field(
        description="New strategy family name for the duplicate — must not already be in "
        "use by another family, or the request is rejected."
    )
    symbols: list[str] | None = Field(
        default=None,
        description="Optional symbol list to retarget the duplicate to. Rewrites the "
        "`StrategySpec(symbols=...)` literal in the cloned source and re-validates it in "
        "the sandbox before saving; the request fails if no such literal can be found. "
        "Leave unset to duplicate with the same symbols as the source version. This never "
        "edits configs/app.yaml — the engine won't trade the new symbol live until a human "
        "adds it there separately.",
    )


class RenameVersionRequest(BaseModel):
    name: str = Field(
        description="New display name for this version's strategy family — applies to "
        "every version that currently shares the family's name, not just this one."
    )


class EditVersionCodeRequest(BaseModel):
    code: str = Field(
        description="Full replacement Python source for this strategy. Re-validated in the "
        "sandbox before saving; nothing is written if it fails."
    )
    new_name: str | None = Field(
        default=None,
        description="Leave unset to save as the next version of this version's own strategy "
        "family (the usual case). Set to a different, not-yet-used name to fork the edit into "
        "a brand-new strategy family at version 1 instead — the 'duplicate' save destination, "
        "for trying a change without touching the original. Rejected with 409 if the name is "
        "already in use by another family.",
    )


class StrategyVersionDetailOut(StrategyVersionOut):
    code: str = Field(description="The full generated Python source for this version.")

    @staticmethod
    def from_domain_with_code(version: StrategyVersion, code: str) -> StrategyVersionDetailOut:
        summary = StrategyVersionOut.from_domain(version).model_dump()
        return StrategyVersionDetailOut(**summary, code=code)
