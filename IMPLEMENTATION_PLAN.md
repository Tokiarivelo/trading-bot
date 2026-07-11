# AI Trading Bot — Implementation Plan

> An MT5-connected, AI-assisted trading bot specialized in **XAUUSD, XAGUSD, BTCUSD**.
> Entries always on the **5-minute timeframe**, confirmed by higher timeframes.
> Strategies are generated from **PDF documents analyzed by an AI** (Claude or Ollama),
> and the bot **self-refines every 10 trades** based on AI analysis of its results.

---

## Table of Contents

1. [Vision & Core Features](#1-vision--core-features)
2. [Critical Platform Constraint (read first)](#2-critical-platform-constraint-read-first)
3. [Technology Stack](#3-technology-stack)
4. [Global Architecture](#4-global-architecture)
5. [Repository & Folder Structure](#5-repository--folder-structure)
6. [Module-by-Module Design](#6-module-by-module-design)
7. [Trading Logic Specification](#7-trading-logic-specification)
8. [AI Layer: PDF → Strategy, and Self-Refinement Loop](#8-ai-layer-pdf--strategy-and-self-refinement-loop)
9. [Claude Code Rules & Skills Plan](#9-claude-code-rules--skills-plan)
10. [Full Configuration Plan](#10-full-configuration-plan)
11. [Security](#11-security)
12. [Implementation Checklist (Phases)](#12-implementation-checklist-phases)
13. [Testing & Validation Strategy](#13-testing--validation-strategy)
14. [Risk Disclaimer](#14-risk-disclaimer)

---

## 1. Vision & Core Features

| # | Feature | Summary |
|---|---------|---------|
| F1 | MT5 data feed | Live ticks + OHLCV candles pulled from MetaTrader 5 |
| F2 | TradingView-like chart | Web UI rendering candles, indicators, and executed trades |
| F3 | Auto trading | Bot opens **and** closes positions automatically |
| F4 | PDF → Strategy | Import a PDF; AI (Claude API or local Ollama) extracts the method and generates bot strategy code |
| F5 | Self-refinement | Every **10 closed trades**, AI reviews the trades + market data at trade time, and refines the bot code/parameters if needed |
| F6 | Multi-timeframe | Entries always on **M5**; H1/H4/D1 consulted for confirmation |
| F7 | Trade markers | Every position (entry, SL, TP, exit) is drawn on the chart |
| F8 | Skills system | A "normal trading" skill + special skills for high-volatility news (NFP, CPI, FOMC…) |
| F9 | Symbols | XAUUSD (primary), XAGUSD, BTCUSD |
| F10 | Spread awareness | Broker spread measured live and factored into entry/SL/TP decisions |
| F11 | Account login | User enters MT5 login / password / server in the app UI |

---

## 2. Critical Platform Constraint (read first)

The official `MetaTrader5` Python package **only runs on Windows**, because it talks to a running MT5 desktop terminal. You are on Linux, so choose one of:

| Option | Description | Recommendation |
|--------|-------------|----------------|
| **A. Wine on Linux** | Run MT5 terminal + Windows Python under Wine; the bot's *MT5 connector service* runs inside Wine and exposes a local API (gRPC/HTTP) to the rest of the app running natively on Linux | ✅ Good for development on your machine |
| **B. Windows VPS** | MT5 + connector service on a cheap Windows VPS; rest of the app anywhere | ✅ Best for 24/7 live trading (low latency, no sleep) |
| **C. Third-party bridge** | Libraries like `mt5linux` (wraps option A) or broker REST APIs | ⚠️ Convenient but adds a dependency layer |

**Architectural decision that solves this cleanly:** isolate *everything* MT5-specific behind a small **MT5 Gateway service** with a network API. The rest of the system never imports `MetaTrader5` directly. This makes the platform problem a deployment detail, not a code problem, and lets you swap in a mock gateway for backtesting.

---

## 3. Technology Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language (backend/bot) | **Python 3.12+** | MT5 package, AI SDKs, pandas/numpy ecosystem |
| MT5 Gateway | `MetaTrader5` pip package + **FastAPI** (runs under Wine/Windows) | Only officially supported bridge |
| Backend API | **FastAPI** + WebSockets | Async, typed, easy WS streaming to chart |
| Frontend | **Next.js (App Router) + Tailwind CSS + TypeScript** | Production-grade React framework, utility-first styling, fast dev loop (Turbopack) |
| Charting | **`lightweight-charts`** (TradingView's own open-source library) | Literally the TradingView look & feel; supports markers, price lines, overlays |
| Database | **SQLite** (start) → PostgreSQL (later) | Trades, strategy versions, AI analyses, config |
| AI — cloud | **Claude API** (`claude-sonnet-5` for analysis/codegen, `claude-haiku-4-5` for cheap routine checks) | Best code generation & document analysis |
| AI — local | **Ollama** (e.g. `llama3.1`, `qwen2.5-coder`) | Free/offline fallback, user-selectable |
| PDF parsing | `pymupdf` (text + images) → AI | Robust extraction before AI sees it |
| Task scheduling | `APScheduler` | Trade loop ticks, news calendar refresh |
| News calendar | Forex Factory / investing.com scrape or `finnhub`/`fmp` API | Detect NFP/CPI/FOMC windows |
| Secrets | OS keyring (`keyring` pkg) + encrypted at rest (`cryptography`/Fernet) | MT5 credentials never in plaintext |
| Packaging | `docker-compose` for Linux services; gateway documented separately | Reproducible |
| Dev tooling | `uv` (backend), `pnpm` (frontend), root `Makefile` as command entry point | One command per task, always-latest deps policy |

---

## 4. Global Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (Next.js)                        │
│  Chart (lightweight-charts) · Trade markers · Bot controls ·       │
│  PDF upload · MT5 login form · Strategy & analysis viewer          │
└───────────────▲─────────────────────────────▲──────────────────────┘
                │ REST (commands/config)      │ WebSocket (candles, ticks,
                │                             │  positions, bot events)
┌───────────────┴─────────────────────────────┴──────────────────────┐
│                        BACKEND API (FastAPI)                       │
│   auth · config · strategy mgmt · chart data · bot control         │
└──────┬──────────────┬──────────────┬──────────────┬────────────────┘
       │              │              │              │
┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐ ┌─────▼──────────────┐
│ BOT ENGINE │ │  AI LAYER  │ │ NEWS SERVICE│ │  PERSISTENCE (DB)  │
│ strategy   │ │ pdf→method │ │ calendar    │ │ trades · versions  │
│ runner,    │ │ 10-trade   │ │ NFP/CPI     │ │ analyses · configs │
│ risk mgmt, │ │ review,    │ │ detection,  │ │                    │
│ skills     │ │ code refine│ │ skill switch│ │                    │
└──────┬─────┘ └────────────┘ └─────────────┘ └────────────────────┘
       │  gRPC/HTTP (network boundary — solves the Linux problem)
┌──────▼──────────────────────────────────────────────────────────────┐
│              MT5 GATEWAY (Windows / Wine / VPS)                     │
│  login · candles · ticks · spread · order send/modify/close        │
└──────────────────────────────▲──────────────────────────────────────┘
                               │
                        MetaTrader 5 Terminal → Broker
```

**Key principles**

- **Hexagonal (ports & adapters) per module**: every module exposes interfaces (`ports/`), with concrete implementations (`adapters/`) that can be swapped (live MT5 ↔ backtest simulator, Claude ↔ Ollama).
- **The bot never calls MT5 directly** — only through the `BrokerPort` interface.
- **Strategies are data + code artifacts**, versioned in the DB and on disk, so the AI refinement loop can diff/rollback.
- **Event-driven core**: the engine emits events (`CandleClosed`, `PositionOpened`, `PositionClosed`, `TenTradesCompleted`, `NewsWindowEntered`) that other modules subscribe to.

---

## 5. Repository & Folder Structure

Each top-level folder under `backend/src/` is a **self-contained module** with its own mini clean-architecture: `domain/` (pure logic, no I/O), `application/` (use cases), `ports/` (interfaces), `adapters/` (implementations), `api/` (FastAPI routes if the module has any).

```
trading-bot/
├── IMPLEMENTATION_PLAN.md            ← this file
├── README.md
├── docker-compose.yml
├── .env.example
├── CLAUDE.md                         ← Claude Code project rules (see §9)
├── .claude/
│   ├── settings.json                 ← permissions & hooks for Claude Code
│   └── skills/                       ← Claude Code skills (see §9)
│       ├── new-strategy/SKILL.md
│       ├── refine-bot/SKILL.md
│       ├── backtest/SKILL.md
│       ├── trade-review/SKILL.md
│       └── news-skill-gen/SKILL.md
│
├── gateway/                          ← MT5 GATEWAY (runs on Windows/Wine)
│   ├── pyproject.toml
│   ├── src/gateway/
│   │   ├── main.py                   ← FastAPI app
│   │   ├── mt5_client.py             ← the ONLY file importing MetaTrader5
│   │   ├── routes/
│   │   │   ├── auth.py               ← login/logout to MT5 account
│   │   │   ├── market_data.py        ← candles, ticks, spread, symbol info
│   │   │   └── trading.py            ← open/modify/close orders, positions
│   │   └── schemas.py                ← pydantic models shared over the wire
│   └── README.md                     ← Wine/VPS install instructions
│
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py                   ← FastAPI entrypoint, wires modules
│   │   ├── container.py              ← dependency injection / composition root
│   │   │
│   │   ├── shared/                   ← cross-cutting, no business logic
│   │   │   ├── events/               ← event bus (pub/sub), event definitions
│   │   │   ├── config/               ← settings loader (pydantic-settings)
│   │   │   ├── db/                   ← SQLAlchemy engine, migrations (alembic)
│   │   │   └── logging/
│   │   │
│   │   ├── market_data/              ← F1: candles, ticks, spread
│   │   │   ├── domain/               ← Candle, Tick, Timeframe, Spread models
│   │   │   ├── application/          ← stream_candles, get_history use cases
│   │   │   ├── ports/                ← MarketDataPort
│   │   │   ├── adapters/
│   │   │   │   ├── mt5_gateway.py    ← calls the gateway HTTP API
│   │   │   │   └── replay.py         ← historical replay for backtests
│   │   │   └── api/                  ← REST + WS endpoints for the chart
│   │   │       ├── routes.py         ← fully documented FastAPI routes (response_model, summary, description)
│   │   │       ├── schemas.py        ← pydantic wire models (mirrors domain/, never imported by domain/)
│   │   │       └── ws.py             ← Socket.IO candle stream
│   │   │
│   │   ├── broker/                   ← F3, F10, F11: order execution
│   │   │   ├── domain/               ← Order, Position, ExecutionResult, SpreadModel
│   │   │   ├── application/          ← open_position, close_position, apply_spread_rules
│   │   │   ├── ports/                ← BrokerPort, AccountPort
│   │   │   ├── adapters/
│   │   │   │   ├── mt5_gateway.py
│   │   │   │   └── paper.py          ← paper-trading simulator (same interface)
│   │   │   └── api/                  ← MT5 credentials login + order endpoints (routes.py, schemas.py)
│   │   │
│   │   ├── engine/                   ← F3, F6: the bot's beating heart
│   │   │   ├── domain/               ← Signal, TradePlan, RiskParams, EngineState
│   │   │   ├── application/
│   │   │   │   ├── trade_loop.py     ← on M5 candle close → evaluate → act
│   │   │   │   ├── mtf_confirm.py    ← higher-timeframe confirmation
│   │   │   │   ├── risk_manager.py   ← lot sizing, max drawdown, daily loss cap
│   │   │   │   └── position_manager.py ← trailing, BE moves, auto close
│   │   │   ├── ports/                ← StrategyPort, SkillSelectorPort
│   │   │   ├── adapters/
│   │   │   └── api/                  ← status + kill switch (routes.py, schemas.py)
│   │   │
│   │   ├── strategies/               ← F4: strategy artifacts (AI-generated)
│   │   │   ├── domain/               ← Strategy, StrategyVersion, Rule models
│   │   │   ├── application/          ← load, validate, activate, rollback
│   │   │   ├── registry.py           ← discovers strategy files
│   │   │   ├── sandbox.py            ← safe execution wrapper (restricted API surface)
│   │   │   └── generated/            ← AI-written strategy code lives HERE
│   │   │       ├── xauusd_breakout_v1.py
│   │   │       └── ...               ← every file versioned + hash-tracked in DB
│   │   │
│   │   ├── skills/                   ← F8: BOT trading skills (≠ Claude Code skills)
│   │   │   ├── domain/               ← Skill, ActivationCondition models
│   │   │   ├── application/          ← skill_selector (normal vs news vs symbol-specific)
│   │   │   ├── normal/               ← default trading behavior per symbol
│   │   │   │   ├── xauusd.yaml
│   │   │   │   ├── xagusd.yaml
│   │   │   │   └── btcusd.yaml
│   │   │   └── news/                 ← high-volatility playbooks
│   │   │       ├── nfp.yaml
│   │   │       ├── cpi.yaml
│   │   │       ├── fomc.yaml
│   │   │       └── generic_high_impact.yaml
│   │   │
│   │   ├── ai/                       ← F4, F5: all AI interaction
│   │   │   ├── domain/               ← AnalysisReport, RefinementProposal, StrategySpec
│   │   │   ├── application/
│   │   │   │   ├── pdf_to_strategy.py    ← PDF → StrategySpec → code generation
│   │   │   │   ├── ten_trade_review.py   ← triggered by TenTradesCompleted event
│   │   │   │   └── code_refiner.py       ← applies AI-proposed diffs w/ validation
│   │   │   ├── ports/                ← LLMPort (provider-agnostic)
│   │   │   ├── adapters/
│   │   │   │   ├── claude.py         ← Anthropic SDK
│   │   │   │   └── ollama.py         ← local models
│   │   │   ├── prompts/              ← versioned prompt templates (jinja2)
│   │   │   │   ├── extract_method_from_pdf.md
│   │   │   │   ├── generate_strategy_code.md
│   │   │   │   ├── review_ten_trades.md
│   │   │   │   └── refine_strategy_code.md
│   │   │   └── api/                  ← PDF upload endpoint, analysis viewer API
│   │   │
│   │   ├── news/                     ← F8: economic calendar
│   │   │   ├── domain/               ← NewsEvent, ImpactLevel, NewsWindow
│   │   │   ├── application/          ← fetch_calendar, detect_active_window
│   │   │   ├── ports/ · adapters/    ← forexfactory / finnhub adapters
│   │   │   └── api/
│   │   │
│   │   ├── journal/                  ← F5, F7: trade history & context capture
│   │   │   ├── domain/               ← TradeRecord (entry/exit/SL/TP/spread/skill/
│   │   │   │                            strategy-version/M5+HTF snapshots at entry)
│   │   │   ├── application/          ← record_trade, snapshot_market_context,
│   │   │   │                            get_last_n_trades
│   │   │   └── api/                  ← feeds chart markers & AI review (routes.py, schemas.py)
│   │   │
│   │   └── backtest/                 ← validation before anything goes live
│   │       ├── application/          ← run_backtest(strategy, period, symbol)
│   │       ├── adapters/             ← uses market_data.replay + broker.paper
│   │       └── reports/
│   │
│   └── tests/
│       ├── unit/                     ← mirrors src/ module structure
│       ├── integration/
│       └── fixtures/                 ← recorded candle data for deterministic tests
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── app/                      ← Next.js App Router: layout, pages, globals.css
│   │   ├── features/                 ← one folder per feature (mirrors backend)
│   │   │   ├── chart/                ← lightweight-charts wrapper, indicators,
│   │   │   │                            trade markers, timeframe switcher
│   │   │   ├── account/              ← MT5 login form, connection status
│   │   │   ├── bot-control/          ← start/stop, mode (live/paper), risk dial
│   │   │   ├── strategies/           ← PDF upload, strategy list, version diff view
│   │   │   ├── journal/              ← trade table, per-trade detail, stats
│   │   │   ├── ai-reports/           ← 10-trade analyses, refinement history
│   │   │   └── news/                 ← upcoming events, active news-window banner
│   │   ├── shared/                   ← api client, ws client, ui kit, hooks
│   │   └── types/                    ← generated from backend OpenAPI schema
│   └── ...
│
└── configs/                          ← runtime configuration (see §10)
    ├── app.yaml
    ├── symbols/
    │   ├── xauusd.yaml
    │   ├── xagusd.yaml
    │   └── btcusd.yaml
    ├── risk.yaml
    ├── ai.yaml
    └── news.yaml
```

---

## 6. Module-by-Module Design

### 6.1 `gateway/` — MT5 Gateway
- Thin, dumb, stable. **No business logic.** Endpoints: `POST /login`, `GET /candles`, `GET /tick`, `GET /symbol_info` (includes live spread), `POST /order`, `POST /close`, `GET /positions`, `WS /ticks`.
- Returns raw broker facts; all decisions happen in the backend.
- Health endpoint so the backend can detect gateway/terminal disconnects and pause trading.

### 6.2 `market_data/`
- Streams M5/H1/H4/D1 candles; caches recent history in memory; persists to DB for backtests and AI snapshots.
- Emits `CandleClosed(symbol, timeframe)` events — the engine's clock.

### 6.3 `broker/`
- `SpreadModel`: rolling average + live spread per symbol. Rules (from config): skip entry if `spread > max_spread_points`; widen SL by spread; require `expected_move ≥ k × spread` for a trade to be worth taking.
- `paper.py` adapter simulates fills **including spread** so paper results are honest.

### 6.4 `engine/`
- Runs one loop per symbol. On `CandleClosed(M5)`:
  1. Skill selector picks the active skill (normal vs news window).
  2. Active strategy evaluates → `Signal | None`.
  3. If signal: `mtf_confirm` checks higher TFs (per strategy spec).
  4. `risk_manager` sizes the lot (fixed % risk), checks caps (daily loss, max concurrent positions, max spread).
  5. `broker.open_position` → `journal.record_trade` (with full market context snapshot).
- `position_manager` runs on every tick/candle: SL-to-breakeven, trailing, time-based exit, hard close on skill rules (e.g., flat 2 min before NFP).

### 6.5 `strategies/`
- A strategy = one Python file implementing a fixed interface:
  ```python
  class Strategy(Protocol):
      spec: StrategySpec            # symbols, TFs used, params, HTF rules
      def evaluate(self, ctx: MarketContext) -> Signal | None: ...
  ```
- `sandbox.py`: generated code is imported in a restricted namespace — it receives only `MarketContext` (candles, indicators, spread) and returns a `Signal`. **It can never touch the broker, filesystem, or network.** The engine is the only component that executes trades.
- Every version is stored with: file hash, parent version, the AI analysis that produced it, and backtest results. Rollback = flip the active pointer.

### 6.6 `skills/` (bot skills — not Claude Code skills)
- Declarative YAML, interpreted by the engine:
  ```yaml
  # skills/news/nfp.yaml
  name: nfp
  activation:
    calendar_event: ["Non-Farm Payrolls"]
    window: { before_min: 30, after_min: 60 }
    symbols: [XAUUSD, XAGUSD]
  rules:
    pre_event:  { close_all: true, block_new_entries: true }
    post_event: { wait_candles_m5: 3, strategy_override: "news_breakout",
                  max_spread_points: 80, risk_multiplier: 0.5 }
  ```
- `skill_selector` resolves priority: **news skill > symbol normal skill > global default**.

### 6.7 `ai/`
- `LLMPort` with two adapters (Claude / Ollama), selectable in `configs/ai.yaml` per task — e.g., Claude for code generation, Ollama for routine trade commentary.
- **PDF pipeline**: `pymupdf` extracts text+images → prompt `extract_method_from_pdf` → structured `StrategySpec` (JSON: entry rules, exit rules, TFs, indicators, risk notes) → user reviews spec in UI → prompt `generate_strategy_code` → file in `strategies/generated/` → **mandatory backtest** → user activates.
- **10-trade review**: `journal` emits `TenTradesCompleted` → collect the 10 `TradeRecord`s incl. M5 + HTF candle snapshots around each trade → prompt `review_ten_trades` → `AnalysisReport` (what worked, what failed, hypothesis) → optionally `RefinementProposal` (param change or code diff) → **auto-backtest the proposal; apply only if it beats the current version; always keep the old version**. A config flag chooses `auto-apply` vs `ask-user`.

### 6.8 `journal/`
- The single source of truth for F5 and F7. Each `TradeRecord` stores everything the AI needs later: strategy version, skill active, spread at entry, slippage, and serialized candle windows (M5 ±50 candles, H1 ±20) at entry and exit.
- Chart markers API: `GET /journal/markers?symbol=&from=&to=` → frontend draws entry arrows, SL/TP lines, exit flags.

### 6.9 `frontend/features/chart/`
- `lightweight-charts` candlestick series + volume; timeframe switcher (M5 default, H1/H4/D1 view-only); indicator overlays defined by the active strategy spec; live updates over WebSocket; trade markers from journal; news-window shading on the time axis.

---

## 7. Trading Logic Specification

### 7.1 Entry flow (always M5)
```
M5 candle closes
 └─ gateway healthy? account connected? engine enabled?      → else skip
 └─ news window active?  → use news skill rules (may block entirely)
 └─ strategy.evaluate(M5 context) → Signal(dir, sl, tp, confidence)?
 └─ HTF confirmation (per strategy spec, e.g.):
     • H1 trend direction agrees (EMA200 slope / structure)
     • H4 not at major S/R against the trade
     → any veto ⇒ log "signal vetoed by HTF" and skip
 └─ spread check: live_spread ≤ symbol.max_spread_points
     AND (tp_distance ≥ min_rr × (sl_distance + spread))
 └─ risk manager: lot = account_balance × risk_pct / sl_distance_value
     caps: max_open_positions, daily_loss_limit, max_trades_per_day
 └─ send order (with spread-adjusted SL/TP) → journal snapshot
```

### 7.2 Exit flow
- Hard SL/TP always placed at the broker (never mental stops).
- `position_manager`: move SL to breakeven at +1R; optional trailing per strategy spec; time-stop (close after N candles without progress); force-flat before high-impact news if skill says so.

### 7.3 Spread handling (F10)
- Live spread from `symbol_info` on every evaluation.
- Buy fills at ask / sell at bid — the paper simulator must model this identically.
- All SL/TP distances validated against broker `stops_level`.
- Per-symbol `max_spread_points` (XAUUSD spreads blow up during news — this is the #1 real-world killer of gold scalpers).

---

## 8. AI Layer: PDF → Strategy, and Self-Refinement Loop

### 8.1 PDF → Strategy pipeline
```
PDF upload → text/image extraction → LLM: extract StrategySpec (JSON)
   → USER REVIEWS the spec in UI (edit/approve)
   → LLM: generate strategy code from approved spec
   → static validation (interface check, forbidden imports, type check)
   → automatic backtest on 6–12 months of data
   → results shown to user → user activates (paper first, then live)
```
Never skip the human review of the spec — PDFs are ambiguous and the spec is the contract.

### 8.2 10-trade refinement loop
```
TenTradesCompleted event
   → build review bundle: 10 TradeRecords + market snapshots + current code + spec
   → LLM: review_ten_trades → AnalysisReport
       (win rate, R distribution, common failure pattern, session/news correlation)
   → if LLM proposes refinement:
        param-only change  → update spec params, re-backtest
        code change        → LLM produces diff → sandbox validation → re-backtest
   → apply policy (configs/ai.yaml):
        mode: "suggest"  → show in UI, wait for approval   ← DEFAULT
        mode: "auto"     → apply only if backtest improves ≥ threshold
   → new StrategyVersion recorded; old version kept for rollback
```

**Guardrails (non-negotiable):**
- Refined code runs in the same sandbox with the same restricted API.
- A refinement can never change risk caps upward (risk %, daily loss limit are user-owned config, not strategy-owned).
- Max 1 auto-refinement per day per strategy; consecutive-loss circuit breaker (e.g., 5 losses → pause + notify) is engine-level and untouchable by AI.

---

## 9. Claude Code Rules & Skills Plan

This section is about using **Claude Code as your development copilot** on this repo (distinct from the bot's runtime skills in `backend/src/skills/`).

### 9.1 `CLAUDE.md` (project rules) — create at repo root
Contents to include:
```markdown
# Project rules
- Architecture: hexagonal per module. Business logic in domain/ and application/
  ONLY. Nothing outside gateway/src/gateway/mt5_client.py may import MetaTrader5.
- Strategies in backend/src/strategies/generated/ implement the Strategy protocol
  and are sandbox-safe: no imports beyond math/statistics/numpy/pandas, no I/O.
- Every broker-affecting change requires: unit tests + a paper-mode integration test.
- Risk caps (risk %, daily loss, max positions) live in configs/risk.yaml and are
  never modified by generated code or AI refinement logic.
- Run `pytest backend/tests` and `ruff check` before declaring any task done.
- Money-touching code paths: prefer explicit over clever; log every decision
  (signal, veto reason, spread, lot calc) at INFO.
- Frontend: Next.js (App Router) + Tailwind CSS; features mirror backend modules;
  charts via lightweight-charts only; always latest stable packages.
- API docs: every backend route has an explicit response_model (api/schemas.py),
  summary/description, and documented error responses — /docs and /openapi.json
  are always complete and accurate (see backend/src/main.py's OPENAPI_TAGS).
```

### 9.2 `.claude/skills/` (Claude Code dev skills)

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `new-strategy` | `/new-strategy <spec-file or description>` | Scaffolds a strategy file from a StrategySpec: correct interface, sandbox-safe imports, unit test stub, registers in registry, runs backtest |
| `refine-bot` | `/refine-bot <analysis-report-id>` | Reads an AI AnalysisReport from the DB, proposes/applies the code refinement with backtest before/after comparison |
| `backtest` | `/backtest <strategy> <symbol> <period>` | Runs the backtest CLI, renders the report, summarizes win rate / PF / max DD |
| `trade-review` | `/trade-review [n]` | Pulls last n trades from journal, correlates with market snapshots, writes a human-readable review |
| `news-skill-gen` | `/news-skill-gen <event-name>` | Generates a new YAML news skill (activation window, spread caps, risk multiplier) from a template + historical volatility of that event |
| `frontend-feature` | `/frontend-feature <description>` | Scaffolds/extends a frontend feature the project way: Next.js App Router + Tailwind, feature folder mirroring a backend module, shared api/ws clients, latest stable packages, `pnpm lint` + `pnpm build` validation |

Each `SKILL.md` should contain: purpose, exact steps, files it may touch, validation commands to run, and what it must never do (e.g., `refine-bot` must never edit `configs/risk.yaml`).

### 9.3 `.claude/settings.json` (hooks & permissions)
- Allow: `pytest`, `ruff`, `uv run`, backtest CLI.
- Hook (PostToolUse on Edit/Write under `strategies/generated/`): auto-run sandbox static validation.
- Hook (Stop): remind to run tests if `backend/src/` changed and pytest wasn't run.

---

## 10. Full Configuration Plan

### 10.1 File map
| File | Owns | Hot-reload? |
|------|------|-------------|
| `.env` | secrets refs, DB URL, gateway URL, Anthropic key ref | no |
| `configs/app.yaml` | mode (paper/live), enabled symbols, engine on/off, timezone | yes |
| `configs/symbols/<sym>.yaml` | per-symbol trading params | yes |
| `configs/risk.yaml` | user-owned risk caps (AI can never write) | yes |
| `configs/ai.yaml` | provider selection, models, refinement mode | yes |
| `configs/news.yaml` | calendar source, tracked events, default windows | yes |

### 10.2 Examples

```yaml
# configs/app.yaml
mode: paper            # paper | live   ← start EVERYTHING in paper
timezone: "Europe/Paris"
symbols: [XAUUSD, XAGUSD, BTCUSD]
engine:
  enabled: true
  entry_timeframe: M5
  confirmation_timeframes: [H1, H4]
```

```yaml
# configs/symbols/xauusd.yaml
symbol: XAUUSD
max_spread_points: 35        # skip entries above this
min_rr: 1.5                  # after spread adjustment
sessions:                    # only trade these (server time)
  - { start: "09:00", end: "12:00" }
  - { start: "14:30", end: "18:00" }
default_skill: normal/xauusd
```

```yaml
# configs/risk.yaml            ← USER-OWNED. AI/generated code: read-only.
risk_per_trade_pct: 0.5
daily_loss_limit_pct: 2.0
max_open_positions: 2
max_trades_per_day: 8
consecutive_loss_pause: 5     # circuit breaker
```

```yaml
# configs/ai.yaml
provider_per_task:
  pdf_extraction:  { provider: claude, model: claude-sonnet-5 }
  code_generation: { provider: claude, model: claude-sonnet-5 }
  ten_trade_review:{ provider: claude, model: claude-haiku-4-5 }
  # or provider: ollama, model: qwen2.5-coder:14b
refinement:
  mode: suggest               # suggest | auto
  auto_apply_min_improvement_pct: 10
  max_auto_refinements_per_day: 1
review_every_n_trades: 10
```

### 10.3 MT5 credentials (F11)
- Entered in the frontend login form → sent over HTTPS to backend → backend stores **encrypted** (Fernet key in OS keyring) → forwarded to gateway only at connect time → gateway holds them in memory only.
- Never written to logs, config files, or the DB in plaintext. `.env.example` documents this explicitly.

---

## 11. Security

- [ ] Credentials encrypted at rest (Fernet + OS keyring); memory-only in gateway.
- [ ] Backend↔gateway on localhost or private network / WireGuard if VPS; shared-secret auth header.
- [ ] Generated strategy code: import whitelist, AST scan for forbidden nodes (`exec`, `open`, `socket`, dunder access), resource/time limits on `evaluate()`.
- [ ] Frontend auth (even single-user: a local password) since it can start a live bot.
- [ ] Kill switch: one endpoint + UI button → close all positions, disable engine.

---

## 12. Implementation Checklist (Phases)

### Phase 0 — Foundations (repo & tooling)
- [x] Init git repo, `README.md`, this plan
- [x] `CLAUDE.md` + `.claude/settings.json` + skill stubs (§9)
- [x] Backend scaffold: FastAPI app, module skeletons, DI container, event bus
- [x] Frontend scaffold: Next.js (App Router) + Tailwind CSS + TS, layout, api/ws client
- [x] SQLite + alembic migrations
- [x] `docker-compose.yml` (backend, frontend, db) + gateway install doc (Wine or VPS — decide now, see §2)
- [x] CI: ruff + pytest on every commit

### Phase 1 — MT5 Gateway & market data
- [x] Gateway: login, candles, tick, symbol_info (spread), health
- [x] Backend `market_data` module + `mt5_gateway` adapter
- [x] Candle streaming M5/H1/H4/D1 for the 3 symbols; `CandleClosed` events
- [x] Historical download job → DB (streaming persists closed bars; `POST /market-data/backfill` for bulk)
- [x] MT5 login flow end-to-end from the UI (F11), encrypted storage

### Phase 2 — Chart (F2, F7 partial)
- [x] lightweight-charts candlestick + volume, dark theme
- [x] WebSocket live updates; timeframe switcher
- [x] Symbol switcher (XAUUSD/XAGUSD/BTCUSD)
- [x] Spread indicator on chart header

### Phase 3 — Broker & paper trading
- [x] Gateway trading endpoints: open/modify/close/positions
- [x] `broker` module: domain models, spread rules, `mt5_gateway` + `paper` adapters
- [x] `journal` module: TradeRecord + market context snapshots
- [x] Trade markers on chart (F7 complete)

### Phase 4 — Engine & first strategy (manual, not AI yet)
- [x] Trade loop on M5 close; HTF confirmation; risk manager; position manager
- [x] One hand-written baseline strategy (e.g., simple breakout) to prove the pipe
- [x] Skill selector + `normal/` skills for the 3 symbols
- [x] Circuit breakers (daily loss, consecutive losses) + kill switch
- [ ] **Run 2+ weeks in paper mode** — do not proceed to live before this

### Phase 5 — Backtesting
- [x] Replay adapter + paper broker → deterministic backtest runner
- [x] Spread-aware fill simulation
- [x] Report: win rate, profit factor, max drawdown, R distribution, equity curve
- [x] Backtest CLI
- [ ] UI report page (backend + CLI shipped this pass; frontend viewer is a follow-up)

### Phase 6 — AI: PDF → Strategy (F4)
- [ ] `LLMPort` + Claude adapter + Ollama adapter; provider config
- [ ] PDF upload + extraction + `extract_method_from_pdf` prompt → StrategySpec
- [ ] Spec review/edit UI
- [ ] `generate_strategy_code` prompt → sandbox validation → auto-backtest
- [ ] Strategy versioning + activation flow (paper first)

### Phase 7 — AI: 10-trade refinement loop (F5)
- [ ] `TenTradesCompleted` event from journal
- [ ] Review bundle builder (trades + snapshots + code + spec)
- [ ] `review_ten_trades` prompt → AnalysisReport → UI page
- [ ] `refine_strategy_code` → diff → sandbox → backtest comparison
- [ ] Suggest/auto apply policy + rollback UI

### Phase 8 — News skills (F8)
- [ ] `news` module: calendar fetch, impact classification, window detection
- [ ] News skills YAML (NFP, CPI, FOMC, generic) + skill override in engine
- [ ] Pre-news flatten / entry-block; post-news strategy override
- [ ] News windows shaded on chart; upcoming-events panel

### Phase 9 — Hardening & go-live
- [ ] Security checklist (§11) fully done
- [ ] Reconnect/resume logic (gateway drop, terminal restart, backend restart with open positions)
- [ ] Alerting (Telegram/email) for fills, circuit breakers, refinements
- [ ] 30 days profitable+stable paper trading → smallest live size → scale slowly

---

## 13. Testing & Validation Strategy

| Layer | How |
|-------|-----|
| Domain logic | Pure unit tests (no I/O), fixture candles |
| Spread & risk math | Property-based tests (hypothesis) — lot sizing, RR, spread adjust |
| Strategy sandbox | Adversarial tests: generated code trying forbidden imports/IO must be rejected |
| Engine | Integration tests over recorded candle fixtures with paper broker |
| Gateway | Contract tests against a mock; manual smoke test against demo account |
| AI prompts | Golden-file tests: same input bundle → spec/report shape validation (schema, not exact text) |
| End-to-end | Demo MT5 account, paper→demo-live pipeline, one full news event rehearsal |

---

## 14. Risk Disclaimer

Automated trading of leveraged instruments (especially XAUUSD) can lose money **fast**. This plan deliberately bakes in: paper-first everywhere, user-owned risk caps the AI cannot touch, circuit breakers, mandatory backtests before activation, and human approval as the default for AI refinements. Keep those. Use a **demo account** until Phase 9's criteria are met, and never risk money you cannot afford to lose.
