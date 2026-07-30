"""Pure aggregation logic for the analytics dashboard (journal/domain/analytics.py)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from src.journal.domain.analytics import compute_bot_analytics, compute_symbol_analytics
from src.journal.domain.models import CandleSnapshot, TradeAnalyticsRecord, TradeRecord


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_record(id: str, symbol: str = "XAUUSD", **kw) -> TradeRecord:
    defaults = dict(
        id=id,
        symbol=symbol,
        side="buy",
        volume=0.1,
        open_price=2400.35,
        open_time=utc(2026, 7, 10, 14, 0),
        sl=2390.0,
        tp=2420.0,
        spread_points_at_entry=25,
        comment="",
    )
    return TradeRecord(**{**defaults, **kw})


# ── compute_symbol_analytics ────────────────────────────────────────────────


def test_symbol_analytics_aggregates_wins_losses_and_open_trades():
    trades = [
        make_record(
            "1",
            symbol="XAUUSD",
            skill="normal/xauusd/a",
            open_time=utc(2026, 7, 10, 14, 0),
            close_time=utc(2026, 7, 10, 15, 0),
            profit=10.0,
        ),
        make_record(
            "2",
            symbol="XAUUSD",
            skill="normal/xauusd/b",
            open_time=utc(2026, 7, 10, 15, 0),
            close_time=utc(2026, 7, 10, 16, 0),
            profit=-4.0,
        ),
        make_record("3", symbol="XAUUSD", open_time=utc(2026, 7, 10, 16, 0)),  # still open
        make_record(
            "4",
            symbol="EURUSD",
            open_time=utc(2026, 7, 10, 17, 0),
            close_time=utc(2026, 7, 10, 18, 0),
            profit=2.0,
        ),
    ]

    results = compute_symbol_analytics(trades)

    xau = next(r for r in results if r.symbol == "XAUUSD")
    assert xau.trade_count == 3
    assert xau.open_count == 1
    assert xau.closed_count == 2
    assert xau.win_count == 1
    assert xau.loss_count == 1
    assert xau.win_rate == 0.5
    assert xau.total_profit == 6.0
    assert xau.gross_profit == 10.0
    assert xau.gross_loss == 4.0
    assert xau.profit_factor == 2.5
    assert xau.bot_count == 2

    eur = next(r for r in results if r.symbol == "EURUSD")
    assert eur.closed_count == 1
    assert eur.win_rate == 1.0


def test_symbol_analytics_sorted_by_total_profit_descending():
    trades = [
        make_record("1", symbol="A", close_time=utc(2026, 7, 10, 15, 0), profit=1.0),
        make_record("2", symbol="B", close_time=utc(2026, 7, 10, 15, 0), profit=50.0),
    ]

    results = compute_symbol_analytics(trades)

    assert [r.symbol for r in results] == ["B", "A"]


def test_symbol_analytics_profit_factor_none_with_no_losses():
    trades = [make_record("1", close_time=utc(2026, 7, 10, 15, 0), profit=5.0)]

    result = compute_symbol_analytics(trades)[0]

    assert result.profit_factor is None


# ── slim TradeAnalyticsRecord projection (optimization: repository.py's
#    get_all_for_analytics skips the JSON snapshot/structure columns this
#    aggregation never reads) ─────────────────────────────────────────────


def _to_analytics_record(record: TradeRecord) -> TradeAnalyticsRecord:
    """Mirrors what `JournalRepository.get_all_for_analytics` projects from a
    full row — only the fields `compute_symbol_analytics`/`compute_bot_analytics`
    actually touch."""
    return TradeAnalyticsRecord(
        id=record.id,
        symbol=record.symbol,
        volume=record.volume,
        open_time=record.open_time,
        close_time=record.close_time,
        profit=record.profit,
        skill=record.skill,
        strategy_version=record.strategy_version,
    )


def _make_full_trades() -> list[TradeRecord]:
    snapshot = (
        CandleSnapshot(
            time=utc(2026, 7, 10, 13, 55), open=1, high=2, low=0.5, close=1.5, tick_volume=100
        ),
    )
    return [
        make_record(
            "1",
            symbol="XAUUSD",
            skill="normal/xauusd/a",
            strategy_version="breakout_v1:v1",
            volume=0.2,
            open_time=utc(2026, 7, 10, 14, 0),
            close_time=utc(2026, 7, 10, 15, 0),
            profit=10.0,
            m5_entry_snapshot=snapshot,
            h1_entry_snapshot=snapshot,
            m5_exit_snapshot=snapshot,
            h1_exit_snapshot=snapshot,
            reason="RBR base retest",
            confidence=0.82,
            zone_kind="demand",
            structure=(("HL", 2397.2, utc(2026, 7, 10, 13, 30)),),
        ),
        make_record(
            "2",
            symbol="XAUUSD",
            skill="normal/xauusd/b",
            strategy_version="breakout_v1:v1",
            volume=0.1,
            open_time=utc(2026, 7, 10, 15, 0),
            close_time=utc(2026, 7, 10, 16, 0),
            profit=-4.0,
        ),
        make_record(
            "3",
            symbol="XAUUSD",
            open_time=utc(2026, 7, 10, 16, 0),
        ),  # still open
        make_record(
            "4",
            symbol="EURUSD",
            skill="normal/eurusd/a",
            strategy_version="meanrev_v2:v1",
            open_time=utc(2026, 7, 10, 17, 0),
            close_time=utc(2026, 7, 10, 18, 0),
            profit=2.0,
        ),
    ]


def test_compute_symbol_analytics_bit_identical_for_slim_records():
    full_trades = _make_full_trades()
    slim_trades = [_to_analytics_record(t) for t in full_trades]

    assert compute_symbol_analytics(slim_trades) == compute_symbol_analytics(full_trades)


def test_compute_bot_analytics_bit_identical_for_slim_records():
    full_trades = _make_full_trades()
    slim_trades = [_to_analytics_record(t) for t in full_trades]

    assert compute_bot_analytics(slim_trades) == compute_bot_analytics(full_trades)


def test_trade_analytics_record_has_no_json_snapshot_or_structure_fields():
    """The slim projection must not carry the four JSON columns
    (m5/h1_entry/exit_snapshot, structure) that analytics.py never reads —
    that's the whole point of `get_all_for_analytics` over `get_all`."""
    field_names = {f.name for f in dataclasses.fields(TradeAnalyticsRecord)}
    assert field_names == {
        "id",
        "symbol",
        "volume",
        "open_time",
        "close_time",
        "profit",
        "skill",
        "strategy_version",
    }
    excluded = {
        "m5_entry_snapshot",
        "h1_entry_snapshot",
        "m5_exit_snapshot",
        "h1_exit_snapshot",
        "structure",
    }
    assert field_names.isdisjoint(excluded)


def test_symbol_analytics_empty_input_returns_empty_list():
    assert compute_symbol_analytics([]) == []


# ── compute_bot_analytics ───────────────────────────────────────────────────


def test_bot_analytics_excludes_trades_with_no_skill():
    trades = [
        make_record(
            "1", skill="normal/xauusd/a", close_time=utc(2026, 7, 10, 15, 0), profit=5.0
        ),
        make_record("2", skill=None, close_time=utc(2026, 7, 10, 15, 0), profit=100.0),
    ]

    results = compute_bot_analytics(trades)

    assert len(results) == 1
    assert results[0].skill == "normal/xauusd/a"


def test_bot_analytics_computes_equity_curve_and_drawdown():
    trades = [
        make_record(
            "1",
            skill="normal/xauusd/a",
            open_time=utc(2026, 7, 10, 14, 0),
            close_time=utc(2026, 7, 10, 15, 0),
            profit=10.0,
        ),
        make_record(
            "2",
            skill="normal/xauusd/a",
            open_time=utc(2026, 7, 10, 15, 0),
            close_time=utc(2026, 7, 10, 16, 0),
            profit=-15.0,
        ),
        make_record(
            "3",
            skill="normal/xauusd/a",
            open_time=utc(2026, 7, 10, 16, 0),
            close_time=utc(2026, 7, 10, 17, 0),
            profit=8.0,
        ),
    ]

    bot = compute_bot_analytics(trades)[0]

    assert [p.cumulative_profit for p in bot.equity_curve] == [10.0, -5.0, 3.0]
    # peak 10 -> trough -5 => drawdown 15
    assert bot.max_drawdown == 15.0
    assert bot.total_profit == 3.0
    assert bot.win_count == 2
    assert bot.loss_count == 1
    assert bot.expectancy == 1.0
    assert bot.avg_trade_duration_seconds == 3600.0


def test_bot_analytics_bot_name_and_symbol_derived_from_skill_and_latest_trade():
    trades = [
        make_record(
            "1",
            symbol="XAUUSD",
            skill="normal/xauusd/breakout_v1",
            strategy_version="breakout_v1:v1",
            open_time=utc(2026, 7, 10, 14, 0),
            close_time=utc(2026, 7, 10, 15, 0),
            profit=1.0,
        )
    ]

    bot = compute_bot_analytics(trades)[0]

    assert bot.bot_name == "breakout_v1"
    assert bot.symbol == "XAUUSD"
    assert bot.strategy_version == "breakout_v1:v1"


def test_bot_analytics_sorted_by_total_profit_descending():
    trades = [
        make_record(
            "1", skill="normal/a/x", close_time=utc(2026, 7, 10, 15, 0), profit=1.0
        ),
        make_record(
            "2", skill="normal/b/y", close_time=utc(2026, 7, 10, 15, 0), profit=99.0
        ),
    ]

    results = compute_bot_analytics(trades)

    assert [r.skill for r in results] == ["normal/b/y", "normal/a/x"]


def test_bot_analytics_max_drawdown_zero_when_curve_never_dips():
    trades = [
        make_record(
            "1", skill="normal/a/x", close_time=utc(2026, 7, 10, 15, 0), profit=1.0
        ),
        make_record(
            "2", skill="normal/a/x", close_time=utc(2026, 7, 10, 16, 0), profit=2.0
        ),
    ]

    bot = compute_bot_analytics(trades)[0]

    assert bot.max_drawdown == 0.0
