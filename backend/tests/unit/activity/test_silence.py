"""Dead-bot silence detection (OBSERVABILITY_PLAN.md Phase 5) — pure
domain logic, see `activity/domain/silence.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.activity.domain.silence import detect_silence

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _times_at(*minutes_ago: float) -> list[datetime]:
    return [NOW - timedelta(minutes=m) for m in minutes_ago]


def test_no_signals_is_never_silent():
    status = detect_silence([], now=NOW)
    assert status.silent is False
    assert status.median_interval_s is None
    assert status.last_signal_at is None
    assert status.elapsed_s == 0.0


def test_fewer_than_min_signals_has_no_baseline_and_is_never_silent():
    # Fires every 10 min, but only 3 recorded — below the default
    # min_signals=5 floor, so there's no median to judge against yet.
    times = _times_at(30, 20, 10)
    status = detect_silence(times, now=NOW, min_signals=5)
    assert status.silent is False
    assert status.median_interval_s is None
    assert status.last_signal_at == NOW - timedelta(minutes=10)


def test_regular_cadence_with_recent_signal_is_not_silent():
    # Median gap 10 min, last signal 8 min ago — well under the 5x threshold.
    times = _times_at(50, 40, 30, 20, 10, 8)
    status = detect_silence(times, now=NOW, multiplier=5.0, min_signals=5)
    assert status.silent is False
    assert status.median_interval_s == 600.0  # 10 min in seconds
    assert status.threshold_s == 3000.0  # 5x


def test_gap_beyond_multiplier_times_median_is_silent():
    # Median gap 10 min historically, but nothing for the last 60 min —
    # 6x the median, past the default 5x threshold.
    times = _times_at(120, 110, 100, 90, 80, 60)
    status = detect_silence(times, now=NOW, multiplier=5.0, min_signals=5)
    assert status.silent is True
    assert status.median_interval_s == 600.0
    assert status.elapsed_s == 3600.0
    assert status.threshold_s == 3000.0


def test_gap_exactly_at_threshold_is_not_yet_silent():
    times = _times_at(50, 40, 30, 20, 10, 0)
    # Median interval 10 min; push "now" to exactly 5x that past the last
    # signal (the last signal itself is "0 min ago" in the fixture, so
    # advance the clock instead of editing the fixture).
    later = NOW + timedelta(minutes=50)
    status = detect_silence(times, now=later, multiplier=5.0, min_signals=5)
    assert status.threshold_s == 3000.0
    assert status.elapsed_s == 3000.0
    assert status.silent is False  # strictly greater than, not >=


def test_a_bot_that_only_ever_fired_once_at_the_same_instant_never_flags():
    # Degenerate case: every recorded signal shares the same timestamp, so
    # the median interval is 0 — treated as "no usable baseline" rather than
    # flagging silence off a zero threshold.
    times = [NOW - timedelta(minutes=1)] * 6
    status = detect_silence(times, now=NOW, min_signals=5)
    assert status.median_interval_s == 0.0
    assert status.threshold_s is None
    assert status.silent is False


def test_unsorted_input_is_handled_the_same_as_sorted():
    times = _times_at(10, 60, 30, 90, 80, 120)
    sorted_status = detect_silence(sorted(times, reverse=True), now=NOW)
    unsorted_status = detect_silence(times, now=NOW)
    assert sorted_status == unsorted_status
