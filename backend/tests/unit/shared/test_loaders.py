from src.broker.domain.account import AccountConfig
from src.shared.config.loaders import load_accounts_config, load_maintenance_config
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
