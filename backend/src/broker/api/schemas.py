"""Wire schemas for the `/account` and `/broker` HTTP APIs.

These are pure `BaseModel`s that mirror `broker/domain/account.py` and
`broker/domain/trading.py` — the domain stays framework-free (per CLAUDE.md),
and this module is where domain values get an explicit, documented HTTP
shape. Every field carries a description so it renders in `/docs`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AccountInfoOut(BaseModel):
    """A logged-in MT5 account's identity and balances."""

    login: int = Field(description="MT5 account number.")
    server: str = Field(description="Broker server name, e.g. 'MetaQuotes-Demo'.")
    name: str = Field(description="Account holder name as reported by the broker.")
    currency: str = Field(description="Account deposit currency, e.g. 'USD'.")
    balance: float = Field(description="Account balance excluding floating P/L.")
    equity: float = Field(description="Balance plus floating P/L of open positions.")
    leverage: int = Field(description="Account leverage, e.g. 100 for 1:100.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "login": 123456,
                "server": "MetaQuotes-Demo",
                "name": "Jane Trader",
                "currency": "USD",
                "balance": 10_000.0,
                "equity": 10_050.0,
                "leverage": 100,
            }
        }
    }


class ConnectRequest(BaseModel):
    """MT5 login credentials. Never logged, never echoed in responses."""

    login: int = Field(description="MT5 account number.")
    password: str = Field(min_length=1, description="MT5 account password.")
    server: str = Field(min_length=1, description="Broker server name.")
    remember: bool = Field(
        default=True,
        description="If true, encrypt and persist the credentials so the "
        "backend can silently reconnect on restart.",
    )


class ConnectResponse(BaseModel):
    connected: bool = Field(description="Always true on a 200 response.")
    account: AccountInfoOut


class DisconnectRequest(BaseModel):
    forget: bool = Field(
        default=False, description="If true, also erase any persisted credentials."
    )


class DisconnectResponse(BaseModel):
    connected: bool = Field(description="Always false on a 200 response.")


class AccountStatusOut(BaseModel):
    """Current connection state — polled by the UI's MT5 Account panel."""

    gateway_up: bool = Field(description="Whether the MT5 gateway HTTP service is reachable.")
    connected: bool = Field(description="Whether the gateway's MT5 terminal is logged in.")
    account: AccountInfoOut | None = Field(
        default=None, description="Present only when `connected` is true."
    )
    has_saved_credentials: bool = Field(
        description="Whether credentials are stored for silent auto-reconnect."
    )


class OpenOrderRequest(BaseModel):
    """Market order request. Rejected by the spread/RR gate before it ever
    reaches the broker if `sl`/`tp` don't clear `configs/symbols/*.yaml`."""

    symbol: str = Field(description="Trading symbol, e.g. 'XAUUSD'.")
    side: str = Field(description="Order direction: 'buy' or 'sell'.", examples=["buy"])
    volume: float = Field(gt=0, description="Lot size, > 0.")
    sl: float | None = Field(default=None, description="Stop loss price. Required by the RR gate.")
    tp: float | None = Field(
        default=None, description="Take profit price. Required by the RR gate."
    )
    comment: str = Field(default="", description="Free-text order comment.")


class CloseOrderRequest(BaseModel):
    volume: float | None = Field(
        default=None, description="Partial close volume; omit or null to close in full."
    )


class ModifyOrderRequest(BaseModel):
    sl: float | None = Field(
        default=None, description="New stop loss price, or null to leave unchanged."
    )
    tp: float | None = Field(
        default=None, description="New take profit price, or null to leave unchanged."
    )


class ModifyOrderResponse(BaseModel):
    status: str = Field(description="'ok' on success.")


class ExecutionResultOut(BaseModel):
    """A broker fill — returned by both open and close order calls."""

    ticket: int = Field(description="Broker position ticket.")
    symbol: str
    side: str = Field(description="'buy' or 'sell'.")
    volume: float
    price: float = Field(description="Fill price.")
    sl: float | None
    tp: float | None
    time: str = Field(description="Fill time, ISO 8601 UTC.")
    spread_points: int = Field(description="Spread in points at fill time.")
    comment: str = ""
    profit: float | None = Field(
        default=None, description="Realized P/L. Populated on close fills, null on open fills."
    )


class PositionOut(BaseModel):
    """An open position as currently held at the broker."""

    ticket: int
    symbol: str
    side: str = Field(description="'buy' or 'sell'.")
    volume: float
    open_price: float
    sl: float | None
    tp: float | None
    open_time: str = Field(description="Position open time, ISO 8601 UTC.")
    profit: float = Field(description="Current floating P/L.")
    comment: str = ""
