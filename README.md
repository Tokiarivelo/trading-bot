> 🇫🇷 Version française : [README.fr.md](README.fr.md)

# AI Trading Bot — XAUUSD / XAGUSD / BTCUSD

An MT5-connected, AI-assisted trading bot. Entries on M5 with higher-timeframe
confirmation, TradingView-style chart, strategies generated from PDF documents
by an AI (Claude or Ollama), and automatic self-refinement every 10 trades.

**Full design & roadmap:** see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## Repository layout

| Path | What |
|------|------|
| `backend/` | FastAPI backend — engine, strategies, AI layer, journal (hexagonal modules) |
| `frontend/` | Next.js + Tailwind CSS + TypeScript UI — chart, bot controls, PDF upload, reports |
| `gateway/` | MT5 Gateway service — the **only** code touching MetaTrader5 (runs on Windows/Wine/VPS, see `gateway/README.md`) |
| `configs/` | Runtime configuration (symbols, risk caps, AI providers, news) |
| `Makefile` | Canonical dev commands — setup, dev servers, checks, DB, docker (`make help`) |
| `.claude/` | Claude Code dev skills and settings |

## Quick start (development)

Everything goes through the root `Makefile` — run `make help` for the full list.

```bash
make setup             # backend (uv sync) + frontend (pnpm install) + .env
make dev               # backend on :8000 + frontend on :3000, Ctrl-C stops both

# or individually:
make dev-backend       # FastAPI with auto-reload — http://localhost:8000
make dev-frontend      # Next.js dev server — http://localhost:3000

# Gateway — requires an MT5 terminal; see gateway/README.md for full setup:
#   Wine on Linux for development, Windows VPS recommended for 24/7 live trading
```

Under the hood: backend is Python 3.12 via `uv`, frontend is Next.js via
`pnpm` (version pinned in `frontend/package.json`).

## Checks

```bash
make check             # lint (ruff + oxlint) + backend tests + frontend build
```

Individual gates: `make lint`, `make test`, `make build-frontend` — see `make help`.

## Safety model (do not weaken)

- Everything starts in **paper mode** (`configs/app.yaml: mode: paper`).
- Risk caps live in `configs/risk.yaml` and are user-owned — AI/generated code
  never writes them.
- AI-generated strategies run sandboxed: no I/O, no network, no broker access.
- Engine-level circuit breakers: daily loss limit, consecutive-loss pause, kill switch.
