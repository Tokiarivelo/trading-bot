"""Live-vs-backtest divergence (OBSERVABILITY_PLAN.md Phase 4).

The report exists to separate two failure modes that look identical from the
equity curve: the simulator filling better than the broker does, and the
strategy's edge having decayed. These tests pin that separation.
"""

from __future__ import annotations

import pytest

from src.backtest.domain.divergence import (
    MIN_SAMPLES_PER_SIDE,
    FillSample,
    compute_divergence,
)


def samples(
    n: int, *, profit: float, slippage: float | None = 0.0, volume: float = 0.1
) -> list[FillSample]:
    return [
        FillSample(profit=profit, volume=volume, slippage=slippage, r_multiple=profit)
        for _ in range(n)
    ]


def metric(report: object, name: str) -> object:
    return next(m for m in report.metrics if m.name == name)  # type: ignore[attr-defined]


class TestVerdicts:
    def test_matching_populations_are_aligned(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(20, profit=10.0, slippage=0.02),
            backtest=samples(20, profit=10.0, slippage=0.02),
        )
        assert report.verdict == "aligned"
        assert report.comparable is True
        assert not any(m.significant for m in report.metrics)

    def test_worse_live_fills_with_intact_results_blame_the_simulator(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(20, profit=10.0, slippage=0.50),
            backtest=samples(20, profit=10.0, slippage=0.02),
        )
        assert report.verdict == "simulator_optimistic"
        assert metric(report, "avg_slippage").significant is True  # type: ignore[attr-defined]
        assert "not achievable" in report.summary

    def test_matching_fills_with_collapsed_results_blame_the_edge(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(20, profit=-5.0, slippage=0.02),
            backtest=samples(20, profit=10.0, slippage=0.02),
        )
        assert report.verdict == "edge_decayed"
        assert metric(report, "win_rate").significant is True  # type: ignore[attr-defined]

    def test_both_diverging_refuses_to_attribute_the_outcome_gap(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(20, profit=-5.0, slippage=0.50),
            backtest=samples(20, profit=10.0, slippage=0.02),
        )
        assert report.verdict == "both"
        assert "cannot be attributed" in report.summary

    def test_too_few_trades_refuses_to_draw_a_conclusion(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(MIN_SAMPLES_PER_SIDE - 1, profit=-50.0),
            backtest=samples(200, profit=10.0),
        )
        assert report.verdict == "insufficient_data"
        assert report.comparable is False
        # The metrics are still returned so the UI can show what exists...
        assert len(report.metrics) > 0
        # ...but none of them is flagged as meaningful.
        assert not any(m.significant for m in report.metrics)


class TestFillRate:
    def test_a_broker_refusing_orders_the_simulator_accepts_is_the_headline(self) -> None:
        """The `stops_level` failure mode: the backtest fills nearly every
        signal, live fills a fifth of them."""
        report = compute_divergence(
            strategy="rbr_dbd_zones_scalp_vix75",
            symbol="Volatility 75 Index",
            live=samples(20, profit=10.0),
            backtest=samples(20, profit=10.0),
            live_signal_count=100,
            live_opened_count=20,
            backtest_signal_count=100,
            backtest_opened_count=95,
        )
        fill_rate = metric(report, "fill_rate")
        assert fill_rate.live_value == pytest.approx(0.20)  # type: ignore[attr-defined]
        assert fill_rate.backtest_value == pytest.approx(0.95)  # type: ignore[attr-defined]
        assert fill_rate.significant is True  # type: ignore[attr-defined]
        assert report.verdict == "simulator_optimistic"

    def test_fill_rate_is_absent_rather_than_guessed_when_counts_are_missing(self) -> None:
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=samples(20, profit=10.0),
            backtest=samples(20, profit=10.0),
        )
        fill_rate = metric(report, "fill_rate")
        assert fill_rate.live_value is None  # type: ignore[attr-defined]
        assert fill_rate.backtest_value is None  # type: ignore[attr-defined]
        assert fill_rate.significant is False  # type: ignore[attr-defined]


class TestMissingMeasurements:
    def test_unmeasured_slippage_is_excluded_not_counted_as_zero(self) -> None:
        """Trades journalled before slippage was recorded are missing data, not
        perfect fills — counting them as zero would drag the live mean toward
        the optimism the model exists to remove."""
        live = samples(10, profit=10.0, slippage=None) + samples(10, profit=10.0, slippage=0.5)
        report = compute_divergence(
            strategy="breakout_v1",
            symbol="XAUUSD",
            live=live,
            backtest=samples(20, profit=10.0, slippage=0.5),
        )
        slippage = metric(report, "avg_slippage")
        assert slippage.live_sample_count == 10  # type: ignore[attr-defined]
        assert slippage.live_value == pytest.approx(0.5)  # type: ignore[attr-defined]
        assert slippage.significant is False  # type: ignore[attr-defined]


def test_metric_deltas_are_live_minus_backtest() -> None:
    report = compute_divergence(
        strategy="breakout_v1",
        symbol="XAUUSD",
        live=samples(20, profit=4.0),
        backtest=samples(20, profit=10.0),
    )
    avg_profit = metric(report, "avg_profit")
    assert avg_profit.delta == pytest.approx(-6.0)  # type: ignore[attr-defined]
    assert avg_profit.relative_delta == pytest.approx(-0.6)  # type: ignore[attr-defined]


def test_computation_is_pure_and_repeatable() -> None:
    kwargs = {
        "strategy": "breakout_v1",
        "symbol": "XAUUSD",
        "live": samples(20, profit=4.0, slippage=0.3),
        "backtest": samples(20, profit=10.0, slippage=0.1),
    }
    assert compute_divergence(**kwargs) == compute_divergence(**kwargs)  # type: ignore[arg-type]
