"""Custom indicator CRUD + on-demand computation.

Unlike `strategies.application.versioning.StrategyVersionService`, there is
no versioning/activation lifecycle here: an indicator is a single row edited
in place, since it never trades and is never registered live — the only
safety gate is the sandbox re-validating on every save and every compute.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd

from src.backtest.application.period import InvalidPeriod, parse_period
from src.indicators.adapters.repository import IndicatorRepository
from src.indicators.domain.models import IndicatorComputeResult, IndicatorDefinition
from src.indicators.sandbox import validate_and_load
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Candle, Timeframe

# Sentinel for `edit`'s `default_params` kwarg, distinguishing "not given,
# keep the existing value" from an explicit `default_params={}` (clear it).
_UNSET = object()


class IndicatorValidationError(Exception):
    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class IndicatorNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"indicator name {name!r} is already in use")
        self.name = name


class IndicatorService:
    def __init__(
        self, repository: IndicatorRepository, candle_repository: CandleRepository
    ) -> None:
        self._repository = repository
        self._candle_repository = candle_repository

    def create(
        self, *, name: str, code: str, default_params: dict[str, float] | None = None
    ) -> IndicatorDefinition:
        instance, errors = validate_and_load(code)
        if instance is None:
            raise IndicatorValidationError(errors)
        if self._repository.get_by_name(name) is not None:
            raise IndicatorNameConflictError(name)

        now = datetime.now(UTC)
        definition = IndicatorDefinition(
            id=str(uuid.uuid4()),
            name=name,
            code=code,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            default_params=default_params or {},
            created_at=now,
            updated_at=now,
        )
        self._repository.save(definition)
        return definition

    def edit(
        self,
        indicator_id: str,
        code: str,
        *,
        default_params: dict[str, float] | None | object = _UNSET,
    ) -> IndicatorDefinition:
        """Re-validates `code` in the sandbox and, if it passes, updates this
        indicator's row in place — no new row, no version history, since
        indicators carry no live-trading risk to roll back from. Raises
        `ValueError` if `indicator_id` doesn't exist, and
        `IndicatorValidationError` if `code` fails sandbox validation —
        nothing is written in that case."""
        existing = self._repository.get(indicator_id)
        if existing is None:
            raise ValueError(f"no indicator with id {indicator_id!r}")

        instance, errors = validate_and_load(code)
        if instance is None:
            raise IndicatorValidationError(errors)

        effective_params = (
            existing.default_params if default_params is _UNSET else (default_params or {})
        )
        updated = replace(
            existing,
            code=code,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            default_params=effective_params,
            updated_at=datetime.now(UTC),
        )
        self._repository.save(updated)
        return updated

    def duplicate(self, indicator_id: str, *, new_name: str) -> IndicatorDefinition:
        source = self._repository.get(indicator_id)
        if source is None:
            raise ValueError(f"no indicator with id {indicator_id!r}")
        if self._repository.get_by_name(new_name) is not None:
            raise IndicatorNameConflictError(new_name)

        now = datetime.now(UTC)
        duplicated = IndicatorDefinition(
            id=str(uuid.uuid4()),
            name=new_name,
            code=source.code,
            code_hash=source.code_hash,
            default_params=dict(source.default_params),
            created_at=now,
            updated_at=now,
        )
        self._repository.save(duplicated)
        return duplicated

    def delete(self, indicator_id: str) -> None:
        if self._repository.get(indicator_id) is None:
            raise ValueError(f"no indicator with id {indicator_id!r}")
        self._repository.delete(indicator_id)

    def list_all(self) -> list[IndicatorDefinition]:
        return self._repository.list_all()

    def get(self, indicator_id: str) -> IndicatorDefinition | None:
        return self._repository.get(indicator_id)

    def compute(
        self,
        indicator_id: str,
        *,
        symbol: str,
        timeframe: str,
        period: str,
        params: dict[str, float] | None = None,
    ) -> IndicatorComputeResult:
        definition = self._repository.get(indicator_id)
        if definition is None:
            raise ValueError(f"no indicator with id {indicator_id!r}")
        effective_params = {**definition.default_params, **(params or {})}
        return self._compute_code(
            definition.code,
            symbol=symbol,
            timeframe=timeframe,
            period=period,
            params=effective_params,
        )

    def preview(
        self,
        code: str,
        *,
        symbol: str,
        timeframe: str,
        period: str,
        params: dict[str, float] | None = None,
    ) -> IndicatorComputeResult:
        """Stateless: validates and runs `code` against real candle history
        without persisting anything — used by the create/edit UI's "Preview"
        button before saving (mirrors `POST /strategies/evaluate-custom`)."""
        return self._compute_code(
            code, symbol=symbol, timeframe=timeframe, period=period, params=params or {}
        )

    def _compute_code(
        self,
        code: str,
        *,
        symbol: str,
        timeframe: str,
        period: str,
        params: dict[str, float],
    ) -> IndicatorComputeResult:
        instance, errors = validate_and_load(code)
        if instance is None:
            return IndicatorComputeResult(times=[], series={}, error="; ".join(errors))

        try:
            start, end = parse_period(period)
        except InvalidPeriod as exc:
            return IndicatorComputeResult(times=[], series={}, error=str(exc))

        try:
            tf_enum = Timeframe(timeframe)
        except ValueError:
            return IndicatorComputeResult(
                times=[], series={}, error=f"unknown timeframe: {timeframe!r}"
            )

        candles = self._candle_repository.get_range(symbol, tf_enum, start, end)
        if not candles:
            return IndicatorComputeResult(
                times=[], series={}, error=f"no candles found for {symbol} in the requested range"
            )

        df = _candles_to_dataframe(candles)
        try:
            raw_series = instance.compute(df, params)
        except Exception as exc:
            return IndicatorComputeResult(times=[], series={}, error=f"compute() raised: {exc!r}")

        times = [int(c.time.timestamp()) for c in candles]
        series: dict[str, list[float | None]] = {}
        for series_name, values in raw_series.items():
            values_list = list(values)
            cleaned: list[float | None] = []
            for i in range(len(candles)):
                value = values_list[i] if i < len(values_list) else None
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    cleaned.append(None)
                else:
                    cleaned.append(float(value))
            series[series_name] = cleaned
        return IndicatorComputeResult(times=times, series=series, error=None)


def _candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "tick_volume": [c.tick_volume for c in candles],
        }
    )
