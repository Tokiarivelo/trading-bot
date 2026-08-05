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


def test_signal_regex_matches_the_current_multi_target_format() -> None:
    # Regression guard: bdab6e1 added "@ <price>" and "(N target position(s))"
    # to the engine's SIGNAL line, which the previous \S+-based regex could not
    # match — every backtest report's `signals` list came back empty.
    signals = extract_signals(
        [
            _entry(
                0,
                "SIGNAL: XAUUSD sell @ 4020.03000 (2 target position(s)) via "
                "strategy=pob_snd_zones_xauusd skill=backtest — DBD-retest(30m)",
            ),
            _entry(0, "ENTRY OPENED: ticket=1 sell XAUUSD 0.01 lots @ 4020.00"),
        ]
    )
    assert len(signals) == 1
    assert signals[0].direction == "sell"
    assert signals[0].outcome == "opened"
    assert signals[0].reason == "DBD-retest(30m)"


def test_symbol_with_spaces_parses() -> None:
    signals = extract_signals(
        [
            _entry(
                0,
                "SIGNAL: Volatility 75 Index buy @ 48923.94500 (1 target position(s)) via "
                "strategy=rbr_dbd_zones_scalp_vix75 skill=backtest — RBR-retest",
            ),
        ]
    )
    assert [(s.direction, s.outcome) for s in signals] == [("buy", "skipped")]


def test_newly_covered_guard_lines_map_to_known_outcomes() -> None:
    signals = extract_signals(
        [
            _entry(0, SIGNAL_BUY),
            _entry(
                0,
                "ENTRY BLOCKED (max open positions cap reached): XAUUSD buy [backtest] — "
                "TP2 of 2 skipped, 3 open position(s) at cap 3",
            ),
            _entry(10, SIGNAL_BUY),
            _entry(10, "ENTRY BLOCKED (risk gate): XAUUSD [backtest] — daily loss limit hit"),
            _entry(20, SIGNAL_BUY),
            _entry(
                20,
                "ENTRY SKIPPED (no account connected): XAUUSD buy [backtest] — no account "
                "balance available, cannot size the entry",
            ),
        ]
    )
    assert [s.outcome for s in signals] == ["risk_rejected", "risk_rejected", "skipped"]


def test_risk_sizing_line_with_tp_index_in_the_body_matches() -> None:
    signals = extract_signals(
        [
            _entry(0, SIGNAL_BUY),
            _entry(
                0,
                "ENTRY REJECTED (risk sizing): XAUUSD buy [backtest] — TP1: computed "
                "volume 0.0000 (balance=1000.00, sl_distance=0.00100, risk_multiplier=0.50)",
            ),
        ]
    )
    assert [s.outcome for s in signals] == ["risk_rejected"]
    assert "TP1: computed volume 0.0000" in signals[0].reason


def test_outcome_explanation_is_appended_to_the_reason() -> None:
    signals = extract_signals(
        [
            _entry(0, SIGNAL_BUY),
            _entry(0, "ENTRY BLOCKED (HTF veto): XAUUSD buy — H1 trend (down) opposes buy"),
        ]
    )
    assert signals[0].reason == "RBR-retest(30m) — H1 trend (down) opposes buy"


def test_outcome_vocabulary_stays_closed() -> None:
    from src.backtest.application.signals import _OUTCOME_PREFIXES

    known = {"opened", "htf_veto", "risk_rejected", "spread_veto", "broker_rejected", "skipped"}
    assert {outcome for _prefix, outcome in _OUTCOME_PREFIXES} <= known


def test_unrelated_lines_are_ignored() -> None:
    signals = extract_signals(
        [
            _entry(0, "risk manager: new trading day, daily counters reset"),
            _entry(1, "ENTRY OPENED: ticket=9 buy XAUUSD 0.01 lots @ 4000.00"),  # manual/no signal
            _entry(2, "breakeven: ticket=9 XAUUSD sl moved to entry 4000.00"),
        ]
    )
    assert signals == ()
