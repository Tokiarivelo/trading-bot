"""Wire models for custom indicators. Mirrors `strategies/api/schemas.py`'s
`StrategyVersionOut`/`StrategyVersionDetailOut` split; the domain stays
framework-free (no pydantic imports in `domain/`)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.indicators.domain.models import IndicatorComputeResult, IndicatorDefinition


class IndicatorOut(BaseModel):
    id: str = Field(description="Indicator id, used in every other /indicators endpoint.")
    name: str = Field(description="Unique display name shown in the chart's indicator picker.")
    code_hash: str = Field(description="SHA-256 of the source, for change detection/audit.")
    default_params: dict[str, float] = Field(
        description="Default parameter values (e.g. {'period': 20}) passed into compute() "
        "when a caller doesn't override them."
    )
    created_at: int = Field(description="Epoch seconds UTC.")
    updated_at: int = Field(description="Epoch seconds UTC — bumped on every edit.")

    @staticmethod
    def from_domain(definition: IndicatorDefinition) -> IndicatorOut:
        return IndicatorOut(
            id=definition.id,
            name=definition.name,
            code_hash=definition.code_hash,
            default_params=definition.default_params,
            created_at=int(definition.created_at.timestamp()),
            updated_at=int(definition.updated_at.timestamp()),
        )


class IndicatorDetailOut(IndicatorOut):
    code: str = Field(description="The full Python source for this indicator.")

    @staticmethod
    def from_domain(definition: IndicatorDefinition) -> IndicatorDetailOut:
        summary = IndicatorOut.from_domain(definition).model_dump()
        return IndicatorDetailOut(**summary, code=definition.code)


class CreateIndicatorRequest(BaseModel):
    name: str = Field(description="Unique display name — rejected with 409 if already in use.")
    code: str = Field(
        description="Python source defining a class with a `compute(candles, params) -> "
        "dict[str, list[float | None]]` method. Sandbox-validated before saving; imports "
        "limited to math/statistics/numpy/pandas, no I/O or network."
    )
    default_params: dict[str, float] = Field(
        default_factory=dict,
        description="Default parameter values passed into compute() when a caller doesn't "
        "override them, e.g. {'period': 20}.",
    )


class EditIndicatorRequest(BaseModel):
    code: str = Field(
        description="Full replacement Python source. Re-validated in the sandbox before "
        "saving; nothing is written if it fails. Unlike strategy versions, this updates the "
        "indicator's row in place — indicators carry no live-trading risk to roll back from."
    )
    default_params: dict[str, float] | None = Field(
        default=None,
        description="New default parameter values. Omit to keep the indicator's existing "
        "defaults unchanged.",
    )


class DuplicateIndicatorRequest(BaseModel):
    name: str = Field(
        description="New name for the duplicate — must not already be in use, or the "
        "request is rejected with 409."
    )


class ComputeIndicatorRequest(BaseModel):
    symbol: str = Field(description="Symbol to compute the indicator over, e.g. 'XAUUSD'.")
    timeframe: str = Field(description="Candle timeframe, e.g. 'M5', 'H1'.")
    period: str = Field(description="History window as 'YYYY-MM:YYYY-MM', e.g. '2026-06:2026-07'.")
    params: dict[str, float] | None = Field(
        default=None,
        description="Per-call parameter overrides merged on top of the indicator's stored "
        "default_params.",
    )


class PreviewIndicatorRequest(BaseModel):
    code: str = Field(description="Ad-hoc Python source to validate and run, not persisted.")
    params: dict[str, float] = Field(
        default_factory=dict, description="Parameters passed into compute()."
    )
    symbol: str = Field(description="Symbol to compute the indicator over, e.g. 'XAUUSD'.")
    timeframe: str = Field(description="Candle timeframe, e.g. 'M5', 'H1'.")
    period: str = Field(description="History window as 'YYYY-MM:YYYY-MM', e.g. '2026-06:2026-07'.")


class ComputeIndicatorResponseOut(BaseModel):
    times: list[int] = Field(description="Epoch-seconds UTC bar-open time for each point.")
    series: dict[str, list[float | None]] = Field(
        description="One or more named output series (e.g. {'value': [...]} for a single "
        "line, {'upper': [...], 'lower': [...]} for a band), each aligned 1:1 with `times`. "
        "`null` entries are warm-up gaps (e.g. before a moving average has enough bars)."
    )
    error: str | None = Field(
        description="Set instead of `series` being populated when the code failed sandbox "
        "validation, the symbol/period had no candle history, or compute() raised at runtime."
    )

    @staticmethod
    def from_result(result: IndicatorComputeResult) -> ComputeIndicatorResponseOut:
        return ComputeIndicatorResponseOut(
            times=result.times, series=result.series, error=result.error
        )
