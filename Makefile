# ══════════════════════════════════════════════════════════════════════════
#  AI Trading Bot — developer Makefile
#
#  Run `make` or `make help` to list every target.
#
#  Tooling (see CLAUDE.md — binding):
#    backend/gateway : Python 3.12 managed with uv   (https://docs.astral.sh/uv)
#    frontend        : Next.js managed with pnpm     (pinned in package.json)
#
#  The MT5 gateway needs a Windows environment (Wine or a Windows VPS) with a
#  running MT5 terminal.  `make dev` starts it alongside backend + frontend
#  under Wine.  See gateway/README.md for full setup & VPS deployment.
# ══════════════════════════════════════════════════════════════════════════

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Locations & tools
BACKEND_DIR  := backend
FRONTEND_DIR := frontend
GATEWAY_DIR  := gateway
UV           := uv
PNPM         := pnpm

# Ports (override like: make dev-backend BACKEND_PORT=8001)
BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 3000
GATEWAY_PORT  ?= 8787

# Wine prefix dedicated to the MT5 terminal + Windows Python (see gateway/README.md)
WINEPREFIX ?= $(HOME)/.mt5

# Shared secret the backend and gateway must agree on. Pulled from .env's
# TB_GATEWAY_SHARED_SECRET so `make dev-gateway` / `make dev` always match
# what the backend sends — no more silent 401s from a forgotten env var.
GATEWAY_SHARED_SECRET := $(shell [ -f .env ] && grep -E '^TB_GATEWAY_SHARED_SECRET=' .env | cut -d= -f2-)

# ════════════════════════════════ HELP ══════════════════════════════════════

.PHONY: help
help: ## Show this help
	@echo ""
	@echo "AI Trading Bot — make targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} \
		/^# ───/ {gsub(/^# ─+ ?| ?─+$$/, ""); printf "\n\033[1m%s\033[0m\n", $$0} \
		/^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""

# ─── Setup ───────────────────────────────────────────────────────────────────

.PHONY: setup
setup: setup-backend setup-frontend setup-gateway env ## Full dev setup: backend + frontend + gateway deps + .env

.PHONY: setup-backend
setup-backend: ## Install backend deps into backend/.venv (uv sync)
	cd $(BACKEND_DIR) && $(UV) sync

.PHONY: setup-frontend
setup-frontend: ## Install frontend deps (pnpm install)
	cd $(FRONTEND_DIR) && $(PNPM) install

.PHONY: setup-gateway
setup-gateway: ## Install gateway deps (real runtime is Windows/Wine — see gateway/README.md)
	cd $(GATEWAY_DIR) && $(UV) sync

.PHONY: env
env: ## Create .env from .env.example if it doesn't exist yet (auto-generates the gateway secret)
	@if [ -f .env ]; then \
		echo ".env already exists — leaving it untouched"; \
	else \
		cp .env.example .env; \
		SECRET=$$(openssl rand -hex 32); \
		sed -i.bak "s#^TB_GATEWAY_SHARED_SECRET=.*#TB_GATEWAY_SHARED_SECRET=$$SECRET#" .env && rm -f .env.bak; \
		echo "created .env from .env.example with a random TB_GATEWAY_SHARED_SECRET"; \
		echo "MT5 login/password/server are NOT put in .env — enter them via the UI's"; \
		echo "MT5 Account panel, or 'make mt5-login LOGIN=... PASSWORD=... SERVER=...'"; \
	fi

.PHONY: setup-wine
setup-wine: ## One-time host setup for the Wine-hosted MT5 gateway (Ubuntu/Debian; Linux dev only)
	@echo "Installing Wine + winetricks (sudo required)..."
	sudo dpkg --add-architecture i386
	sudo apt update && sudo apt install --install-recommends -y wine64 wine32 winetricks
	@echo "Creating Wine prefix at $(WINEPREFIX)..."
	WINEPREFIX=$(WINEPREFIX) winetricks -q corefonts
	@echo ""
	@echo "Host setup done. Remaining manual steps (see gateway/README.md):"
	@echo "  1. WINEPREFIX=$(WINEPREFIX) wine mt5setup.exe                 # install the MT5 terminal"
	@echo "  2. WINEPREFIX=$(WINEPREFIX) wine python-3.12.x-amd64.exe /quiet InstallAllUsers=0 PrependPath=1"
	@echo "  3. WINEPREFIX=$(WINEPREFIX) wine python -m pip install MetaTrader5 fastapi uvicorn pydantic"
	@echo "  4. Start the terminal, log in to your MT5 demo account, enable Algo Trading,"
	@echo "     and add XAUUSD/XAGUSD/BTCUSD to Market Watch — see 'Terminal configuration'"
	@echo "     in gateway/README.md."

# ─── Dev servers ─────────────────────────────────────────────────────────────

.PHONY: dev
dev: ## Run backend + frontend + gateway together (Ctrl-C stops all)
	@trap 'kill 0' EXIT; \
	( cd $(BACKEND_DIR) && $(UV) run uvicorn src.main:socket_app --reload --port $(BACKEND_PORT) ) & \
	( cd $(FRONTEND_DIR) && $(PNPM) dev --port $(FRONTEND_PORT) ) & \
	( cd $(GATEWAY_DIR) && WINEPREFIX=$(WINEPREFIX) GATEWAY_SHARED_SECRET=$(GATEWAY_SHARED_SECRET) GATEWAY_PORT=$(GATEWAY_PORT) wine $(WINE_PYTHON) run_gateway.py ) & \
	wait

.PHONY: dev-backend
dev-backend: ## Run the FastAPI backend with auto-reload (default http://localhost:8000)
	cd $(BACKEND_DIR) && $(UV) run uvicorn src.main:socket_app --reload --port $(BACKEND_PORT)

.PHONY: dev-frontend
dev-frontend: ## Run the Next.js dev server (default http://localhost:3000)
	cd $(FRONTEND_DIR) && $(PNPM) dev --port $(FRONTEND_PORT)

# Wine Python used by the gateway (override: make dev-gateway WINE_PYTHON=/path/to/python.exe)
WINE_PYTHON ?= $(HOME)/.wine/drive_c/Python312/python.exe

.PHONY: dev-gateway
dev-gateway: ## Run the MT5 gateway under Wine (http://localhost:8787) — needs the terminal already running (see setup-wine)
	cd $(GATEWAY_DIR) && WINEPREFIX=$(WINEPREFIX) GATEWAY_SHARED_SECRET=$(GATEWAY_SHARED_SECRET) GATEWAY_PORT=$(GATEWAY_PORT) wine $(WINE_PYTHON) run_gateway.py

.PHONY: mt5-terminal
mt5-terminal: ## Launch the MT5 terminal in the dedicated Wine prefix (leave it running)
	WINEPREFIX=$(WINEPREFIX) wine "$(WINEPREFIX)/drive_c/Program Files/MetaTrader 5/terminal64.exe" &

.PHONY: mt5-login
mt5-login: ## Log in to MT5 through the gateway from the CLI: make mt5-login LOGIN=123 PASSWORD=x SERVER=Broker-Demo
	@test -n "$(LOGIN)" && test -n "$(PASSWORD)" && test -n "$(SERVER)" || \
		{ echo 'usage: make mt5-login LOGIN=12345678 PASSWORD=*** SERVER=MetaQuotes-Demo'; exit 1; }
	curl -sf -X POST http://127.0.0.1:$(GATEWAY_PORT)/login \
		-H "X-Gateway-Secret: $(GATEWAY_SHARED_SECRET)" \
		-H "Content-Type: application/json" \
		-d '{"login": $(LOGIN), "password": "$(PASSWORD)", "server": "$(SERVER)"}' \
		| python3 -m json.tool

.PHONY: backtest
backtest: ## Run a strategy backtest: make backtest strategy=breakout_v1 symbol=XAUUSD period=2025-01:2025-06
	@test -n "$(strategy)" && test -n "$(symbol)" && test -n "$(period)" || \
		{ echo 'usage: make backtest strategy=breakout_v1 symbol=XAUUSD period=2025-01:2025-06'; exit 1; }
	cd backend && uv run python -m src.backtest.cli $(strategy) $(symbol) $(period)

# ─── Quality gates (run `make check` before declaring any task done) ─────────

.PHONY: check
check: lint test build-frontend ## EVERYTHING: lint + tests + frontend production build

.PHONY: lint
lint: lint-backend lint-gateway lint-frontend ## Lint backend + gateway (ruff) + frontend (oxlint)

.PHONY: lint-backend
lint-backend: ## ruff check backend src + tests
	cd $(BACKEND_DIR) && $(UV) run ruff check src tests

.PHONY: lint-gateway
lint-gateway: ## ruff check gateway src + tests
	cd $(GATEWAY_DIR) && $(UV) run ruff check src tests

.PHONY: lint-frontend
lint-frontend: ## oxlint the frontend
	cd $(FRONTEND_DIR) && $(PNPM) lint

.PHONY: format
format: format-backend format-gateway ## Auto-format backend + gateway (ruff format + safe fixes)

.PHONY: format-backend
format-backend: ## Auto-format backend (ruff format + safe fixes)
	cd $(BACKEND_DIR) && $(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

.PHONY: format-gateway
format-gateway: ## Auto-format gateway (ruff format + safe fixes)
	cd $(GATEWAY_DIR) && $(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

.PHONY: test
test: test-backend test-gateway ## All tests (backend + gateway; frontend has no test suite yet)

.PHONY: test-backend
test-backend: ## Full backend pytest suite
	cd $(BACKEND_DIR) && $(UV) run pytest

.PHONY: test-gateway
test-gateway: ## Gateway contract tests (stubbed MetaTrader5 — runs on Linux)
	cd $(GATEWAY_DIR) && $(UV) run pytest

.PHONY: test-unit
test-unit: ## Backend unit tests only
	cd $(BACKEND_DIR) && $(UV) run pytest tests/unit

.PHONY: test-integration
test-integration: ## Backend integration tests only (paper-mode broker paths)
	cd $(BACKEND_DIR) && $(UV) run pytest tests/integration

.PHONY: build-frontend
build-frontend: ## Next.js production build (includes TypeScript type-checking)
	cd $(FRONTEND_DIR) && $(PNPM) build

# ─── Database (SQLite via alembic) ───────────────────────────────────────────

.PHONY: db-upgrade
db-upgrade: ## Apply all pending migrations (alembic upgrade head)
	cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

.PHONY: db-downgrade
db-downgrade: ## Roll back the last migration (alembic downgrade -1)
	cd $(BACKEND_DIR) && $(UV) run alembic downgrade -1

.PHONY: db-revision
db-revision: ## New autogenerated migration: make db-revision m="add journal table"
	@test -n "$(m)" || { echo 'usage: make db-revision m="describe the change"'; exit 1; }
	cd $(BACKEND_DIR) && $(UV) run alembic revision --autogenerate -m "$(m)"

.PHONY: db-history
db-history: ## Show migration history and current revision
	cd $(BACKEND_DIR) && $(UV) run alembic history && $(UV) run alembic current

# ─── Docker (Linux services only — backend + frontend; gateway excluded) ─────

.PHONY: docker-up
docker-up: ## Start the dev stack in the background (docker compose up -d)
	docker compose up -d --build

.PHONY: docker-down
docker-down: ## Stop the dev stack
	docker compose down

.PHONY: docker-logs
docker-logs: ## Tail logs from all services
	docker compose logs -f --tail=100

.PHONY: docker-ps
docker-ps: ## Show service status
	docker compose ps

# ─── Dependency maintenance (rule: always latest stable — see CLAUDE.md) ─────

.PHONY: outdated
outdated: ## Show outdated deps in backend (uv), gateway (uv) and frontend (pnpm)
	cd $(BACKEND_DIR) && $(UV) tree --outdated --depth 1 || true
	cd $(GATEWAY_DIR) && $(UV) tree --outdated --depth 1 || true
	cd $(FRONTEND_DIR) && $(PNPM) outdated || true

.PHONY: update-deps
update-deps: ## Upgrade everything to latest stable (then run `make check`!)
	cd $(BACKEND_DIR) && $(UV) lock --upgrade && $(UV) sync
	cd $(GATEWAY_DIR) && $(UV) lock --upgrade && $(UV) sync
	cd $(FRONTEND_DIR) && $(PNPM) update --latest
	@echo "──> now run 'make check' and review lockfile diffs before committing"

# ─── Utilities ────────────────────────────────────────────────────────────────

.PHONY: openapi
openapi: ## Dump the backend OpenAPI schema (backend must be running)
	curl -sf http://localhost:$(BACKEND_PORT)/openapi.json | python3 -m json.tool

.PHONY: doctor
doctor: ## Diagnose the full stack: gateway up? terminal connected? backend can reach it?
	@echo "── gateway :$(GATEWAY_PORT)/health ──"; \
	if curl -sf http://127.0.0.1:$(GATEWAY_PORT)/health; then echo; else \
		echo; echo "gateway is DOWN — run 'make dev-gateway' (Wine + terminal must be up first)"; exit 0; \
	fi; \
	echo; echo "── backend :$(BACKEND_PORT)/account/status ──"; \
	if curl -sf http://127.0.0.1:$(BACKEND_PORT)/account/status; then echo; else \
		echo; echo "backend is DOWN — run 'make dev-backend'"; exit 0; \
	fi; \
	echo; echo "If terminal_connected is false: MT5 isn't logged in yet — that's why"; \
	echo "/symbol_info etc. return 502/503. Fix with the UI's MT5 Account panel, or:"; \
	echo "  make mt5-login LOGIN=12345678 PASSWORD=*** SERVER=MetaQuotes-Demo"

.PHONY: clean
clean: ## Remove caches and build artifacts (keeps .venv and node_modules)
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/out
	find $(BACKEND_DIR) $(GATEWAY_DIR) -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-all
clean-all: clean ## clean + remove .venv and node_modules (full reinstall needed after)
	rm -rf $(BACKEND_DIR)/.venv $(GATEWAY_DIR)/.venv $(FRONTEND_DIR)/node_modules
