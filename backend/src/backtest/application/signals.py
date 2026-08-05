"""Extract structured `BacktestSignal`s from the replay's decision trail.

The engine logs one `SIGNAL: ...` line per strategy signal, followed (same
simulated clock tick, before the next signal) by exactly one outcome line —
an HTF veto, a risk-sizing rejection, a spread/RR-gate rejection, or the
fill. Rather than modifying the engine to publish a dedicated event (engine
code is off-limits to backtest changes, see CLAUDE.md), this parses those
lines back into data the report/UI can render: every valid setup the
strategy saw, and what happened to it.

The line prefixes matched here are owned by `TradeEngine._try_enter`
(`SIGNAL:`, `ENTRY BLOCKED (HTF veto):`) and `OrderService.open_position`
(`ENTRY REJECTED (spread/RR gate):`, `ENTRY OPENED:`) plus the risk-sizing
rejection in the trade loop (`ENTRY REJECTED (risk sizing):`) — if those
messages are ever reworded, update this module in the same change.

`SIGNAL:` lines also carry a `skill=<name>` token (added for multi-bot
attribution, §6.6) between `strategy=<name>` and the reason — matched and
discarded here since a backtest always runs a single strategy under
`FixedSkillSelector`'s fixed `skill="backtest"`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.backtest.domain.models import ActivityLogEntry, BacktestSignal

# Current format (multi-target engine, bdab6e1 onward):
#   "SIGNAL: XAUUSD sell @ 2412.35000 (2 target position(s)) via
#    strategy=pob_snd_zones_xauusd skill=backtest — <reason>"
# The "@ <price>" and "(N target position(s))" segments are both optional so
# legacy lines still parse. Symbols may contain spaces ("Volatility 75
# Index"), so anchor on the literal " via strategy=" / " — " delimiters
# rather than \S+.
_SIGNAL_RE = re.compile(
    r"^SIGNAL: .+? (?P<direction>buy|sell)"
    r"(?: @ (?P<price>-?\d+(?:\.\d+)?))?"
    r"(?: \(\d+ target position\(s\)\))?"
    r" via strategy=.+? skill=.+? — (?P<reason>.*)$"
)

# Closed vocabulary — the chart indexes `SIGNAL_OUTCOME_META[outcome]`
# unguarded, so new guard lines map onto an existing value.
_OUTCOME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ENTRY OPENED:", "opened"),
    ("ENTRY BLOCKED (HTF veto):", "htf_veto"),
    ("ENTRY BLOCKED (risk gate):", "risk_rejected"),
    ("ENTRY BLOCKED (volatility guard):", "risk_rejected"),
    ("ENTRY BLOCKED (max open positions cap reached):", "risk_rejected"),
    ("ENTRY REJECTED (risk sizing):", "risk_rejected"),
    ("ENTRY REJECTED (spread/RR gate):", "spread_veto"),
    ("ENTRY REJECTED (broker):", "broker_rejected"),
    ("ENTRY SKIPPED (no account connected):", "skipped"),
)

_EXPLANATION_SEP = " — "


def _merge_reason(reason: str, message: str) -> str:
    """Append the outcome line's own ` — <explanation>` tail (veto reason,
    sizing failure) onto the signal's reason. `ENTRY OPENED:` lines have none."""
    _, sep, tail = message.partition(_EXPLANATION_SEP)
    explanation = tail.strip()
    if not sep or not explanation or explanation in reason:
        return reason
    return f"{reason}{_EXPLANATION_SEP}{explanation}"


def extract_signals(entries: Sequence[ActivityLogEntry]) -> tuple[BacktestSignal, ...]:
    """One `BacktestSignal` per `SIGNAL:` line, with `outcome` taken from the
    first outcome line that follows it (before the next signal). A signal
    with no outcome line at all — which the current engine flow never
    produces — is recorded as "skipped" rather than dropped, so the report
    never undercounts what the strategy emitted."""
    signals: list[BacktestSignal] = []
    pending: BacktestSignal | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            signals.append(pending)
            pending = None

    for entry in entries:
        match = _SIGNAL_RE.match(entry.message)
        if match is not None:
            flush()
            pending = BacktestSignal(
                time=entry.time,
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
                    BacktestSignal(
                        time=pending.time,
                        direction=pending.direction,
                        outcome=outcome,
                        reason=_merge_reason(pending.reason, entry.message),
                    )
                )
                pending = None
                break
    flush()
    return tuple(signals)
