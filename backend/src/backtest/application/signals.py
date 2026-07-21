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

# "SIGNAL: XAUUSD sell via strategy=pob_snd_zones_xauusd skill=backtest — <reason>"
_SIGNAL_RE = re.compile(
    r"^SIGNAL: \S+ (?P<direction>buy|sell) via strategy=\S+ skill=\S+ — (?P<reason>.*)$"
)

_OUTCOME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ENTRY OPENED:", "opened"),
    ("ENTRY BLOCKED (HTF veto):", "htf_veto"),
    ("ENTRY REJECTED (risk sizing):", "risk_rejected"),
    ("ENTRY REJECTED (spread/RR gate):", "spread_veto"),
)


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
                        reason=pending.reason,
                    )
                )
                pending = None
                break
    flush()
    return tuple(signals)
