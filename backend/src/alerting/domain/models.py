"""Alerting domain (Phase 9) — pure values, no I/O.

`AlertingConfig` mirrors `configs/alerting.yaml`; secrets (bot token, chat
id, SMTP credentials) never live here or in that file — they come from
`Settings`/`.env`, same secrets-vs-config split as the rest of the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, kw_only=True)
class AlertMessage:
    title: str
    body: str
    level: AlertLevel = AlertLevel.INFO


@dataclass(frozen=True, kw_only=True)
class AlertEventFlags:
    fills: bool = True
    circuit_breaker: bool = True
    refinements: bool = True
    gateway_disconnect: bool = True
    bot_silence: bool = True
    """A bot fired no signal for N times its own median inter-signal
    interval (OBSERVABILITY_PLAN.md Phase 5) — see `SilenceConfig` below."""


@dataclass(frozen=True, kw_only=True)
class SilenceConfig:
    """Tuning for `activity.application.silence_monitor.SilenceMonitor`
    (OBSERVABILITY_PLAN.md Phase 5) — how aggressively "no signal in a
    while" is treated as "this bot is dead" rather than "the market's quiet
    right now"."""

    poll_interval_s: float = 900.0
    lookback_days: int = 30
    multiplier: float = 5.0
    min_signals: int = 5


@dataclass(frozen=True, kw_only=True)
class AlertingConfig:
    telegram_enabled: bool = False
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    from_address: str = ""
    to_address: str = ""
    events: AlertEventFlags = AlertEventFlags()
    silence: SilenceConfig = SilenceConfig()
