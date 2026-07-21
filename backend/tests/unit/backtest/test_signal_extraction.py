"""Unit tests for `backtest/application/signals.py` — turning the replay's
decision-trail log lines back into structured `BacktestSignal`s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.backtest.application.signals import extract_signals
from src.backtest.domain.models import ActivityLogEntry

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _entry(minutes: int, message: str) -> ActivityLogEntry:
    return ActivityLogEntry(
        time=T0 + timedelta(minutes=minutes),
        level="INFO",
        logger="src.engine.application.trade_loop",
        message=message,
    )


SIGNAL_SELL = (
    "SIGNAL: XAUUSD sell via strategy=pob_snd_zones_xauusd skill=backtest — DBD-retest(30m) "
    "pattern=bearish_engulfing lines: entry=4020.03 sl=4061.43 tp=3949.40"
)
SIGNAL_BUY = "SIGNAL: XAUUSD buy via strategy=pob_snd_zones_xauusd skill=backtest — RBR-retest(30m)"


def test_extracts_signal_with_opened_outcome() -> None:
    signals = extract_signals(
        [
            _entry(0, "backtest starting: strategy=x symbol=XAUUSD"),
            _entry(5, SIGNAL_BUY),
            _entry(5, "SIZING OK: XAUUSD buy 0.01 lots (balance=1000.00, risk_multiplier=1.00)"),
            _entry(5, "ENTRY OPENED: ticket=1 buy XAUUSD 0.01 lots @ 4000.00"),
        ]
    )
    assert len(signals) == 1
    assert signals[0].direction == "buy"
    assert signals[0].outcome == "opened"
    assert signals[0].reason == "RBR-retest(30m)"
    assert signals[0].time == T0 + timedelta(minutes=5)


def test_extracts_veto_and_rejection_outcomes() -> None:
    signals = extract_signals(
        [
            _entry(0, SIGNAL_SELL),
            _entry(0, "ENTRY BLOCKED (HTF veto): XAUUSD sell — H1 trend (up) opposes sell"),
            _entry(10, SIGNAL_SELL),
            _entry(10, "ENTRY REJECTED (risk sizing): XAUUSD sell — computed volume 0.0000"),
            _entry(20, SIGNAL_BUY),
            _entry(20, "ENTRY REJECTED (spread/RR gate): buy XAUUSD spread=40pts — tp distance"),
        ]
    )
    assert [s.outcome for s in signals] == ["htf_veto", "risk_rejected", "spread_veto"]
    assert [s.direction for s in signals] == ["sell", "sell", "buy"]
    assert signals[0].reason.startswith("DBD-retest(30m)")


def test_signal_without_outcome_line_is_kept_as_skipped() -> None:
    # Two back-to-back signals where the first never got an outcome line,
    # and a trailing signal at the very end of the run.
    signals = extract_signals(
        [
            _entry(0, SIGNAL_BUY),
            _entry(5, SIGNAL_SELL),
            _entry(5, "ENTRY OPENED: ticket=2 sell XAUUSD 0.01 lots @ 4000.00"),
            _entry(10, SIGNAL_BUY),
        ]
    )
    assert [s.outcome for s in signals] == ["skipped", "opened", "skipped"]


def test_signal_regex_matches_the_skill_tagged_format() -> None:
    # Regression guard: TradeEngine now logs "... strategy=<name> skill=<skill>
    # — <reason>" (multi-bot attribution, §6.6) instead of "... strategy=<name>
    # — <reason>" — the regex must match the format the engine actually emits,
    # not just the pre-multi-bot format the other fixtures happened to use
    # before this test existed.
    signals = extract_signals(
        [
            _entry(
                0,
                "SIGNAL: XAUUSD buy via strategy=pob_snd_zones_xauusd skill=backtest — "
                "RBR-retest(30m)",
            ),
            _entry(0, "ENTRY OPENED: ticket=1 buy XAUUSD 0.01 lots @ 4000.00"),
        ]
    )
    assert len(signals) == 1
    assert signals[0].outcome == "opened"


def test_unrelated_lines_are_ignored() -> None:
    signals = extract_signals(
        [
            _entry(0, "risk manager: new trading day, daily counters reset"),
            _entry(1, "ENTRY OPENED: ticket=9 buy XAUUSD 0.01 lots @ 4000.00"),  # manual/no signal
            _entry(2, "breakeven: ticket=9 XAUUSD sl moved to entry 4000.00"),
        ]
    )
    assert signals == ()
