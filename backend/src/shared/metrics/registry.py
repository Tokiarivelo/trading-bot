"""Prometheus metrics registry (OBSERVABILITY_PLAN.md Phase 5).

One process-wide `CollectorRegistry` — not the `prometheus_client` global
default — so this module can be imported freely by tests without polluting
(or colliding with) any other registry in the same process. `GET /metrics`
(see `src.main`) serves exactly this registry via `generate_latest`.

Every helper here is safe to call unconditionally from application code: none
of them raise, none of them require a database or gateway connection, and
none of them change any trading decision — this module is observation only
(CLAUDE.md's "Constraints" for this phase). Call sites label metrics from
`current_account_id` (the same `ContextVar` `shared/logging/account_context.py`
already uses to stamp log rows) wherever the call happens inside an account's
own background task; the few call sites where that ContextVar isn't reliably
set (e.g. a manual REST order placed through `/accounts/{id}/broker/orders`
on a non-default account, outside any account-bound background task) fall
back to its `"default"` default — the same pre-existing limitation the
account_id log stamping already has, not a new gap this phase introduces.

Kept dependency-free of any *specific* module (market_data, broker, engine):
composition-root wiring that needs one (e.g. sampling the Socket.IO client
count) is done from `src.main`/`src.container`, which already import those
modules — see `set_ws_client_source` below.
"""

from __future__ import annotations

from collections.abc import Callable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from src.activity.domain.models import SIGNAL_OUTCOMES
from src.shared.logging.account_context import current_account_id

REGISTRY = CollectorRegistry()

_NAMESPACE = "tradingbot"

ENGINE_LOOP_DURATION = Histogram(
    f"{_NAMESPACE}_engine_loop_duration_seconds",
    "Wall-clock time TradeEngine.on_candle_closed spends per candle close "
    "(position management + entry evaluation for every candidate bot), per "
    "account.",
    labelnames=("account_id",),
    registry=REGISTRY,
)

GATEWAY_REQUEST_DURATION = Histogram(
    f"{_NAMESPACE}_gateway_request_duration_seconds",
    "Round-trip time of HTTP requests from the backend to the MT5 gateway, "
    "per account/method/path.",
    labelnames=("account_id", "method", "path"),
    registry=REGISTRY,
)

SIGNALS_TOTAL = Counter(
    f"{_NAMESPACE}_signals_total",
    "Strategy signals fired, before any gate evaluates them. Divide by the "
    "query window (e.g. PromQL `rate(tradingbot_signals_total[1m])`) for "
    "signals/min.",
    labelnames=("account_id", "bot", "symbol"),
    registry=REGISTRY,
)

SIGNAL_OUTCOMES_TOTAL = Counter(
    f"{_NAMESPACE}_signal_outcomes_total",
    "Terminal signal outcomes by reason, in the same closed vocabulary as "
    "SIGNAL_OUTCOMES (src.activity.domain.models — OBSERVABILITY_PLAN.md "
    "Phase 2's veto funnel), so this metric and `GET "
    "/accounts/{account_id}/activity/signals/funnel` never disagree about "
    "what a reason is called.",
    labelnames=("account_id", "outcome"),
    registry=REGISTRY,
)

OPEN_POSITIONS = Gauge(
    f"{_NAMESPACE}_open_positions",
    "Currently open broker positions, per account. Updated from "
    "PositionOpened/PositionClosed event-bus subscriptions (wired in "
    "container.py) rather than counted at scrape time, so a scrape never "
    "blocks on a gateway round trip; this also means it stays correct for "
    "broker-side closes picked up by reconciliation, not just closes routed "
    "through OrderService.",
    labelnames=("account_id",),
    registry=REGISTRY,
)

WS_CLIENTS = Gauge(
    f"{_NAMESPACE}_ws_clients_connected",
    "Currently connected Socket.IO clients. Process-wide (one transport "
    "connection can hold rooms across several accounts at once, e.g. a "
    "multi-window chart layout, so there is no single account to label it "
    "with) — sampled at scrape time via set_function, see "
    "set_ws_client_source below and its call site in src.main's lifespan.",
    registry=REGISTRY,
)


def observe_signal_fired(*, bot: str, symbol: str) -> None:
    """Called once per strategy signal, before any gate — the numerator for
    signals/min."""
    SIGNALS_TOTAL.labels(account_id=current_account_id.get(), bot=bot, symbol=symbol).inc()


def record_signal_outcome(outcome: str) -> None:
    """`outcome` is expected to be one of `SIGNAL_OUTCOMES` — every call site
    in `engine/application/trade_loop.py` and `broker/application/
    order_service.py` already draws from that vocabulary (it's the same
    string persisted to the `signal_decisions` table). Anything else is
    folded into `"unknown"` rather than silently minting a label value the
    veto funnel doesn't know about, mirroring `activity.domain.funnel`'s own
    `_UNKNOWN_STAGE` handling of an unrecognized outcome."""
    label = outcome if outcome in SIGNAL_OUTCOMES else "unknown"
    SIGNAL_OUTCOMES_TOTAL.labels(account_id=current_account_id.get(), outcome=label).inc()


def observe_gateway_rtt(*, account_id: str, method: str, path: str, seconds: float) -> None:
    GATEWAY_REQUEST_DURATION.labels(account_id=account_id, method=method, path=path).observe(
        seconds
    )


def position_opened(*, account_id: str) -> None:
    OPEN_POSITIONS.labels(account_id=account_id).inc()


def position_closed(*, account_id: str) -> None:
    OPEN_POSITIONS.labels(account_id=account_id).dec()


def set_open_positions(*, account_id: str, count: int) -> None:
    """Seeds the gauge from a ground-truth count — called once at startup
    after reconciliation (see `src.main`'s lifespan), so a backend restart
    doesn't report zero open positions until the next open/close event."""
    OPEN_POSITIONS.labels(account_id=account_id).set(count)


def set_ws_client_source(source: Callable[[], int]) -> None:
    """Wires `WS_CLIENTS` to sample `source()` at scrape time instead of
    being incremented/decremented by hand at every connect/disconnect.
    Called once at startup with a closure reading `len(sio.eio.sockets)` —
    kept out of this module's own imports so `shared/metrics` never has to
    import `market_data` (that wiring belongs in the composition root,
    `src.main`/`src.container`, not here)."""
    WS_CLIENTS.set_function(source)
