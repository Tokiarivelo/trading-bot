"""The ONLY file in the whole repository that imports MetaTrader5.

Wraps the official package (Windows/Wine only) in a thin client that returns
plain dicts matching `schemas.py`. No business logic: raw broker facts in,
explicit commands out. Credentials are held in memory only — never persisted
or logged here.

On non-Windows platforms the import fails and every call raises Mt5Error, so
the module stays importable for tests (which stub the `mt5` attribute).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - Linux dev machines
    mt5 = None


class Mt5Error(Exception):
    """Raised when the terminal is unreachable or a call is rejected."""


def _last_error() -> str:
    code, message = mt5.last_error()
    return f"[{code}] {message}"


class Mt5Client:
    """Stateful connection to the local MT5 terminal (one account at a time)."""

    def __init__(self) -> None:
        self._connected = False

    # ── session ─────────────────────────────────────────────────────────

    def login(self, login: int, password: str, server: str) -> dict[str, Any]:
        if mt5 is None:
            raise Mt5Error("MetaTrader5 package unavailable — run the gateway on Windows/Wine")
        if not mt5.initialize():
            raise Mt5Error(f"terminal initialize failed: {_last_error()}")
        if not mt5.login(login, password=password, server=server):
            raise Mt5Error(f"login rejected: {_last_error()}")
        self._connected = True
        logger.info("logged in to %s as %s", server, login)
        return self.account_info()

    def logout(self) -> None:
        if mt5 is not None:
            mt5.shutdown()
        self._connected = False
        logger.info("terminal connection shut down")

    def health(self) -> dict[str, Any]:
        if mt5 is None or not self._connected:
            return {"status": "ok", "terminal_connected": False, "account": None}
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            return {"status": "ok", "terminal_connected": False, "account": None}
        return {"status": "ok", "terminal_connected": True, "account": self.account_info()}

    def account_info(self) -> dict[str, Any]:
        self._require_connection()
        info = mt5.account_info()
        if info is None:
            raise Mt5Error(f"account_info failed: {_last_error()}")
        return {
            "login": info.login,
            "server": info.server,
            "name": info.name,
            "currency": info.currency,
            "balance": info.balance,
            "equity": info.equity,
            "leverage": info.leverage,
        }

    # ── market data ─────────────────────────────────────────────────────

    def candles(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        self._require_connection()
        self._select(symbol)
        rates = mt5.copy_rates_from_pos(symbol, self._timeframe(timeframe), 0, count)
        if rates is None:
            raise Mt5Error(f"copy_rates_from_pos({symbol},{timeframe}) failed: {_last_error()}")
        return [
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "tick_volume": int(r["tick_volume"]),
                "spread": int(r["spread"]),
            }
            for r in rates
        ]

    def tick(self, symbol: str) -> dict[str, Any]:
        self._require_connection()
        self._select(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise Mt5Error(f"symbol_info_tick({symbol}) failed: {_last_error()}")
        return {"time": int(tick.time), "bid": float(tick.bid), "ask": float(tick.ask)}

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        self._require_connection()
        self._select(symbol)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise Mt5Error(f"symbol_info({symbol}) failed: {_last_error()}")
        return {
            "symbol": info.name,
            "bid": float(info.bid),
            "ask": float(info.ask),
            "spread_points": int(info.spread),
            "point": float(info.point),
            "digits": int(info.digits),
            "stops_level": int(info.trade_stops_level),
            "contract_size": float(info.trade_contract_size),
            "volume_min": float(info.volume_min),
            "volume_max": float(info.volume_max),
            "volume_step": float(info.volume_step),
        }

    # ── internals ───────────────────────────────────────────────────────

    def _require_connection(self) -> None:
        if mt5 is None:
            raise Mt5Error("MetaTrader5 package unavailable — run the gateway on Windows/Wine")
        if not self._connected:
            raise Mt5Error("not logged in — POST /login first")

    def _select(self, symbol: str) -> None:
        # Symbols must be in Market Watch before data calls return anything.
        if not mt5.symbol_select(symbol, True):
            raise Mt5Error(f"symbol_select({symbol}) failed: {_last_error()}")

    @staticmethod
    def _timeframe(timeframe: str) -> int:
        try:
            return getattr(mt5, f"TIMEFRAME_{timeframe}")
        except AttributeError:
            raise Mt5Error(f"unsupported timeframe {timeframe!r}") from None


client = Mt5Client()
