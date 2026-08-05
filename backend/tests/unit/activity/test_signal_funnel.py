"""Veto funnel aggregation (OBSERVABILITY_PLAN.md Phase 2) — "of N signals,
why did only M trade?", folded from the typed decision trail."""

from datetime import UTC, datetime

from src.activity.domain.funnel import FUNNEL_STAGES, build_funnels, stage_reached
from src.activity.domain.models import SIGNAL_OUTCOMES, SignalDecision


def _decision(
    signal_id: str,
    outcome: str,
    *,
    bot: str = "normal/xauusd/breakout_v1",
    symbol: str = "XAUUSD",
    reason: str = "retest of demand",
) -> SignalDecision:
    return SignalDecision(
        signal_id=signal_id,
        account_id="default",
        bot=bot,
        strategy="breakout_v1",
        symbol=symbol,
        timeframe="M5",
        direction="buy",
        price=2412.35,
        created_at=datetime.fromtimestamp(1000, tz=UTC),
        outcome=outcome,
        reason=reason,
    )


def test_every_outcome_in_the_vocabulary_has_a_stage():
    """A new outcome that nobody mapped would silently distort every count."""
    assert all(0 <= stage_reached(o) < len(FUNNEL_STAGES) for o in SIGNAL_OUTCOMES)


def test_an_unknown_outcome_still_counts_as_fired():
    (funnel,) = build_funnels([_decision("a", "something_new")])

    assert (funnel.fired, funnel.passed_htf, funnel.filled) == (1, 0, 0)
    assert funnel.drops[0].outcome == "something_new"


def test_the_funnel_narrows_one_stage_at_a_time():
    decisions = [
        _decision("a", "htf_veto"),
        _decision("b", "volatility_guard"),
        _decision("c", "risk_sizing"),
        _decision("d", "spread_veto"),
        _decision("e", "broker_rejected"),
        _decision("f", "opened"),
        _decision("g", "opened"),
    ]

    (funnel,) = build_funnels(decisions)

    assert funnel.fired == 7
    assert funnel.passed_htf == 6  # htf_veto dropped
    assert funnel.sized_ok == 4  # volatility_guard + risk_sizing dropped
    assert funnel.passed_spread == 3  # spread_veto dropped
    assert funnel.filled == 2  # broker_rejected dropped


def test_counts_are_monotonically_non_increasing():
    decisions = [_decision(str(i), o) for i, o in enumerate(SIGNAL_OUTCOMES)]

    (funnel,) = build_funnels(decisions)

    counts = [
        funnel.fired,
        funnel.passed_htf,
        funnel.sized_ok,
        funnel.passed_spread,
        funnel.filled,
    ]
    assert counts == sorted(counts, reverse=True)


def test_drops_are_grouped_by_stage_and_outcome_with_an_example_reason():
    decisions = [
        _decision("a", "htf_veto", reason="M15 trend down"),
        _decision("b", "htf_veto", reason="M15 trend down (second)"),
        _decision("c", "spread_veto", reason="spread 120pts > max 35pts"),
        _decision("d", "opened"),
    ]

    (funnel,) = build_funnels(decisions)

    htf, spread = funnel.drops
    assert (htf.stage, htf.outcome, htf.count) == ("passed_htf", "htf_veto", 2)
    assert htf.example_reason == "M15 trend down"
    assert (spread.stage, spread.outcome, spread.count) == (
        "passed_spread",
        "spread_veto",
        1,
    )
    # Filled signals are not drops.
    assert sum(d.count for d in funnel.drops) == 3


def test_a_pending_signal_counts_as_fired_and_drops_at_the_first_stage():
    (funnel,) = build_funnels([_decision("a", "skipped")])

    assert (funnel.fired, funnel.passed_htf) == (1, 0)
    assert funnel.drops[0].outcome == "skipped"


def test_bots_are_separated_and_ordered_busiest_first():
    decisions = [
        _decision("a", "opened", bot="quiet"),
        *[_decision(f"b{i}", "htf_veto", bot="busy") for i in range(3)],
    ]

    busy, quiet = build_funnels(decisions)

    assert (busy.bot, busy.fired) == ("busy", 3)
    assert (quiet.bot, quiet.fired, quiet.filled) == ("quiet", 1, 1)


def test_a_bots_symbols_are_collected_and_sorted():
    decisions = [
        _decision("a", "opened", symbol="XAUUSD"),
        _decision("b", "opened", symbol="BTCUSD"),
        _decision("c", "opened", symbol="XAUUSD"),
    ]

    (funnel,) = build_funnels(decisions)

    assert funnel.symbols == ("BTCUSD", "XAUUSD")


def test_no_decisions_is_an_empty_funnel_not_a_crash():
    assert build_funnels([]) == []
