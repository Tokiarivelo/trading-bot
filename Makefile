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
#  running MT5 terminal — it is NOT part of `make dev` / docker compose.
#  See gateway/README.md.
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
setup: setup-backend setup-frontend env ## Full dev setup: backend + frontend deps + .env

.PHONY: setup-backend
setup-backend: ## Install backend deps into backend/.venv (uv sync)
	cd $(BACKEND_DIR) && $(UV) sync

.PHONY: setup-frontend
setup-frontend: ## Install frontend deps (pnpm install)
	cd $(FRONTEND_DIR) && $(PNPM) install

.PHONY: setup-gateway
setup-gateway: ## Install gateway deps for local editing (real runtime is Windows/Wine — see gateway/README.md)
	cd $(GATEWAY_DIR) && $(UV) sync

.PHONY: env
env: ## Create .env from .env.example if it doesn't exist yet
	@if [ -f .env ]; then \
		echo ".env already exists — leaving it untouched"; \
	else \
		cp .env.example .env && echo "created .env from .env.example — fill in your secrets"; \
	fi

# ─── Dev servers ─────────────────────────────────────────────────────────────

.PHONY: dev
dev: ## Run backend + frontend together (Ctrl-C stops both)
	@trap 'kill 0' EXIT; \
	( cd $(BACKEND_DIR) && $(UV) run uvicorn src.main:app --reload --port $(BACKEND_PORT) ) & \
	( cd $(FRONTEND_DIR) && $(PNPM) dev --port $(FRONTEND_PORT) ) & \
	wait

.PHONY: dev-backend
dev-backend: ## Run the FastAPI backend with auto-reload (default http://localhost:8000)
	cd $(BACKEND_DIR) && $(UV) run uvicorn src.main:app --reload --port $(BACKEND_PORT)

.PHONY: dev-frontend
dev-frontend: ## Run the Next.js dev server (default http://localhost:3000)
	cd $(FRONTEND_DIR) && $(PNPM) dev --port $(FRONTEND_PORT)

# Wine Python used by the gateway (override: make dev-gateway WINE_PYTHON=/path/to/python.exe)
WINE_PYTHON ?= $(HOME)/.wine/drive_c/Python312/python.exe

.PHONY: dev-gateway
dev-gateway: ## Run the MT5 gateway under Wine (http://localhost:8787)
	cd $(GATEWAY_DIR) && wine $(WINE_PYTHON) run_gateway.py

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
format: ## Auto-format backend (ruff format + safe fixes); oxlint has no formatter
	cd $(BACKEND_DIR) && $(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

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
outdated: ## Show outdated deps in backend (uv) and frontend (pnpm)
	cd $(BACKEND_DIR) && $(UV) tree --outdated --depth 1 || true
	cd $(FRONTEND_DIR) && $(PNPM) outdated || true

.PHONY: update-deps
update-deps: ## Upgrade everything to latest stable (then run `make check`!)
	cd $(BACKEND_DIR) && $(UV) lock --upgrade && $(UV) sync
	cd $(FRONTEND_DIR) && $(PNPM) update --latest
	@echo "──> now run 'make check' and review lockfile diffs before committing"

# ─── Utilities ────────────────────────────────────────────────────────────────

.PHONY: openapi
openapi: ## Dump the backend OpenAPI schema (backend must be running)
	curl -sf http://localhost:$(BACKEND_PORT)/openapi.json | python3 -m json.tool

.PHONY: clean
clean: ## Remove caches and build artifacts (keeps .venv and node_modules)
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/out
	find $(BACKEND_DIR) $(GATEWAY_DIR) -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-all
clean-all: clean ## clean + remove .venv and node_modules (full reinstall needed after)
	rm -rf $(BACKEND_DIR)/.venv $(GATEWAY_DIR)/.venv $(FRONTEND_DIR)/node_modules
