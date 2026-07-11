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


class FakePosition:
    def __init__(
        self, ticket, symbol, type_, volume, price_open, sl, tp, time, profit, comment=""
    ) -> None:
        self.ticket = ticket
        self.symbol = symbol
        self.type = type_
        self.volume = volume
        self.price_open = price_open
        self.sl = sl
        self.tp = tp
        self.time = time
        self.profit = profit
        self.comment = comment


class FakeMt5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408

    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009

    def __init__(self) -> None:
        self.reject_login = False
        self.shutdown_called = False
        self.reject_order = False
        self._next_ticket = 1000
        self._positions: dict[int, FakePosition] = {}

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

    def symbols_get(self):
        return [
            SimpleNamespace(
                name="XAUUSD", description="Gold vs US Dollar", path="Metals", visible=True
            ),
            SimpleNamespace(
                name="XAGUSD", description="Silver vs US Dollar", path="Metals", visible=True
            ),
            SimpleNamespace(
                name="EURUSD", description="Euro vs US Dollar", path="Forex\\Majors", visible=False
            ),
            SimpleNamespace(
                name="BTCUSD", description="Bitcoin vs US Dollar", path="Crypto", visible=True
            ),
        ]

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

    def order_send(self, request):
        if self.reject_order:
            return SimpleNamespace(retcode=10004, order=0, volume=0.0, price=0.0)
        if request["action"] == self.TRADE_ACTION_SLTP:
            position = self._positions.get(request["position"])
            if position is not None:
                position.sl = request.get("sl") or None
                position.tp = request.get("tp") or None
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE, order=request["position"], volume=0.0, price=0.0
            )
        if "position" in request:
            ticket = request["position"]
            position = self._positions.get(ticket)
            close_volume = request["volume"]
            if position is not None:
                if close_volume >= position.volume:
                    del self._positions[ticket]
                else:
                    position.volume -= close_volume
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE,
                order=ticket,
                volume=close_volume,
                price=request["price"],
            )
        ticket = self._next_ticket
        self._next_ticket += 1
        self._positions[ticket] = FakePosition(
            ticket=ticket,
            symbol=request["symbol"],
            type_=request["type"],
            volume=request["volume"],
            price_open=request["price"],
            sl=request["sl"] or None,
            tp=request["tp"] or None,
            time=1_752_100_812,
            profit=12.5,
            comment=request.get("comment", ""),
        )
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=ticket,
            volume=request["volume"],
            price=request["price"],
        )

    def positions_get(self, symbol=None, ticket=None):
        rows = list(self._positions.values())
        if ticket is not None:
            rows = [p for p in rows if p.ticket == ticket]
        if symbol is not None:
            rows = [p for p in rows if p.symbol == symbol]
        return rows


@pytest.fixture
def fake_mt5(monkeypatch) -> FakeMt5:
    fake = FakeMt5()
    monkeypatch.setattr(mt5_client, "mt5", fake)
    monkeypatch.setattr(mt5_client.client, "_connected", False)
    return fake


@pytest.fixture
def api(fake_mt5) -> TestClient:
    return TestClient(app)
