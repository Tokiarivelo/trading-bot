from src.broker.domain.account import AccountConfig
from src.shared.config.loaders import load_accounts_config
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
