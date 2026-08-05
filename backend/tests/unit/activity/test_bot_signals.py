"""Unit tests for `activity/application/bot_signals.py` — turning one live
bot's own decision-trail log lines back into structured `BotSignal`s, scoped
correctly even when other bots' lines interleave in the same stream."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.activity.application.bot_signals import extract_bot_signals
from src.activity.domain.models import LogEntry

T0 = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
SKILL_A = "normal/xauusd/breakout_v1"
SKILL_B = "normal/xauusd/mean_reversion"


def _entry(
    seconds: int, message: str, logger: str = "src.engine.application.trade_loop"
) -> LogEntry:
    return LogEntry(
        id=None,
        created_at=T0 + timedelta(seconds=seconds),
        level="INFO",
        logger=logger,
        message=message,
    )


def signal_line(skill: str, direction: str = "buy", reason: str = "RBR-retest(30m)") -> str:
    return f"SIGNAL: XAUUSD {direction} via strategy=breakout_v1 skill={skill} — {reason}"


def test_extracts_opened_signal_for_the_target_skill() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, signal_line(SKILL_A)),
            _entry(
                0, "SIZING OK: XAUUSD buy 0.02 lots [normal/xauusd/breakout_v1] (balance=1000.00)"
            ),
            _entry(
                0,
                "ENTRY OPENED: ticket=1 buy XAUUSD 0.02 lots @ 4000.00 sl=3990.0 tp=4020.0 "
                "spread=15pts strategy=breakout_v1:v1 skill=normal/xauusd/breakout_v1 magic=123 "
                "reason=RBR-retest(30m)",
                logger="src.broker.application.order_service",
            ),
        ],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].direction == "buy"
    assert signals[0].outcome == "opened"
    assert signals[0].reason == "RBR-retest(30m)"


def test_ignores_other_bots_interleaved_lines() -> None:
    # Bot B's signal+veto land between bot A's signal and its own outcome —
    # without skill-scoped filtering this would misattribute bot B's veto
    # to bot A's signal.
    signals = extract_bot_signals(
        [
            _entry(0, signal_line(SKILL_A, reason="A-signal")),
            _entry(1, signal_line(SKILL_B, direction="sell", reason="B-signal")),
            _entry(
                1,
                "ENTRY BLOCKED (HTF veto): XAUUSD sell [normal/xauusd/mean_reversion] — "
                "H1 trend (up) opposes sell",
            ),
            _entry(
                2,
                "ENTRY REJECTED (risk sizing): XAUUSD buy [normal/xauusd/breakout_v1] — "
                "computed volume 0.0000 (balance=1000.00, sl_distance=0.001, risk_mult=1.00)",
            ),
        ],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].reason.startswith("A-signal — computed volume 0.0000")
    assert signals[0].outcome == "risk_rejected"

    signals_b = extract_bot_signals(
        [
            _entry(0, signal_line(SKILL_A, reason="A-signal")),
            _entry(1, signal_line(SKILL_B, direction="sell", reason="B-signal")),
            _entry(
                1,
                "ENTRY BLOCKED (HTF veto): XAUUSD sell [normal/xauusd/mean_reversion] — "
                "H1 trend (up) opposes sell",
            ),
            _entry(
                2,
                "ENTRY REJECTED (risk sizing): XAUUSD buy [normal/xauusd/breakout_v1] — "
                "computed volume 0.0000 (balance=1000.00, sl_distance=0.001, risk_mult=1.00)",
            ),
        ],
        skill=SKILL_B,
    )
    assert len(signals_b) == 1
    assert signals_b[0].reason == "B-signal — H1 trend (up) opposes sell"
    assert signals_b[0].outcome == "htf_veto"


def test_recognizes_all_outcome_prefixes() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, signal_line(SKILL_A, reason="s1")),
            _entry(
                0,
                "ENTRY BLOCKED (HTF veto): XAUUSD buy [normal/xauusd/breakout_v1] — H1 trend down",
            ),
            _entry(1, signal_line(SKILL_A, reason="s2")),
            _entry(
                1,
                "ENTRY REJECTED (risk sizing): XAUUSD buy [normal/xauusd/breakout_v1] — "
                "computed volume 0.0000",
            ),
            _entry(2, signal_line(SKILL_A, reason="s3")),
            _entry(
                2,
                "ENTRY REJECTED (spread/RR gate): buy XAUUSD spread=40pts sl=None tp=None "
                "strategy=breakout_v1:v1 skill=normal/xauusd/breakout_v1 — tp distance too tight",
                logger="src.broker.application.order_service",
            ),
            _entry(3, signal_line(SKILL_A, reason="s4")),
            _entry(
                3,
                "ENTRY REJECTED (broker): buy XAUUSD 0.02 lots sl=3990.0 tp=4020.0 "
                "strategy=breakout_v1:v1 skill=normal/xauusd/breakout_v1 — invalid stops",
                logger="src.broker.application.order_service",
            ),
            _entry(4, signal_line(SKILL_A, reason="s5")),
            _entry(
                4,
                "ENTRY OPENED: ticket=9 buy XAUUSD 0.02 lots @ 4000.00 sl=3990.0 tp=4020.0 "
                "spread=15pts strategy=breakout_v1:v1 skill=normal/xauusd/breakout_v1 magic=1 "
                "reason=s5",
                logger="src.broker.application.order_service",
            ),
        ],
        skill=SKILL_A,
    )
    assert [s.outcome for s in signals] == [
        "htf_veto",
        "risk_rejected",
        "spread_veto",
        "broker_rejected",
        "opened",
    ]


def test_signal_without_outcome_line_is_kept_as_skipped() -> None:
    signals = extract_bot_signals(
        [_entry(0, signal_line(SKILL_A, reason="lonely-signal"))],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].outcome == "skipped"


def test_skill_and_symbol_with_spaces_are_parsed() -> None:
    # Real VIX75 lines: both the symbol ("Volatility 75 Index") and the skill
    # ("normal/volatility 75 index/...") contain spaces — the old \S+ regexes
    # dropped every one of these, so the signal trail was empty for any bot on
    # a space-containing symbol.
    skill = "normal/volatility 75 index/rbr_dbd_zones_scalp_vix75"
    signals = extract_bot_signals(
        [
            _entry(
                0,
                "SIGNAL: Volatility 75 Index sell via strategy=rbr_dbd_zones_scalp_vix75 "
                f"skill={skill} — DBD-retest pattern=bearish_engulfing trend=down "
                "zone_rect=[52460.07,52551.08] retest_age=2 mtf_confirms=1",
            ),
            _entry(
                0,
                f"ENTRY BLOCKED (HTF veto): Volatility 75 Index sell [{skill}] — "
                "H4 trend (up) opposes sell signal",
            ),
            _entry(
                60,
                "SIGNAL: Volatility 75 Index buy via strategy=rbr_dbd_zones_scalp_vix75 "
                f"skill={skill} — RBR-retest pattern=bullish_engulfing trend=up",
            ),
            _entry(
                60,
                "ENTRY OPENED: ticket=7 buy Volatility 75 Index 0.86 lots @ 48923.94500 "
                "sl=48866.03 tp=49039.76 spread=1049pts "
                f"strategy=rbr_dbd_zones_scalp_vix75:v1 skill={skill} magic=42 "
                "reason=RBR-retest pattern=bullish_engulfing",
                logger="src.broker.application.order_service",
            ),
        ],
        skill=skill,
    )
    assert [s.outcome for s in signals] == ["htf_veto", "opened"]
    assert signals[0].direction == "sell"
    assert signals[0].reason.startswith("DBD-retest pattern=bearish_engulfing")
    assert signals[1].direction == "buy"


def test_lines_with_no_skill_token_are_ignored() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, "ENTRY BLOCKED (skill routing): XAUUSD — no active bots"),
            _entry(1, "ENTRY SKIPPED (no account connected): XAUUSD"),
        ],
        skill=SKILL_A,
    )
    assert signals == []


# --- current multi-target SIGNAL format (bdab6e1 onward) --------------------


def current_signal_line(
    skill: str,
    direction: str = "buy",
    price: str = "4001.25000",
    targets: int = 2,
    reason: str = "RBR-retest(30m)",
) -> str:
    return (
        f"SIGNAL: XAUUSD {direction} @ {price} ({targets} target position(s)) "
        f"via strategy=breakout_v1 skill={skill} — {reason}"
    )


def test_parses_current_signal_line_with_price_and_target_count() -> None:
    # Regression guard: the "(N target position(s))" segment added in bdab6e1
    # made the old regex match nothing at all, so the live signal trail was
    # empty for every bot.
    signals = extract_bot_signals(
        [_entry(0, current_signal_line(SKILL_A, reason="RBR-retest(30m)"))],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].direction == "buy"
    assert signals[0].price == 4001.25
    assert signals[0].reason == "RBR-retest(30m)"
    assert signals[0].outcome == "skipped"


def test_legacy_signal_line_without_price_still_parses_with_null_price() -> None:
    signals = extract_bot_signals([_entry(0, signal_line(SKILL_A))], skill=SKILL_A)
    assert len(signals) == 1
    assert signals[0].price is None


def test_signal_line_with_target_count_but_no_price_parses() -> None:
    message = (
        "SIGNAL: XAUUSD sell (3 target position(s)) via strategy=breakout_v1 "
        f"skill={SKILL_A} — DBD-retest"
    )
    signals = extract_bot_signals([_entry(0, message)], skill=SKILL_A)
    assert [(s.direction, s.price) for s in signals] == [("sell", None)]


def test_price_survives_onto_the_outcome_row() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, current_signal_line(SKILL_A, price="4001.25000")),
            _entry(
                0,
                "ENTRY OPENED: ticket=1 buy XAUUSD 0.02 lots @ 4001.30 sl=3990.0 tp=4020.0 "
                f"skill={SKILL_A} magic=1 reason=RBR-retest(30m)",
                logger="src.broker.application.order_service",
            ),
        ],
        skill=SKILL_A,
    )
    assert [(s.outcome, s.price) for s in signals] == [("opened", 4001.25)]


# --- guard lines that previously had no skill token / no outcome mapping ----


def test_no_account_connected_line_is_attributed_and_marked_skipped() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, current_signal_line(SKILL_A, reason="s1")),
            _entry(
                0,
                f"ENTRY SKIPPED (no account connected): XAUUSD buy [{SKILL_A}] — "
                "no account balance available, cannot size the entry",
            ),
        ],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].outcome == "skipped"
    assert signals[0].reason == "s1 — no account balance available, cannot size the entry"


def test_max_open_positions_line_is_attributed_and_marked_risk_rejected() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, current_signal_line(SKILL_A, reason="s1")),
            _entry(
                0,
                f"ENTRY BLOCKED (max open positions cap reached): XAUUSD buy [{SKILL_A}] — "
                "TP2 of 2 skipped, 3 open position(s) at cap 3",
            ),
        ],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].outcome == "risk_rejected"
    assert signals[0].reason.endswith("TP2 of 2 skipped, 3 open position(s) at cap 3")


def test_risk_sizing_line_with_tp_index_in_the_body_matches() -> None:
    # The TP index used to sit inside the prefix ("risk sizing for TP1"), which
    # matched neither parser's literal "ENTRY REJECTED (risk sizing):".
    signals = extract_bot_signals(
        [
            _entry(0, current_signal_line(SKILL_A, reason="s1")),
            _entry(
                0,
                f"ENTRY REJECTED (risk sizing): XAUUSD buy [{SKILL_A}] — TP1: computed "
                "volume 0.0000 (balance=1000.00, sl_distance=0.00100, risk_multiplier=0.50)",
            ),
        ],
        skill=SKILL_A,
    )
    assert len(signals) == 1
    assert signals[0].outcome == "risk_rejected"
    assert "TP1: computed volume 0.0000" in signals[0].reason


def test_risk_gate_and_volatility_guard_are_mapped_to_known_outcomes() -> None:
    signals = extract_bot_signals(
        [
            _entry(0, current_signal_line(SKILL_A, reason="s1")),
            _entry(0, f"ENTRY BLOCKED (risk gate): XAUUSD [{SKILL_A}] — daily loss limit hit"),
            _entry(1, current_signal_line(SKILL_A, reason="s2")),
            _entry(
                1,
                f"ENTRY BLOCKED (volatility guard): XAUUSD buy [{SKILL_A}] — "
                "regime=EXTREME percentile=99.2",
            ),
        ],
        skill=SKILL_A,
    )
    assert [s.outcome for s in signals] == ["risk_rejected", "risk_rejected"]


def test_every_outcome_value_stays_within_the_frontend_vocabulary() -> None:
    # The chart indexes SIGNAL_OUTCOME_META[outcome] unguarded — a new value
    # would crash it, so the parser's vocabulary is closed by contract.
    from src.activity.application.bot_signals import _OUTCOME_PREFIXES

    known = {"opened", "htf_veto", "risk_rejected", "spread_veto", "broker_rejected", "skipped"}
    assert {outcome for _prefix, outcome in _OUTCOME_PREFIXES} <= known
