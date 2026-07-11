"""Pydantic models shared over the wire between gateway and backend.

The backend's market_data/broker adapters parse exactly these shapes —
change them in lockstep.
"""

from __future__ import annotations

from pydantic import BaseModel

VALID_TIMEFRAMES = ("M1", "M5", "H1", "H4", "D1")


class LoginRequest(BaseModel):
    login: int
    password: str
    server: str


class AccountInfoOut(BaseModel):
    login: int
    server: str
    name: str
    currency: str
    balance: float
    equity: float
    leverage: int


class HealthOut(BaseModel):
    status: str
    terminal_connected: bool
    account: AccountInfoOut | None = None


class CandleOut(BaseModel):
    time: int  # bar open time, epoch seconds UTC
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int  # points, as recorded on the bar


class TickOut(BaseModel):
    time: int  # epoch seconds UTC
    bid: float
    ask: float


class BrokerSymbolOut(BaseModel):
    name: str
    description: str
    path: str  # broker's Market Watch group, e.g. "Forex\\Majors"
    visible: bool  # already in Market Watch (candle/tick calls auto-add it either way)


class BrokerSymbolPageOut(BaseModel):
    items: list[BrokerSymbolOut]
    total: int  # count after search filtering, before limit/offset — for pagination


class SymbolInfoOut(BaseModel):
    symbol: str
    bid: float
    ask: float
    spread_points: int  # live spread in points
    point: float
    digits: int
    stops_level: int  # broker min SL/TP distance in points
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float


VALID_SIDES = ("buy", "sell")


class OrderRequest(BaseModel):
    symbol: str
    side: str  # "buy" | "sell"
    volume: float
    sl: float | None = None
    tp: float | None = None
    comment: str = ""


class OrderResultOut(BaseModel):
    ticket: int
    symbol: str
    side: str
    volume: float
    price: float
    sl: float | None
    tp: float | None
    time: int  # epoch seconds UTC
    spread_points: int
    comment: str = ""
    profit: float | None = None  # populated on close, None on open


class ModifyRequest(BaseModel):
    sl: float | None = None
    tp: float | None = None


class CloseRequest(BaseModel):
    volume: float | None = None  # None = close in full


class PositionOut(BaseModel):
    ticket: int
    symbol: str
    side: str
    volume: float
    open_price: float
    sl: float | None
    tp: float | None
    open_time: int
    profit: float
    comment: str = ""
