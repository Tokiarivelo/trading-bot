"""Contract tests run against a stubbed MetaTrader5 module (Linux-friendly).

The stub mimics the official package's shapes: numpy-style subscriptable rows
for rates, attribute objects for account/terminal/symbol info.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gateway import mt5_client
from gateway.main import app


class FakeMt5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408

    def __init__(self) -> None:
        self.reject_login = False
        self.shutdown_called = False

    def initialize(self) -> bool:
        return True

    def login(self, login, password=None, server=None) -> bool:
        return not self.reject_login

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self):
        return (-6, "Authorization failed")

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        return SimpleNamespace(
            login=123456,
            server="Demo-Server",
            name="Test User",
            currency="USD",
            balance=10_000.0,
            equity=10_050.0,
            leverage=100,
        )

    def symbol_select(self, symbol, enable) -> bool:
        return True

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        base = 1_752_100_500  # aligned to a 5-min boundary
        return [
            {
                "time": base + i * 300,
                "open": 2400.0 + i,
                "high": 2401.0 + i,
                "low": 2399.0 + i,
                "close": 2400.5 + i,
                "tick_volume": 1000 + i,
                "spread": 25,
            }
            for i in range(min(count, 3))
        ]

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=1_752_100_812, bid=2400.10, ask=2400.35)

    def symbol_info(self, symbol):
        return SimpleNamespace(
            name=symbol,
            bid=2400.10,
            ask=2400.35,
            spread=25,
            point=0.01,
            digits=2,
            trade_stops_level=10,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )


@pytest.fixture
def fake_mt5(monkeypatch) -> FakeMt5:
    fake = FakeMt5()
    monkeypatch.setattr(mt5_client, "mt5", fake)
    monkeypatch.setattr(mt5_client.client, "_connected", False)
    return fake


@pytest.fixture
def api(fake_mt5) -> TestClient:
    return TestClient(app)
