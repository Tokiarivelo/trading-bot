"""Phase 5 of MULTI_ACCOUNT_PLAN.md: `build_container()` wires one isolated
`AccountRuntime` per enabled `configs/accounts.yaml` entry — its own event
bus, strategy registry, and credential path — while `Container`'s
backward-compat properties keep resolving to the primary (first enabled)
account, so every existing single-account route/test is unaffected.

No real gateway connection is ever made here — `httpx.AsyncClient`/
`GatewayMarketData`/etc. are all constructed lazily and never called.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.container import build_container
from src.shared.config.settings import CONFIGS_DIR, Settings
from src.shared.db.base import Base
from src.shared.events.definitions import CandleClosed


@pytest.fixture
def two_account_settings(tmp_path: Path) -> Settings:
    """Copies the real `configs/` tree (symbols/skills/risk/ai/news/etc. all
    need to be valid YAML for `build_container` to load) into a temp dir,
    then overwrites `accounts.yaml` with two enabled accounts."""
    configs_dir = tmp_path / "configs"
    shutil.copytree(CONFIGS_DIR, configs_dir)
    (configs_dir / "accounts.yaml").write_text(
        "accounts:\n"
        "  - id: acct-a\n"
        "    label: Account A\n"
        "    gateway_url: http://127.0.0.1:19001\n"
        "    gateway_shared_secret_env: TB_GATEWAY_SHARED_SECRET\n"
        "    mode: paper\n"
        "    enabled: true\n"
        "  - id: acct-b\n"
        "    label: Account B\n"
        "    gateway_url: http://127.0.0.1:19002\n"
        "    gateway_shared_secret_env: TB_GATEWAY_SHARED_SECRET\n"
        "    mode: paper\n"
        "    enabled: true\n"
    )
    db_path = tmp_path / "test.db"
    Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))
    return Settings(
        configs_dir=configs_dir,
        database_url=f"sqlite+aiosqlite:///{db_path}",
    )


async def test_build_container_wires_one_runtime_per_enabled_account(two_account_settings):
    container = build_container(two_account_settings)
    try:
        assert set(container.accounts) == {"acct-a", "acct-b"}
        assert container.primary_account_id == "acct-a"

        acct_a = container.accounts["acct-a"]
        acct_b = container.accounts["acct-b"]
        assert acct_a.event_bus is not acct_b.event_bus
        assert acct_a.strategy_registry is not acct_b.strategy_registry
        assert acct_a.gateway_client is not acct_b.gateway_client
        assert str(acct_a.gateway_client.base_url) == "http://127.0.0.1:19001"
        assert str(acct_b.gateway_client.base_url) == "http://127.0.0.1:19002"

        # Backward-compat properties resolve to the primary account only.
        assert container.trade_journal is acct_a.trade_journal
        assert container.trade_engine is acct_a.trade_engine
        assert container.strategy_registry is acct_a.strategy_registry
    finally:
        await container.aclose()


async def test_account_event_buses_are_isolated(two_account_settings):
    """Publishing on one account's bus must never reach another account's
    trade engine — the whole point of a per-account `EventBus`."""
    container = build_container(two_account_settings)
    try:
        acct_a = container.accounts["acct-a"]
        acct_b = container.accounts["acct-b"]

        calls_b: list[str] = []
        original = acct_b.trade_engine.on_candle_closed

        async def spy(event):
            calls_b.append(event.symbol)
            await original(event)

        acct_b.trade_engine.on_candle_closed = spy  # type: ignore[method-assign]

        await acct_a.event_bus.publish(CandleClosed(symbol="XAUUSD", timeframe="M5"))

        assert calls_b == []
    finally:
        await container.aclose()


async def test_strategy_activation_does_not_cross_accounts(two_account_settings):
    """MULTI_ACCOUNT_PLAN.md Phase 4's own repository tests assert two
    accounts can have different active versions of the same strategy name —
    this checks the in-memory `StrategyRegistry` side of that promise:
    registering a new instance for a name on one account's registry must
    leave the other account's registry untouched."""
    container = build_container(two_account_settings)
    try:
        acct_a = container.accounts["acct-a"]
        acct_b = container.accounts["acct-b"]

        baseline_b = acct_b.strategy_registry.get("breakout_v1")
        assert acct_a.strategy_registry.get("breakout_v1") is not None
        assert baseline_b is not None

        sentinel = object()
        acct_a.strategy_registry.register("breakout_v1", sentinel)

        assert acct_a.strategy_registry.get("breakout_v1") is sentinel
        assert acct_b.strategy_registry.get("breakout_v1") is baseline_b
    finally:
        await container.aclose()
