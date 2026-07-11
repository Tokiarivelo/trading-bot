# Launching the stack

This is the practical, ordered checklist to get the app fully running end to
end. For MT5 gateway internals see `gateway/README.md` — this file is the
"do these steps in this order" version, tailored to the errors you'll hit if
you skip one.

## Do I need an MT5 login and password?

**Yes.** You need a broker **demo account**: a login number, password, and
server name (e.g. `MetaQuotes-Demo`). Get one from any MT5 broker — it's free
and instant.

That said, **the credentials never go in `.env`**. They are entered either:

- in the app UI's **MT5 Account** panel (`POST /account/connect`), or
- directly against the gateway for testing: `make mt5-login LOGIN=... PASSWORD=... SERVER=...`

`.env` only holds the *shared secret* the backend and gateway use to
authenticate to each other (`TB_GATEWAY_SHARED_SECRET` / `GATEWAY_SHARED_SECRET`)
— never your broker password.

**This is exactly what's causing the errors in your logs:**

```
GET /symbol_info?symbol=XAUUSD  → 502 Bad Gateway
GET /market-data/symbol-info    → 503 Service Unavailable
```

`/health` and `/account/status` return 200 because the gateway and backend
processes are both up — but no one has logged in to MT5 yet, so every call
that needs live broker data fails. Run `make doctor` to confirm:

```
$ make doctor
── gateway :8787/health ──
{"status":"ok","terminal_connected":false,"account":null}
```

`terminal_connected: false` is the tell. Fix it with step 5 below.

## Prerequisites

| Tool | Needed for |
|---|---|
| Python 3.12 + [uv](https://docs.astral.sh/uv) | backend, gateway |
| Node.js + pnpm (pinned in `frontend/package.json`) | frontend |
| Wine (Linux) **or** a Windows machine/VPS | the MT5 gateway — `MetaTrader5` only ships Windows wheels |
| An MT5 broker **demo account** (login, password, server) | connecting to MT5 at all |
| MT5 terminal installer (`mt5setup.exe`) | the terminal Wine/Windows runs |

## Step-by-step

### 1. Install dependencies + create `.env`

```bash
make setup
```

This runs `uv sync` for backend and gateway, `pnpm install` for frontend, and
creates `.env` from `.env.example` with a freshly generated random
`TB_GATEWAY_SHARED_SECRET` (no manual editing needed for local dev).

### 2. Apply database migrations

```bash
make db-upgrade
```

Creates `backend/data/trading.db` and applies all Alembic migrations. Skip if
`backend/data/trading.db` already exists and is up to date (`make db-history`
to check).

### 3. Set up Wine + the MT5 terminal (Linux dev machines only)

```bash
make setup-wine
```

Installs Wine/winetricks and creates a dedicated Wine prefix at `~/.mt5`
(override with `WINEPREFIX=...`). This only does the scriptable part — it
prints the remaining manual steps (installer downloads need your interaction):

```bash
export WINEPREFIX=~/.mt5
wine mt5setup.exe                                                    # install MT5 terminal
wine python-3.12.x-amd64.exe /quiet InstallAllUsers=0 PrependPath=1  # Windows Python (not Linux Python!)
wine python -m pip install MetaTrader5 fastapi uvicorn pydantic
```

Already on Windows, or deploying to a VPS instead? See "Option B — Windows
VPS" in `gateway/README.md` — skip `make setup-wine` and just install the
terminal + `pip install MetaTrader5 fastapi uvicorn pydantic` natively.

### 4. Start the MT5 terminal and log in — once, inside the terminal UI

```bash
make mt5-terminal   # launches terminal64.exe in the Wine prefix; leave it running
```

Inside the terminal:

1. **File → Login to Trade Account** → enter your demo login / password /
   server. Tick **Save password**.
2. **Tools → Options → Expert Advisors** → check **Allow algorithmic
   trading**, and make sure the toolbar's **Algo Trading** button is green.
   Skipping this makes every order call fail later with retcode `10027`.
3. Right-click **Market Watch → Symbols** → make **XAUUSD, XAGUSD, BTCUSD**
   visible. If your broker suffixes symbol names (e.g. `XAUUSD.a`), update
   `configs/app.yaml` and `configs/symbols/*.yaml` to match.
4. **Tools → Options → Charts** → set *Max bars in chart* to the max, then
   open an M5/H1/H4/D1 chart per symbol and scroll back once, so the terminal
   downloads history before you call `/market-data/backfill`.

Keep this terminal process running — the gateway only works while it's up
and connected.

### 5. Start everything

```bash
make dev            # backend + frontend + gateway together, or run separately:
make dev-backend     # http://localhost:8000
make dev-frontend    # http://localhost:3000
make dev-gateway      # http://localhost:8787 (needs the terminal from step 4 already running)
```

`make dev-gateway` and `make dev` now automatically pass the gateway
`WINEPREFIX` and the `GATEWAY_SHARED_SECRET` read out of your `.env`, so the
backend and gateway always agree on the shared secret — no separate
configuration needed.

### 6. Log in to MT5 through the gateway

Either from the app UI's **MT5 Account** panel, or from the CLI:

```bash
make mt5-login LOGIN=12345678 PASSWORD='your-password' SERVER=MetaQuotes-Demo
```

### 7. Verify

```bash
make doctor
```

Expect `"terminal_connected": true` and a non-null `"account"` in both
responses. At that point `/symbol_info`, `/market-data/symbol-info`, and the
candle stream all start working — no more 502/503s.

Browse the full, documented backend API at <http://localhost:8000/docs>
(Swagger UI) or <http://localhost:8000/redoc> — every endpoint lists its
request/response schema and the status codes it can return.

## Quality gates before calling anything "done"

```bash
make check   # lint + backend/gateway tests + frontend production build
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `symbol_info` → 502, `market-data/symbol-info` → 503 | Not logged in to MT5 yet — step 6 |
| `terminal_connected: false` after login worked before | Terminal closed/crashed, or lost broker connection — restart it (step 4), then repeat step 6 |
| `502 login rejected: [-6] Authorization failed` | Wrong login/password/**server name** — copy the server name exactly from the broker email |
| `401 bad or missing X-Gateway-Secret` | `TB_GATEWAY_SHARED_SECRET` in `.env` doesn't match what the gateway process has — re-run `make dev-gateway`/`make dev`, which now derive it from `.env` automatically |
| Order calls fail with retcode `10027` | Algo Trading disabled in the terminal — step 4.2 |
| `/candles` returns very few bars | Terminal hasn't downloaded that history — step 4.4 |
| Wine terminal loses connection when laptop sleeps | Disable suspend, or move to a Windows VPS (`gateway/README.md`, Option B) |

Full reference: `gateway/README.md` (gateway internals, VPS deployment) and
`README.md` (project overview).
