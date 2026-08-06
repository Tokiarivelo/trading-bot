"""Live-vs-backtest divergence (OBSERVABILITY_PLAN.md Phase 4, deliverable 3).

A backtest is a claim about the future. This module checks the claim against
what actually happened, for the same strategy on the same symbol, and reports
where the two disagree.

Two kinds of disagreement matter and they have opposite remedies:

* **the simulator is lying** — live fills are worse than simulated ones
  (slippage, spread, fill rate). Fix the simulator; the strategy may be fine.
* **the edge decayed** — fills match but the outcomes don't (win rate,
  expectancy). The simulator is honest and the strategy has stopped working,
  or was overfit to its backtest window.

They are told apart by *which* metrics diverge, which is why execution
metrics and outcome metrics are labelled separately below rather than being
averaged into one score.

Pure aggregation — no I/O, no framework, no ORM. The caller supplies both
sides as flat samples; where they came from (journal rows, a report file) is
the API layer's problem.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# A metric needs at least this many samples on *both* sides before its
# divergence means anything. Three live trades and a 400-trade backtest will
# always "diverge"; saying so would be noise.
MIN_SAMPLES_PER_SIDE = 5

# Relative gap at which a metric is called out. 0.25 = the live value is more
# than 25% away from the backtested one — big enough to ignore ordinary
# sampling noise on a few dozen trades, small enough to catch a simulator that
# is systematically optimistic.
SIGNIFICANT_RELATIVE_GAP = 0.25

KIND_EXECUTION = "execution"
KIND_OUTCOME = "outcome"


@dataclass(frozen=True, kw_only=True)
class FillSample:
    """One comparable fill, from either side of the comparison.

    Deliberately minimal and shared by both sides: only fields a backtest and
    the live journal can *both* supply are here, because a metric that exists
    on one side only cannot diverge, it can only be missing."""

    profit: float
    volume: float
    slippage: float | None = None
    """Signed, positive = cost the trader. `None` on live trades journalled
    before Phase 3 started measuring it; those are excluded from the slippage
    metric rather than counted as zero."""
    r_multiple: float | None = None


@dataclass(frozen=True, kw_only=True)
class DivergenceMetric:
    """One measurement compared across the two runs."""

    name: str
    kind: str  # KIND_EXECUTION | KIND_OUTCOME
    live_value: float | None
    backtest_value: float | None
    delta: float | None  # live - backtest
    relative_delta: float | None  # delta / |backtest|, None when backtest is 0
    significant: bool
    live_sample_count: int
    backtest_sample_count: int
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class DivergenceReport:
    strategy: str
    symbol: str
    live_trade_count: int
    backtest_trade_count: int
    comparable: bool
    """False when either side has fewer than `MIN_SAMPLES_PER_SIDE` trades —
    the metrics are still returned so the UI can show what exists, but no
    conclusion should be drawn from them."""
    metrics: tuple[DivergenceMetric, ...]
    verdict: str
    summary: str


def compute_divergence(
    *,
    strategy: str,
    symbol: str,
    live: Sequence[FillSample],
    backtest: Sequence[FillSample],
    live_signal_count: int | None = None,
    live_opened_count: int | None = None,
    backtest_signal_count: int | None = None,
    backtest_opened_count: int | None = None,
) -> DivergenceReport:
    """Compare a live trade population against a backtested one.

    The optional signal/opened counts add the **fill rate** metric — of the
    signals each side produced, what fraction became positions. It is the
    single most diagnostic number here: a backtest that fills 95% of its
    signals while live fills 20% is not modelling the broker, which is exactly
    the `stops_level` failure this phase was built around. Both counts must be
    supplied for a side for that metric to be computed."""
    metrics: list[DivergenceMetric] = []
    live_n, backtest_n = len(live), len(backtest)
    comparable = live_n >= MIN_SAMPLES_PER_SIDE and backtest_n >= MIN_SAMPLES_PER_SIDE

    metrics.append(
        _metric(
            "fill_rate",
            KIND_EXECUTION,
            _ratio(live_opened_count, live_signal_count),
            _ratio(backtest_opened_count, backtest_signal_count),
            live_signal_count or 0,
            backtest_signal_count or 0,
            note="signals that became positions; a live rate far below the "
            "simulated one means the broker is refusing orders the "
            "simulator accepts",
        )
    )
    metrics.append(
        _metric(
            "avg_slippage",
            KIND_EXECUTION,
            _mean([s.slippage for s in live if s.slippage is not None]),
            _mean([s.slippage for s in backtest if s.slippage is not None]),
            sum(1 for s in live if s.slippage is not None),
            sum(1 for s in backtest if s.slippage is not None),
            note="price units, positive = cost the trader; a positive delta "
            "means the slippage model is calibrated too optimistically",
        )
    )
    metrics.append(
        _metric(
            "win_rate",
            KIND_OUTCOME,
            _win_rate(live),
            _win_rate(backtest),
            live_n,
            backtest_n,
            note="a matching fill rate with a collapsed win rate points at "
            "edge decay rather than at the simulator",
        )
    )
    metrics.append(
        _metric(
            "avg_profit",
            KIND_OUTCOME,
            _mean([s.profit for s in live]),
            _mean([s.profit for s in backtest]),
            live_n,
            backtest_n,
            note="account currency per trade",
        )
    )
    metrics.append(
        _metric(
            "avg_r",
            KIND_OUTCOME,
            _mean([s.r_multiple for s in live if s.r_multiple is not None]),
            _mean([s.r_multiple for s in backtest if s.r_multiple is not None]),
            sum(1 for s in live if s.r_multiple is not None),
            sum(1 for s in backtest if s.r_multiple is not None),
            note="risk-normalised, so it survives the two sides trading "
            "different lot sizes",
        )
    )
    metrics.append(
        _metric(
            "avg_volume",
            KIND_EXECUTION,
            _mean([s.volume for s in live]),
            _mean([s.volume for s in backtest]),
            live_n,
            backtest_n,
            note="lots; a gap here usually means the two ran on different "
            "account balances, and makes the currency metrics above "
            "incomparable",
        )
    )

    verdict, summary = _verdict(
        metrics, comparable=comparable, live_n=live_n, backtest_n=backtest_n
    )
    return DivergenceReport(
        strategy=strategy,
        symbol=symbol,
        live_trade_count=live_n,
        backtest_trade_count=backtest_n,
        comparable=comparable,
        metrics=tuple(metrics),
        verdict=verdict,
        summary=summary,
    )


def _metric(
    name: str,
    kind: str,
    live_value: float | None,
    backtest_value: float | None,
    live_n: int,
    backtest_n: int,
    *,
    note: str,
) -> DivergenceMetric:
    both_present = live_value is not None and backtest_value is not None
    delta = live_value - backtest_value if both_present else None
    relative = (
        delta / abs(backtest_value)
        if delta is not None and backtest_value not in (None, 0.0)
        else None
    )
    significant = (
        relative is not None
        and abs(relative) >= SIGNIFICANT_RELATIVE_GAP
        and live_n >= MIN_SAMPLES_PER_SIDE
        and backtest_n >= MIN_SAMPLES_PER_SIDE
    )
    return DivergenceMetric(
        name=name,
        kind=kind,
        live_value=live_value,
        backtest_value=backtest_value,
        delta=delta,
        relative_delta=relative,
        significant=significant,
        live_sample_count=live_n,
        backtest_sample_count=backtest_n,
        note=note,
    )


def _verdict(
    metrics: Sequence[DivergenceMetric], *, comparable: bool, live_n: int, backtest_n: int
) -> tuple[str, str]:
    """Which of the two failure modes the divergence pattern points at.

    Execution metrics diverging first means the simulator is wrong; outcome
    metrics diverging alone means the edge went. Both means the report cannot
    separate them and says so, rather than guessing."""
    if not comparable:
        return (
            "insufficient_data",
            f"{live_n} live and {backtest_n} backtested trades — at least "
            f"{MIN_SAMPLES_PER_SIDE} of each are needed before a divergence "
            "means anything.",
        )
    execution = [m for m in metrics if m.kind == KIND_EXECUTION and m.significant]
    outcome = [m for m in metrics if m.kind == KIND_OUTCOME and m.significant]
    if execution and outcome:
        return (
            "both",
            "Execution and outcome both diverge ("
            + ", ".join(m.name for m in execution + outcome)
            + ") — fix the fill model first, then re-judge the edge; the "
            "outcome gap cannot be attributed until fills agree.",
        )
    if execution:
        return (
            "simulator_optimistic",
            "The simulator is filling better than the broker does ("
            + ", ".join(m.name for m in execution)
            + ") — the backtest's numbers are not achievable as-is.",
        )
    if outcome:
        return (
            "edge_decayed",
            "Fills agree but results do not ("
            + ", ".join(m.name for m in outcome)
            + ") — the simulation is honest and the strategy is "
            "underperforming its backtest.",
        )
    return ("aligned", "Live execution and results are within tolerance of the backtest.")


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def _win_rate(samples: Sequence[FillSample]) -> float | None:
    if not samples:
        return None
    return sum(1 for s in samples if s.profit > 0) / len(samples)


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator
