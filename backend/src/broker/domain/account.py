"""Broker account domain: credentials and account state. Pure values, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class Mt5Credentials:
    login: int
    password: str = field(repr=False)  # keep passwords out of repr/logs
    server: str


@dataclass(frozen=True, kw_only=True)
class AccountInfo:
    login: int
    server: str
    name: str
    currency: str
    balance: float
    equity: float
    leverage: int


@dataclass(frozen=True, kw_only=True)
class GatewayHealth:
    gateway_up: bool
    terminal_connected: bool
    account: AccountInfo | None = None


@dataclass(frozen=True, kw_only=True)
class AccountConfig:
    """One entry from `configs/accounts.yaml` — a broker account this
    backend can run against, reached through its own gateway process.

    `id` is a short slug, not the MT5 login number — it's the identity used
    downstream in API paths, DB rows, and credential file names.
    """

    id: str
    label: str
    gateway_url: str
    gateway_shared_secret_env: str
    mode: str  # "paper" | "live"
    enabled: bool = True
    risk_override_file: str | None = None


class BrokerUnavailable(Exception):
    """Gateway unreachable or the terminal rejected the request."""


class LoginRejected(Exception):
    """MT5 refused the credentials (bad login/password/server)."""
