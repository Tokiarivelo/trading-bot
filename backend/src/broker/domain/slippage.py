"""Slippage model for simulated fills, calibrated from real live fills
(OBSERVABILITY_PLAN.md Phase 4).

Phase 3 started recording `TradeRecord.slippage` — the signed, per-fill
difference between the price an order asked for and the price the broker gave
it, oriented so **positive always means the fill cost the trader** (see
`broker.domain.trading.execution_slippage`). That is the empirical
distribution this module turns into a backtest input, so a backtest stops
assuming the perfect fill that no live order has ever received.

Pure: no I/O, no framework. The caller supplies the observed samples; where
they come from (the journal, a fixture, nothing at all) is not this module's
business.

Sampling is done through an explicitly seeded `random.Random`, never the
global RNG, so a backtest with identical inputs still produces byte-identical
trades — the determinism property that was previously verified via trade
fingerprints and must not regress.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from src.broker.domain.trading import Side

# Below this many measured live fills a symbol's own distribution is noise —
# one bad fill during a news spike would otherwise define the whole model.
MIN_CALIBRATION_SAMPLES = 20

# Documented fallback, used when a symbol has fewer than
# `MIN_CALIBRATION_SAMPLES` measured fills (the normal state for a symbol the
# bot has not traded live yet, and for every symbol on day one of Phase 3).
#
# Chosen to be pessimistic rather than neutral: assuming zero slippage is the
# assumption that made backtests optimistic in the first place, so the default
# is "the trader pays a bit", expressed in points so it scales to any symbol.
# These are deliberately modest — the point of the fallback is to stop
# reporting a free fill, not to guess a number precisely. Replace them with
# real data by trading live: any symbol crossing MIN_CALIBRATION_SAMPLES
# switches to its own measured mean/stddev automatically.
FALLBACK_MEAN_POINTS = 2.0
FALLBACK_STDDEV_POINTS = 2.0

# Slippage beyond this many standard deviations is clipped when sampled.
# Without it a normal draw can occasionally return an absurd fill price that
# dominates a whole backtest's P&L through one trade.
_SAMPLE_CLIP_SIGMA = 3.0


@dataclass(frozen=True, kw_only=True)
class SlippageProfile:
    """The per-symbol slippage distribution a backtest fills against.

    `mean`/`stddev` are in **price units** (not points), positive mean = the
    average fill costs the trader that much. `source` records whether this
    came from real fills or the documented fallback, so a report can say which
    — a backtest calibrated on the fallback is a guess and should be labelled
    as one."""

    symbol: str
    mean: float
    stddev: float
    sample_count: int
    source: str  # "live" | "fallback"

    @property
    def calibrated(self) -> bool:
        return self.source == "live"


def calibrate_slippage(
    symbol: str,
    observed: Sequence[float],
    *,
    point: float,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
) -> SlippageProfile:
    """Build a `SlippageProfile` from measured live slippage values.

    `observed` are `TradeRecord.slippage` values for this symbol, already in
    price units and already sign-oriented by `execution_slippage`. `None`
    slippages (trades journalled before Phase 3) must be filtered out by the
    caller — they are missing measurements, not zero-slippage fills, and
    treating them as zeros would drag the mean toward the very optimism this
    model exists to remove.

    Falls back to `FALLBACK_MEAN_POINTS`/`FALLBACK_STDDEV_POINTS` scaled by
    `point` when there are fewer than `min_samples` observations."""
    samples = list(observed)
    if len(samples) < min_samples:
        return SlippageProfile(
            symbol=symbol,
            mean=FALLBACK_MEAN_POINTS * point,
            stddev=FALLBACK_STDDEV_POINTS * point,
            sample_count=len(samples),
            source="fallback",
        )
    return SlippageProfile(
        symbol=symbol,
        mean=statistics.fmean(samples),
        stddev=statistics.stdev(samples),
        sample_count=len(samples),
        source="live",
    )


class SlippageSampler:
    """Draws slippage values from a `SlippageProfile`, deterministically.

    Seeded per instance; a run that creates the sampler with the same seed and
    calls it in the same order gets the same sequence, which is what keeps
    backtests reproducible. The default seed is fixed rather than random for
    exactly that reason."""

    DEFAULT_SEED = 20260805

    def __init__(self, profile: SlippageProfile, *, seed: int = DEFAULT_SEED) -> None:
        self._profile = profile
        self._rng = random.Random(seed)

    @property
    def profile(self) -> SlippageProfile:
        return self._profile

    def sample(self) -> float:
        """One slippage draw, in price units, positive = costs the trader.

        A zero-stddev profile (every observed fill identical, or a fallback
        configured with no spread) returns its mean without touching the RNG,
        so such runs stay trivially reproducible."""
        if self._profile.stddev <= 0.0:
            return self._profile.mean
        raw = self._rng.gauss(self._profile.mean, self._profile.stddev)
        limit = _SAMPLE_CLIP_SIGMA * self._profile.stddev
        low = self._profile.mean - limit
        high = self._profile.mean + limit
        return min(high, max(low, raw))


def apply_slippage(side: Side, price: float, slippage: float) -> float:
    """Move a would-be fill price by `slippage` in the direction that costs the
    trader — the exact inverse of `execution_slippage`, so
    `execution_slippage(side, price, apply_slippage(side, price, s)) == s`.

    A buy pays more, a sell receives less. A negative `slippage` (price
    improvement, which does happen) therefore improves the fill."""
    direction = 1.0 if side is Side.BUY else -1.0
    return price + slippage * direction
