# Project rules — AI Trading Bot

Read `IMPLEMENTATION_PLAN.md` for the full design. These rules are binding.

## Architecture
- Hexagonal per module: business logic lives in `domain/` and `application/` ONLY.
  `ports/` hold interfaces (Protocols), `adapters/` hold implementations, `api/`
  holds FastAPI routes. Domain code never imports adapters, FastAPI, or SQLAlchemy.
- Nothing outside `gateway/src/gateway/mt5_client.py` may import `MetaTrader5`.
  The backend talks to MT5 only through the gateway HTTP API via `ports` adapters.
- Modules communicate through the event bus (`backend/src/shared/events/`) or
  explicit application-service calls wired in `backend/src/container.py` — never
  by importing another module's internals.

## Strategies & AI safety (non-negotiable)
- Strategy files in `backend/src/strategies/generated/` implement the `Strategy`
  protocol and must be sandbox-safe: imports limited to `math`, `statistics`,
  `numpy`, `pandas`; no I/O, no network, no broker access, no dunder tricks.
- Risk caps (`configs/risk.yaml`: risk %, daily loss limit, max positions) are
  user-owned. Generated code, AI refinement logic, and dev skills must NEVER
  modify this file or route around its limits.
- Engine circuit breakers (consecutive-loss pause, kill switch) are engine-level
  code; AI refinements must not touch `backend/src/engine/`.

## Quality bar
- Every broker-affecting change requires unit tests plus a paper-mode
  integration test.
- Money-touching code paths: explicit over clever. Log every decision (signal,
  veto reason, spread, lot calculation) at INFO.
- Before declaring any task done, run from `backend/`:
  `uv run ruff check src tests` and `uv run pytest`.

## Frontend
- Feature folders under `frontend/src/features/` mirror backend modules.
- All charting via `lightweight-charts` only.
- API types come from the backend OpenAPI schema — don't hand-write duplicates.

## Conventions
- Python 3.12, `uv` for dependency management, `ruff` for lint+format.
- Config is YAML in `configs/`, loaded through `shared/config`; secrets only via
  `.env` / OS keyring — never hardcoded, never logged.
