"""Broker-constraint simulation for backtests (OBSERVABILITY_PLAN.md Phase 4).

Implements `ExecutionSimulatorPort` on top of the pure rules in
`broker/domain/broker_constraints.py` and the calibrated model in
`broker/domain/slippage.py`, and — crucially — **counts every rejection by
reason**. A strategy that a live broker would refuse 100% of the time must
show as 100% rejected in its report, not as a tidy equity curve.

Stateful (counters, RNG cursor) and therefore an adapter, not domain. One
instance per backtest run; it is the run's own object, so its counts are the
run's counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.broker.domain.broker_constraints import (
    REASON_STOPS_LEVEL,
    RETCODE_INVALID_STOPS,
    RETCODE_INVALID_VOLUME,
    SimulatedEntry,
    check_stops_level,
    clamp_stops,
    round_volume,
    widened_spread_points,
)
from src.broker.domain.slippage import SlippageSampler, apply_slippage
from src.broker.domain.trading import OrderRejected, Side
from src.market_data.domain.models import SymbolInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class RejectionCount:
    """How many entries one broker rule refused, and an example of why."""

    reason: str
    count: int
    retcode: int
    example: str
    """The first refusal's own message — the concrete numbers ("sl 45.00 <
    required 107.70") that make the count actionable."""


class BrokerConstraintSimulator:
    """Applies, in the order a real server does:

    1. **lot grid** — round down to `volume_step`, refuse below `volume_min`
       or above `volume_max` (retcode 10014);
    2. **`stops_level`** — refuse an SL or TP closer to price than the
       symbol's minimum distance (retcode 10016) unless `clamp_stops` is on,
       in which case the offending leg is pushed out to the minimum instead
       and the entry proceeds;
    3. **spread widening** — pay a spread wider than the bar's recorded
       closing spread, since real entries do not happen at the close;
    4. **slippage** — move the fill by a draw from the symbol's calibrated
       distribution.

    Ordering matters and mirrors MT5: volume is validated before stops, so a
    strategy that fails both is attributed to the first rule that would
    actually have stopped it."""

    def __init__(
        self,
        *,
        slippage: SlippageSampler,
        spread_widening_factor: float = 1.0,
        clamp_stops: bool = False,
        enforce_stops_level: bool = True,
        enforce_volume: bool = True,
    ) -> None:
        self._slippage = slippage
        self._spread_widening_factor = spread_widening_factor
        self._clamp_stops = clamp_stops
        self._enforce_stops_level = enforce_stops_level
        self._enforce_volume = enforce_volume
        self._counts: dict[str, int] = {}
        self._examples: dict[str, str] = {}
        self._retcodes: dict[str, int] = {}
        self._accepted = 0
        self._clamped = 0

    # ── reporting ────────────────────────────────────────────────────────────

    @property
    def accepted_count(self) -> int:
        """Entries the simulated broker filled."""
        return self._accepted

    @property
    def clamped_count(self) -> int:
        """Entries whose SL/TP was pushed out to `stops_level` instead of being
        rejected. Always 0 unless `clamp_stops` is on."""
        return self._clamped

    @property
    def rejected_count(self) -> int:
        return sum(self._counts.values())

    def rejections(self) -> tuple[RejectionCount, ...]:
        """Per-reason counts, most frequent first, ties broken by reason name
        so the report is deterministic."""
        return tuple(
            RejectionCount(
                reason=reason,
                count=count,
                retcode=self._retcodes[reason],
                example=self._examples[reason],
            )
            for reason, count in sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )

    def _reject(self, reason: str, retcode: int, message: str) -> OrderRejected:
        self._counts[reason] = self._counts.get(reason, 0) + 1
        self._retcodes.setdefault(reason, retcode)
        self._examples.setdefault(reason, message)
        return OrderRejected(message, retcode)

    # ── ExecutionSimulatorPort ───────────────────────────────────────────────

    def simulate_entry(
        self,
        *,
        symbol: str,
        side: Side,
        volume: float,
        sl: float | None,
        tp: float | None,
        info: SymbolInfo,
    ) -> SimulatedEntry:
        filled_volume = volume
        if self._enforce_volume:
            filled_volume, violation = round_volume(
                volume,
                volume_min=info.volume_min,
                volume_max=info.volume_max,
                volume_step=info.volume_step,
            )
            if violation is not None:
                raise self._reject(
                    violation.reason,
                    RETCODE_INVALID_VOLUME,
                    f"invalid volume: {symbol} requested {violation.requested:.4f} lots, "
                    f"rounds to {violation.rounded:.4f} on a {info.volume_step} step "
                    f"(min {info.volume_min}, max {info.volume_max})",
                )

        reference_price = info.ask if side is Side.BUY else info.bid
        filled_sl, filled_tp = sl, tp
        if self._enforce_stops_level:
            violation = check_stops_level(
                side=side,
                price=reference_price,
                sl=sl,
                tp=tp,
                stops_level=info.stops_level,
                point=info.point,
            )
            if violation is not None:
                message = (
                    f"invalid stops: {symbol} {side.value} {violation.leg} is "
                    f"{violation.distance:.5f} from price {reference_price:.5f}, "
                    f"broker requires at least {violation.required:.5f} "
                    f"(stops_level={info.stops_level} points)"
                )
                if not self._clamp_stops:
                    raise self._reject(REASON_STOPS_LEVEL, RETCODE_INVALID_STOPS, message)
                filled_sl, filled_tp = clamp_stops(
                    side=side,
                    price=reference_price,
                    sl=sl,
                    tp=tp,
                    stops_level=info.stops_level,
                    point=info.point,
                )
                self._clamped += 1
                logger.info("STOPS CLAMPED: %s", message)

        widened = widened_spread_points(info.spread_points, self._spread_widening_factor)
        # The extra spread is charged as an adverse price move: the trader
        # crosses a wider book than the bar's closing quote suggested. Half the
        # extra, because bid/ask are derived symmetrically around the close
        # (see market_data/adapters/replay.py) and an entry only crosses one side.
        extra_spread = (widened - info.spread_points) * info.point / 2.0
        drawn = self._slippage.sample()
        total = extra_spread + drawn
        fill_price = apply_slippage(side, reference_price, total)
        self._accepted += 1
        return SimulatedEntry(
            volume=filled_volume,
            fill_price=fill_price,
            slippage=total,
            sl=filled_sl,
            tp=filled_tp,
        )
