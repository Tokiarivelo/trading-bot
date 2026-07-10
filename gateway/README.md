# MT5 Gateway

The only component that talks to MetaTrader 5. It wraps the official
`MetaTrader5` Python package (Windows-only) behind a small FastAPI HTTP API so
the rest of the system can run natively on Linux.

**No business logic lives here** — the gateway reports broker facts (candles,
ticks, spread, positions) and executes explicit order commands. All decisions
happen in `backend/`.

## Why it exists

The `MetaTrader5` pip package requires a running MT5 **desktop terminal** and
only works on Windows. Options:

| Option | Use for |
|--------|---------|
| Wine on Linux | Development on this machine |
| Windows VPS | 24/7 live trading (recommended for Phase 9) |

## Option A — Wine (development)

1. Install Wine (Ubuntu):
   ```bash
   sudo dpkg --add-architecture i386
   sudo apt update && sudo apt install --install-recommends wine64 wine32 winetricks
   ```
2. Install MT5 terminal under Wine (download `mt5setup.exe` from your broker):
   ```bash
   wine mt5setup.exe
   ```
3. Install **Windows** Python 3.12 under the same Wine prefix:
   ```bash
   wine python-3.12.x-amd64.exe /quiet InstallAllUsers=0 PrependPath=1
   ```
4. Install gateway deps with Windows pip and start it:
   ```bash
   wine python -m pip install MetaTrader5 fastapi uvicorn pydantic
   cd gateway
   wine python -m uvicorn src.gateway.main:app --host 127.0.0.1 --port 8787
   ```
5. Keep the MT5 terminal running (logged into your **demo** account first).
   The backend reaches the gateway at `TB_GATEWAY_URL` (default
   `http://127.0.0.1:8787`).

## Option B — Windows VPS (live)

1. Rent a Windows VPS near your broker's servers.
2. Install MT5 terminal + Python 3.12, then `pip install MetaTrader5 fastapi uvicorn pydantic`.
3. Run the gateway as a service (NSSM or Task Scheduler), bound to a private
   interface. Connect backend↔gateway over WireGuard or an SSH tunnel — never
   expose the gateway to the public internet.
4. Set `TB_GATEWAY_URL` and `TB_GATEWAY_SHARED_SECRET` in the backend `.env`;
   the gateway rejects requests without the matching secret header.

## API (implemented in Phase 1)

| Endpoint | Purpose |
|----------|---------|
| `POST /login` | Connect to an MT5 account (credentials held in memory only) |
| `GET /health` | Terminal & account connection status |
| `GET /candles` | OHLCV history (symbol, timeframe, count) |
| `GET /tick` | Latest bid/ask |
| `GET /symbol_info` | Contract specs + live spread + stops level |
| `POST /order` | Open/modify an order |
| `POST /close` | Close a position |
| `GET /positions` | Open positions |
