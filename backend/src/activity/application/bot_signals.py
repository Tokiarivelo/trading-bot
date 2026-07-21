"""Reconstructs one live bot's `BotSignal`s from its own persisted decision-
trail log lines — the live analog of `backtest.application.signals.extract_signals`,
same log-scraping rationale (no dedicated event, engine code untouched), but
scoped to one `skill` among the several bots that may be logging concurrently
to the same `activity_logs` stream.

The engine logs one `SIGNAL: ...` line per strategy signal, followed (before
that bot's next signal) by exactly one outcome line for that same bot — an
HTF veto, a risk-sizing rejection, a spread/RR-gate rejection, a broker-level
rejection, or the fill. Several bots' lines interleave in the raw log stream,
which would break that "signal immediately followed by its own outcome"
adjacency — so entries are first filtered down to just the target skill's own
lines (every relevant line embeds `skill=<name>` or `[<name>]`, per
`TradeEngine`/`OrderService`'s multi-bot logging, §6.6) before pairing.

The line prefixes matched here are owned by `TradeEngine._try_enter`/
`_enter_for_bot` (`SIGNAL:`, `ENTRY BLOCKED (HTF veto):`,
`ENTRY REJECTED (risk sizing):`) and `OrderService.open_position`
(`ENTRY OPENED:`, `ENTRY REJECTED (spread/RR gate):`,
`ENTRY REJECTED (broker):`) — if those messages are ever reworded, update
this module in the same change.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.activity.domain.models import BotSignal, LogEntry

# "SIGNAL: XAUUSD buy via strategy=breakout_v1 skill=normal/xauusd/breakout_v1 — <reason>"
# Symbol and skill both may contain spaces ("Volatility 75 Index",
# "normal/volatility 75 index/..."), so neither can be matched with \S+ —
# anchor on the literal " via strategy=" / " — " delimiters instead.
_SIGNAL_RE = re.compile(
    r"^SIGNAL: .+? (?P<direction>buy|sell) via strategy=.+? skill=.+? — (?P<reason>.*)$"
)

# The token after the skill value is " — <reason>" on trade_loop/order_service
# reject lines and " magic=<n>" on ENTRY OPENED lines.
_SKILL_EQUALS_RE = re.compile(r"skill=(.+?)(?= magic=| — |$)")
_SKILL_BRACKET_RE = re.compile(r"\[([^\]]+)\]")

_OUTCOME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ENTRY OPENED:", "opened"),
    ("ENTRY BLOCKED (HTF veto):", "htf_veto"),
    ("ENTRY REJECTED (risk sizing):", "risk_rejected"),
    ("ENTRY REJECTED (spread/RR gate):", "spread_veto"),
    ("ENTRY REJECTED (broker):", "broker_rejected"),
)


def _line_skill(message: str) -> str | None:
    match = _SKILL_EQUALS_RE.search(message)
    if match is not None:
        return match.group(1)
    match = _SKILL_BRACKET_RE.search(message)
    return match.group(1) if match is not None else None


def extract_bot_signals(entries: Sequence[LogEntry], skill: str) -> list[BotSignal]:
    """One `BotSignal` per `SIGNAL:` line belonging to `skill`, with `outcome`
    taken from the first outcome line (also belonging to `skill`) that
    follows it. `entries` should already be time-ordered ascending (as
    `ActivityLogRepository.search` returns, reversed) and ideally pre-filtered
    to the `trade_loop`/`order_service` loggers — this function does the
    skill-scoping itself since a raw slice of the activity log interleaves
    every bot's lines."""
    own_entries = [e for e in entries if _line_skill(e.message) == skill]

    signals: list[BotSignal] = []
    pending: BotSignal | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            signals.append(pending)
            pending = None

    for entry in own_entries:
        match = _SIGNAL_RE.match(entry.message)
        if match is not None:
            flush()
            pending = BotSignal(
                time=entry.created_at,
                direction=match.group("direction"),
                outcome="skipped",
                reason=match.group("reason"),
            )
            continue
        if pending is None:
            continue
        for prefix, outcome in _OUTCOME_PREFIXES:
            if entry.message.startswith(prefix):
                signals.append(
                    BotSignal(
                        time=pending.time,
                        direction=pending.direction,
                        outcome=outcome,
                        reason=pending.reason,
                    )
                )
                pending = None
                break
    flush()
    return signals
