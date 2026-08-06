"""The backtest's simulated broker (OBSERVABILITY_PLAN.md Phase 4).

`BrokerConstraintSimulator` is what makes a backtest refuse the entries a live
MT5 server refuses — and, just as importantly, *count* them by reason, so a
strategy that would be 100% rejected live reports as such instead of showing
a clean equity curve.
"""

from __future__ import annotations

import pytest

from src.backtest.adapters.constraint_simulator import BrokerConstraintSimulator
from src.broker.domain.broker_constraints import (
    REASON_STOPS_LEVEL,
    REASON_VOLUME_BELOW_MIN,
    RETCODE_INVALID_STOPS,
    RETCODE_INVALID_VOLUME,
)
from src.broker.domain.slippage import SlippageProfile, SlippageSampler
from src.broker.domain.trading import OrderRejected, Side
from src.market_data.domain.models import SymbolInfo

VIX75_PRICE = 100_000.0


def vix75_info(spread_points: int = 40) -> SymbolInfo:
    """The broker's real facts for Volatility 75 Index: stops_level 10770 on a
    0.01 point, i.e. a 107.70-unit minimum stop distance, and a 0.001 lot
    step with a 0.01 minimum."""
    half = spread_points * 0.01 / 2
    return SymbolInfo(
        symbol="Volatility 75 Index",
        bid=VIX75_PRICE - half,
        ask=VIX75_PRICE + half,
        spread_points=spread_points,
        point=0.01,
        digits=2,
        stops_level=10770,
        contract_size=1.0,
        volume_min=0.01,
        volume_max=15.0,
        volume_step=0.001,
    )


def make_simulator(
    *, mean: float = 0.0, stddev: float = 0.0, **kwargs: object
) -> BrokerConstraintSimulator:
    profile = SlippageProfile(
        symbol="Volatility 75 Index",
        mean=mean,
        stddev=stddev,
        sample_count=100,
        source="live",
    )
    return BrokerConstraintSimulator(slippage=SlippageSampler(profile, seed=1), **kwargs)  # type: ignore[arg-type]


class TestStopsLevel:
    def test_an_m1_scalp_stop_on_vix75_is_refused_with_retcode_10016(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        with pytest.raises(OrderRejected) as excinfo:
            simulator.simulate_entry(
                symbol="Volatility 75 Index",
                side=Side.BUY,
                volume=0.05,
                sl=info.ask - 45.0,  # the ~30-70 unit stops that died live
                tp=info.ask + 500.0,
                info=info,
            )
        assert excinfo.value.retcode == RETCODE_INVALID_STOPS
        assert "107.70" in str(excinfo.value)

    def test_every_such_entry_is_counted_so_the_strategy_reads_as_unfillable(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        for _ in range(10):
            with pytest.raises(OrderRejected):
                simulator.simulate_entry(
                    symbol="Volatility 75 Index",
                    side=Side.SELL,
                    volume=0.05,
                    sl=info.bid + 45.0,
                    tp=info.bid - 500.0,
                    info=info,
                )
        assert simulator.accepted_count == 0
        assert simulator.rejected_count == 10
        (rejection,) = simulator.rejections()
        assert rejection.reason == REASON_STOPS_LEVEL
        assert rejection.count == 10
        assert rejection.retcode == RETCODE_INVALID_STOPS
        # A 100%-rejected strategy must report a 0% acceptance rate — the
        # number that makes "this backtest is fiction" obvious at a glance.
        assert rejection.example
        assert simulator.accepted_count / (simulator.accepted_count + 10) == 0.0

    def test_a_legal_swing_stop_on_the_same_symbol_still_fills(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 500.0,
            tp=info.ask + 1500.0,
            info=info,
        )
        assert entry.volume == pytest.approx(0.05)
        assert simulator.accepted_count == 1
        assert simulator.rejected_count == 0

    def test_clamping_widens_the_stop_instead_of_rejecting(self) -> None:
        simulator = make_simulator(clamp_stops=True)
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 45.0,
            tp=info.ask + 500.0,
            info=info,
        )
        assert entry.sl == pytest.approx(info.ask - 107.70)
        assert simulator.clamped_count == 1
        assert simulator.rejected_count == 0

    def test_enforcement_can_be_turned_off_entirely(self) -> None:
        simulator = make_simulator(enforce_stops_level=False)
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 1.0,
            tp=info.ask + 2.0,
            info=info,
        )
        assert entry.sl == pytest.approx(info.ask - 1.0)
        assert simulator.rejected_count == 0


class TestVolumeGrid:
    def test_lot_is_rounded_down_onto_the_step(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.0257,
            sl=info.ask - 500.0,
            tp=info.ask + 1500.0,
            info=info,
        )
        assert entry.volume == pytest.approx(0.025)

    def test_a_sub_minimum_lot_is_refused_with_retcode_10014(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        with pytest.raises(OrderRejected) as excinfo:
            simulator.simulate_entry(
                symbol="Volatility 75 Index",
                side=Side.BUY,
                volume=0.004,
                sl=info.ask - 500.0,
                tp=info.ask + 1500.0,
                info=info,
            )
        assert excinfo.value.retcode == RETCODE_INVALID_VOLUME
        (rejection,) = simulator.rejections()
        assert rejection.reason == REASON_VOLUME_BELOW_MIN

    def test_volume_is_validated_before_stops_like_mt5_does(self) -> None:
        """An order failing both rules is attributed to the volume, so the
        rejection breakdown names the first rule that would actually have
        stopped it rather than double-counting."""
        simulator = make_simulator()
        info = vix75_info()
        with pytest.raises(OrderRejected):
            simulator.simulate_entry(
                symbol="Volatility 75 Index",
                side=Side.BUY,
                volume=0.004,
                sl=info.ask - 45.0,
                tp=info.ask + 45.0,
                info=info,
            )
        assert [r.reason for r in simulator.rejections()] == [REASON_VOLUME_BELOW_MIN]


class TestFillPrice:
    def test_slippage_moves_a_buy_fill_against_the_trader(self) -> None:
        simulator = make_simulator(mean=0.5)
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 500.0,
            tp=info.ask + 1500.0,
            info=info,
        )
        assert entry.fill_price == pytest.approx(info.ask + 0.5)
        assert entry.slippage == pytest.approx(0.5)

    def test_slippage_moves_a_sell_fill_against_the_trader_too(self) -> None:
        simulator = make_simulator(mean=0.5)
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.SELL,
            volume=0.05,
            sl=info.bid + 500.0,
            tp=info.bid - 1500.0,
            info=info,
        )
        assert entry.fill_price == pytest.approx(info.bid - 0.5)

    def test_spread_widening_costs_the_trader_half_the_extra_spread(self) -> None:
        # 40 recorded points * 1.5 = 60 points; the extra 20 points on a 0.01
        # point is 0.20 price units, of which an entry crosses half.
        simulator = make_simulator(spread_widening_factor=1.5)
        info = vix75_info(spread_points=40)
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 500.0,
            tp=info.ask + 1500.0,
            info=info,
        )
        assert entry.slippage == pytest.approx(0.10)
        assert entry.fill_price == pytest.approx(info.ask + 0.10)

    def test_no_widening_and_no_slippage_reproduces_the_old_frictionless_fill(self) -> None:
        simulator = make_simulator()
        info = vix75_info()
        entry = simulator.simulate_entry(
            symbol="Volatility 75 Index",
            side=Side.BUY,
            volume=0.05,
            sl=info.ask - 500.0,
            tp=info.ask + 1500.0,
            info=info,
        )
        assert entry.fill_price == pytest.approx(info.ask)
        assert entry.slippage == pytest.approx(0.0)


def test_rejection_breakdown_is_ordered_deterministically() -> None:
    simulator = make_simulator()
    info = vix75_info()
    for _ in range(3):
        with pytest.raises(OrderRejected):
            simulator.simulate_entry(
                symbol="Volatility 75 Index",
                side=Side.BUY,
                volume=0.004,
                sl=info.ask - 500.0,
                tp=info.ask + 1500.0,
                info=info,
            )
    for _ in range(5):
        with pytest.raises(OrderRejected):
            simulator.simulate_entry(
                symbol="Volatility 75 Index",
                side=Side.BUY,
                volume=0.05,
                sl=info.ask - 45.0,
                tp=info.ask + 1500.0,
                info=info,
            )
    assert [(r.reason, r.count) for r in simulator.rejections()] == [
        (REASON_STOPS_LEVEL, 5),
        (REASON_VOLUME_BELOW_MIN, 3),
    ]
