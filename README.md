# AI Trading Bot — XAUUSD / XAGUSD / BTCUSD

An MT5-connected, AI-assisted trading bot. Entries on M5 with higher-timeframe
confirmation, TradingView-style chart, strategies generated from PDF documents
by an AI (Claude or Ollama), and automatic self-refinement every 10 trades.

**Full design & roadmap:** see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## Repository layout

| Path | What |
|------|------|
| `backend/` | FastAPI backend — engine, strategies, AI layer, journal (hexagonal modules) |
| `frontend/` | React + TypeScript UI — chart, bot controls, PDF upload, reports |
| `gateway/` | MT5 Gateway service — the **only** code touching MetaTrader5 (runs on Windows/Wine/VPS, see `gateway/README.md`) |
| `configs/` | Runtime configuration (symbols, risk caps, AI providers, news) |
| `.claude/` | Claude Code dev skills and settings |

## Quick start (development)

```bash
# Backend (Python 3.12 via uv)
cd backend
uv sync
uv run uvicorn src.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev            # http://localhost:5173

# Gateway — requires MT5 terminal; see gateway/README.md (Wine or Windows VPS)
```

## Checks

```bash
cd backend
uv run ruff check src tests
uv run pytest
```

## Safety model (do not weaken)

- Everything starts in **paper mode** (`configs/app.yaml: mode: paper`).
- Risk caps live in `configs/risk.yaml` and are user-owned — AI/generated code
  never writes them.
- AI-generated strategies run sandboxed: no I/O, no network, no broker access.
- Engine-level circuit breakers: daily loss limit, consecutive-loss pause, kill switch.
