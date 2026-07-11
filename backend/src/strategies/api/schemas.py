"""Wire models for strategy versioning/activation (§6.5, §8.1). Mirrors
`strategies/domain/versioning.py`; the domain stays framework-free.

`StrategySpecSnapshotOut` intentionally duplicates the shape of
`ai/api/schemas.py: ExtractedStrategySpecSchema` rather than importing it —
api/schemas.py mirrors this module's own domain, it never reaches into
another module's internals (see CLAUDE.md "Architecture").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.strategies.domain.versioning import CodeSource, StrategyVersion, VersionStatus


class StrategySpecSnapshotOut(BaseModel):
    name: str = Field(description="Short snake_case slug, e.g. 'gold_ema_pullback'.")
    symbols: list[str] = Field(description="Symbols this method applies to.")
    entry_timeframe: str = Field(description="Entry timeframe — always 'M5' for this project.")
    confirmation_timeframes: list[str] = Field(description="Higher timeframes used to confirm.")
    indicators: list[str] = Field(description="Indicator names used.")
    entry_rules: str = Field(description="Plain-English entry logic.")
    exit_rules: str = Field(description="Plain-English exit logic.")
    risk_notes: str = Field(description="Informational only — real caps live in risk.yaml.")
    params: dict[str, Any] = Field(default_factory=dict, description="Numeric parameters.")


class StrategyVersionOut(BaseModel):
    id: str = Field(description="Version id, used in every other /strategies/versions endpoint.")
    name: str = Field(description="Strategy family name — versions of the same strategy share it.")
    version: int = Field(description="1-based version number within this name.")
    file_path: str = Field(description="Path under backend/ where the source file lives.")
    code_hash: str = Field(description="SHA-256 of the source, for change detection/audit.")
    source: CodeSource = Field(description="'ai_generated' (via PDF pipeline) or 'manual'.")
    status: VersionStatus = Field(
        description="'validated' (passed the sandbox, not live), 'active' (registered in the "
        "StrategyRegistry and tradeable), or 'archived' (was active, superseded)."
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
            created_at=int(version.created_at.timestamp()),
            parent_version_id=version.parent_version_id,
            draft_id=version.draft_id,
            spec=StrategySpecSnapshotOut(**version.spec) if version.spec else None,
            backtest_report_id=version.backtest_report_id,
        )


class StrategyVersionDetailOut(StrategyVersionOut):
    code: str = Field(description="The full generated Python source for this version.")

    @staticmethod
    def from_domain_with_code(version: StrategyVersion, code: str) -> StrategyVersionDetailOut:
        summary = StrategyVersionOut.from_domain(version).model_dump()
        return StrategyVersionDetailOut(**summary, code=code)
