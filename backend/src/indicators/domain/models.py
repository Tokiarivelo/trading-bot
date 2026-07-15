"""Custom indicator contract and bookkeeping record.

An `Indicator` is user- or AI-written Python that turns a candle DataFrame
into one or more named numeric series for the chart (e.g. `{"value": [...]}`
for a single line, `{"upper": [...], "lower": [...]}` for a band). Unlike
`strategies.domain.models.Strategy`, indicators never place trades and are
never registered live — they're computed on demand for chart display, so
there is no versioning/activation lifecycle here, just a single mutable
record edited in place (see `IndicatorDefinition`).

`candles` is typed loosely (not `pandas.DataFrame`) so this module stays
import-light, matching `strategies/domain/models.py`'s same choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Indicator(Protocol):
    def compute(
        self, candles: Any, params: dict[str, float]
    ) -> dict[str, list[float | None]]: ...


@dataclass(frozen=True)
class IndicatorDefinition:
    id: str
    name: str
    code: str
    code_hash: str
    default_params: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class IndicatorComputeResult:
    """Result of running an indicator's `compute()` against real candle
    history (`IndicatorService.compute`/`.preview`) — `error` is set instead
    of `series` being populated on sandbox rejection, missing history, or a
    runtime exception, so callers (the chart, the preview UI) can render a
    clear message instead of guessing from an empty result."""

    times: list[int]
    series: dict[str, list[float | None]]
    error: str | None
