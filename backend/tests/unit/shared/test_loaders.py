from src.broker.domain.account import AccountConfig
from src.engine.domain.volatility import VolatilityConfig
from src.shared.config.loaders import (
    load_accounts_config,
    load_maintenance_config,
    load_volatility_config,
)
from src.shared.config.maintenance import MaintenanceConfig
from src.shared.config.settings import CONFIGS_DIR


def test_load_accounts_config_returns_typed_accounts():
    accounts = load_accounts_config(CONFIGS_DIR)
    assert len(accounts) >= 1
    for account in accounts:
        assert isinstance(account, AccountConfig)
        assert account.id
        assert account.gateway_url.startswith("http")
        assert account.mode in ("paper", "live")


def test_load_accounts_config_defaults_enabled_and_risk_override():
    accounts = load_accounts_config(CONFIGS_DIR)
    default_account = next(a for a in accounts if a.id == "default")
    assert default_account.enabled is True
    assert default_account.risk_override_file is None


def test_load_maintenance_config_returns_typed_config():
    config = load_maintenance_config(CONFIGS_DIR)
    assert isinstance(config, MaintenanceConfig)
    assert config.activity_log_retention_days > 0
    assert config.activity_log_check_interval_hours > 0
    assert config.wal_checkpoint_interval_minutes > 0


def test_load_volatility_config_returns_typed_config_with_expected_defaults():
    # high_percentile/extreme_percentile/sl_multiplier_high/tp_multiplier_high
    # reflect Phase D's tuned values (2026-08 grid search), not the Phase A
    # originals — see the rationale comments in configs/volatility.yaml.
    config = load_volatility_config(CONFIGS_DIR)
    assert isinstance(config, VolatilityConfig)
    assert config.atr_period == 14
    assert config.regime_lookback_bars == 100
    assert config.low_percentile == 20
    assert config.high_percentile == 60
    assert config.extreme_percentile == 98
    assert config.sl_multiplier_low == 0.85
    assert config.sl_multiplier_normal == 1.0
    assert config.sl_multiplier_high == 1.45
    assert config.tp_multiplier_low == 0.85
    assert config.tp_multiplier_normal == 1.0
    assert config.tp_multiplier_high == 1.45
    assert config.extreme_close_if_losing is True
    assert config.extreme_profit_lock_r_mult == 0.5
    assert config.chandelier_atr_mult == 2.0
    assert config.chandelier_min_profit_r == 1.0
