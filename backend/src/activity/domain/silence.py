"""Dead-bot detection (OBSERVABILITY_PLAN.md Phase 5): a bot that has quietly
stopped firing altogether — a broken skill assignment, an exception
swallowed upstream, a strategy file bug — looks identical to "the market's
just quiet right now" unless something compares the *gap* since its last
signal against that bot's own normal cadence.

Pure domain code — takes already-loaded signal timestamps and decides
whether the current gap is anomalous relative to that bot's own history, so
a scalp bot's normal quiet spell isn't compared against a swing bot's (or
vice versa). No I/O, no framework, trivially unit-testable — the periodic
poll that loads timestamps and publishes an alert lives in
`activity/application/silence_monitor.py`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

DEFAULT_SILENCE_MULTIPLIER = 5.0
"""How many multiples of a bot's own median inter-signal interval count as
"gone silent" — high enough that ordinary variance (a slow session, a
weekend, a quiet news week) doesn't false-positive, low enough to still
catch a bot that has actually stopped within a reasonable window."""

MIN_SIGNALS_FOR_BASELINE = 5
"""Below this many recorded signals there's no meaningful median to compare
against — a brand-new bot isn't "silent", it just hasn't traded yet."""


@dataclass(frozen=True, kw_only=True)
class SilenceStatus:
    silent: bool
    """Whether the elapsed time since the last signal exceeds
    `multiplier * median_interval_s`. Always `False` when there's no
    baseline yet (fewer than `min_signals` recorded signals) or no signals
    at all."""
    median_interval_s: float | None
    """This bot's median gap between consecutive signals in the window
    handed in, or `None` with too few signals to compute one."""
    elapsed_s: float
    """Time since the most recent signal. `0.0` when there are no signals at
    all — there is nothing to be silent *since*."""
    threshold_s: float | None
    """`multiplier * median_interval_s`, or `None` alongside `median_interval_s`."""
    last_signal_at: datetime | None


def detect_silence(
    signal_times: list[datetime],
    *,
    now: datetime,
    multiplier: float = DEFAULT_SILENCE_MULTIPLIER,
    min_signals: int = MIN_SIGNALS_FOR_BASELINE,
) -> SilenceStatus:
    """`signal_times` need not be sorted or deduplicated — every timestamp
    this bot fired a signal at, in whatever lookback window the caller
    already loaded (`SilenceMonitor` uses `SignalDecisionRepository.
    list_between`)."""
    if not signal_times:
        return SilenceStatus(
            silent=False,
            median_interval_s=None,
            elapsed_s=0.0,
            threshold_s=None,
            last_signal_at=None,
        )
    ordered = sorted(signal_times)
    last_signal_at = ordered[-1]
    elapsed_s = (now - last_signal_at).total_seconds()
    if len(ordered) < min_signals:
        return SilenceStatus(
            silent=False,
            median_interval_s=None,
            elapsed_s=elapsed_s,
            threshold_s=None,
            last_signal_at=last_signal_at,
        )
    # Deliberately `strict=False`: `ordered[1:]` is one element shorter than
    # `ordered` by construction — this is the standard consecutive-pairs
    # idiom, not a length mismatch bug.
    intervals = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)]
    median_interval_s = statistics.median(intervals)
    # A zero (or negative-clock) median would make any positive elapsed time
    # look infinitely overdue — treat it as "no usable baseline" rather than
    # flagging silence off a degenerate threshold.
    if median_interval_s <= 0:
        return SilenceStatus(
            silent=False,
            median_interval_s=median_interval_s,
            elapsed_s=elapsed_s,
            threshold_s=None,
            last_signal_at=last_signal_at,
        )
    threshold_s = multiplier * median_interval_s
    return SilenceStatus(
        silent=elapsed_s > threshold_s,
        median_interval_s=median_interval_s,
        elapsed_s=elapsed_s,
        threshold_s=threshold_s,
        last_signal_at=last_signal_at,
    )
