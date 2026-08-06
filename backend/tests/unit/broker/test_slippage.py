"""Slippage calibration and application (OBSERVABILITY_PLAN.md Phase 4)."""

from __future__ import annotations

import pytest

from src.broker.domain.slippage import (
    FALLBACK_MEAN_POINTS,
    FALLBACK_STDDEV_POINTS,
    MIN_CALIBRATION_SAMPLES,
    SlippageProfile,
    SlippageSampler,
    apply_slippage,
    calibrate_slippage,
)
from src.broker.domain.trading import Side, execution_slippage

XAUUSD_POINT = 0.01


class TestCalibration:
    def test_uses_the_documented_fallback_when_there_is_no_live_data(self) -> None:
        profile = calibrate_slippage("XAUUSD", (), point=XAUUSD_POINT)
        assert profile.source == "fallback"
        assert profile.calibrated is False
        assert profile.sample_count == 0
        assert profile.mean == pytest.approx(FALLBACK_MEAN_POINTS * XAUUSD_POINT)
        assert profile.stddev == pytest.approx(FALLBACK_STDDEV_POINTS * XAUUSD_POINT)

    def test_the_fallback_costs_the_trader_rather_than_assuming_a_free_fill(self) -> None:
        # Assuming zero slippage is what made backtests optimistic; the
        # fallback must be pessimistic, not neutral.
        assert calibrate_slippage("XAUUSD", (), point=XAUUSD_POINT).mean > 0.0

    def test_one_bad_fill_does_not_define_the_model(self) -> None:
        profile = calibrate_slippage("XAUUSD", (5.0,), point=XAUUSD_POINT)
        assert profile.source == "fallback"
        assert profile.sample_count == 1

    def test_calibrates_from_live_fills_once_there_are_enough(self) -> None:
        observed = [0.10] * MIN_CALIBRATION_SAMPLES
        profile = calibrate_slippage("XAUUSD", observed, point=XAUUSD_POINT)
        assert profile.source == "live"
        assert profile.calibrated is True
        assert profile.sample_count == MIN_CALIBRATION_SAMPLES
        assert profile.mean == pytest.approx(0.10)
        assert profile.stddev == pytest.approx(0.0)

    def test_live_mean_and_stddev_match_the_observed_distribution(self) -> None:
        observed = [0.0, 0.2] * (MIN_CALIBRATION_SAMPLES // 2)
        profile = calibrate_slippage("XAUUSD", observed, point=XAUUSD_POINT)
        assert profile.mean == pytest.approx(0.1)
        assert profile.stddev > 0.0


class TestApplication:
    def test_a_buy_pays_more_and_a_sell_receives_less(self) -> None:
        assert apply_slippage(Side.BUY, 2400.0, 0.30) == pytest.approx(2400.30)
        assert apply_slippage(Side.SELL, 2400.0, 0.30) == pytest.approx(2399.70)

    def test_price_improvement_improves_the_fill_on_both_sides(self) -> None:
        assert apply_slippage(Side.BUY, 2400.0, -0.30) == pytest.approx(2399.70)
        assert apply_slippage(Side.SELL, 2400.0, -0.30) == pytest.approx(2400.30)

    @pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
    @pytest.mark.parametrize("slippage", [0.30, -0.30, 0.0])
    def test_is_the_exact_inverse_of_the_phase_3_measurement(
        self, side: Side, slippage: float
    ) -> None:
        """The two functions must agree on the sign convention, or a backtest's
        modelled slippage cannot be compared with the live measurement it was
        calibrated from — which is the whole point of the divergence report."""
        fill = apply_slippage(side, 2400.0, slippage)
        assert execution_slippage(side, 2400.0, fill) == pytest.approx(slippage)


class TestSampler:
    def test_same_seed_produces_the_same_sequence(self) -> None:
        profile = calibrate_slippage("XAUUSD", (), point=XAUUSD_POINT)
        a = SlippageSampler(profile, seed=7)
        b = SlippageSampler(profile, seed=7)
        assert [a.sample() for _ in range(5)] == [b.sample() for _ in range(5)]

    def test_different_seeds_produce_different_sequences(self) -> None:
        profile = calibrate_slippage("XAUUSD", (), point=XAUUSD_POINT)
        a = SlippageSampler(profile, seed=1)
        b = SlippageSampler(profile, seed=2)
        assert [a.sample() for _ in range(5)] != [b.sample() for _ in range(5)]

    def test_a_zero_stddev_profile_always_returns_its_mean(self) -> None:
        profile = SlippageProfile(
            symbol="XAUUSD", mean=0.05, stddev=0.0, sample_count=100, source="live"
        )
        sampler = SlippageSampler(profile)
        assert [sampler.sample() for _ in range(10)] == [0.05] * 10

    def test_draws_are_clipped_so_one_outlier_cannot_dominate_a_run(self) -> None:
        profile = SlippageProfile(
            symbol="XAUUSD", mean=0.10, stddev=0.05, sample_count=100, source="live"
        )
        sampler = SlippageSampler(profile, seed=99)
        draws = [sampler.sample() for _ in range(2000)]
        assert min(draws) >= 0.10 - 3.0 * 0.05 - 1e-12
        assert max(draws) <= 0.10 + 3.0 * 0.05 + 1e-12

    def test_the_default_seed_is_fixed_so_backtests_stay_reproducible(self) -> None:
        profile = calibrate_slippage("XAUUSD", (), point=XAUUSD_POINT)
        a = SlippageSampler(profile)
        b = SlippageSampler(profile)
        assert [a.sample() for _ in range(20)] == [b.sample() for _ in range(20)]
