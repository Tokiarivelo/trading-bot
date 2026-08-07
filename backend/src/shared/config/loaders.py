"""Config -> domain dataclass loaders shared by the app composition root
(`container.py`) and the backtest composition root (`backtest/application/run_backtest.py`).
"""

from __future__ import annotations

from pathlib import Path

from src.ai.domain.models import RefinementConfig
from src.ai.ports.llm import ProviderSpec
from src.alerting.domain.models import AlertEventFlags, AlertingConfig, SilenceConfig
from src.broker.domain.account import AccountConfig
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.engine.domain.models import RiskCaps
from src.engine.domain.regime import RegimeConfig
from src.engine.domain.volatility import VolatilityConfig
from src.news.domain.models import ImpactLevel, NewsConfig, TrackedEvent
from src.shared.config.maintenance import MaintenanceConfig
from src.shared.config.settings import load_yaml_config


def load_symbol_trading_config(symbol: str, configs_dir: Path) -> SymbolTradingConfig:
    data = load_yaml_config(f"symbols/{symbol.lower()}", configs_dir)
    return SymbolTradingConfig(
        symbol=data["symbol"],
        max_spread_points=data["max_spread_points"],
        min_rr=data["min_rr"],
        contract_size=data["contract_size"],
        point=data["point"],
        digits=data["digits"],
        stops_level=data["stops_level"],
        volume_min=data["volume_min"],
        volume_max=data["volume_max"],
        volume_step=data["volume_step"],
    )


def load_symbol_trading_config_if_exists(
    symbol: str, configs_dir: Path
) -> SymbolTradingConfig | None:
    """Same as `load_symbol_trading_config`, but `None` instead of raising
    when `configs/symbols/<symbol>.yaml` doesn't exist — for callers with a
    dynamic source of truth for a symbol's facts (e.g. `SpreadGate`'s
    no-config fallback, `run_backtest`'s DB-backed `SymbolSpec`) where a
    hand-authored file is optional, not required."""
    try:
        return load_symbol_trading_config(symbol, configs_dir)
    except FileNotFoundError:
        return None


def load_risk_caps(configs_dir: Path) -> RiskCaps:
    data = load_yaml_config("risk", configs_dir)
    return RiskCaps(
        risk_per_trade_pct=data["risk_per_trade_pct"],
        daily_loss_limit_pct=data["daily_loss_limit_pct"],
        max_open_positions=data["max_open_positions"],
        max_trades_per_day_enabled=data.get("max_trades_per_day_enabled", False),
        consecutive_loss_pause=data["consecutive_loss_pause"],
        consecutive_loss_pause_enabled=data.get("consecutive_loss_pause_enabled", True),
        min_lot_fallback_enabled=data.get("min_lot_fallback_enabled", False),
        max_risk_per_trade_pct=data.get("max_risk_per_trade_pct"),
    )


def load_volatility_config(configs_dir: Path) -> VolatilityConfig:
    data = load_yaml_config("volatility", configs_dir)
    return VolatilityConfig(
        atr_period=data.get("atr_period", 14),
        regime_lookback_bars=data.get("regime_lookback_bars", 100),
        low_percentile=data.get("low_percentile", 20.0),
        high_percentile=data.get("high_percentile", 70.0),
        extreme_percentile=data.get("extreme_percentile", 90.0),
        sl_multiplier_low=data.get("sl_multiplier_low", 0.85),
        sl_multiplier_normal=data.get("sl_multiplier_normal", 1.0),
        sl_multiplier_high=data.get("sl_multiplier_high", 1.3),
        tp_multiplier_low=data.get("tp_multiplier_low", 0.85),
        tp_multiplier_normal=data.get("tp_multiplier_normal", 1.0),
        tp_multiplier_high=data.get("tp_multiplier_high", 1.3),
        extreme_close_if_losing=data.get("extreme_close_if_losing", True),
        extreme_profit_lock_r_mult=data.get("extreme_profit_lock_r_mult", 0.5),
        chandelier_atr_mult=data.get("chandelier_atr_mult", 2.0),
        chandelier_min_profit_r=data.get("chandelier_min_profit_r", 1.0),
    )


def load_regime_config(configs_dir: Path) -> RegimeConfig:
    data = load_yaml_config("regime", configs_dir)
    return RegimeConfig(
        adx_period=data.get("adx_period", 14),
        adx_trend_threshold=data.get("adx_trend_threshold", 20.0),
        session_overlap_start_hour=data.get("session_overlap_start_hour", 12),
        session_overlap_end_hour=data.get("session_overlap_end_hour", 16),
        session_london_start_hour=data.get("session_london_start_hour", 7),
        session_london_end_hour=data.get("session_london_end_hour", 16),
        session_new_york_start_hour=data.get("session_new_york_start_hour", 16),
        session_new_york_end_hour=data.get("session_new_york_end_hour", 21),
        session_asian_start_hour=data.get("session_asian_start_hour", 22),
        session_asian_end_hour=data.get("session_asian_end_hour", 7),
    )


def load_llm_provider_config(configs_dir: Path) -> dict[str, ProviderSpec]:
    data = load_yaml_config("ai", configs_dir).get("provider_per_task", {})
    return {
        task: ProviderSpec(provider=entry["provider"], model=entry["model"])
        for task, entry in data.items()
    }


def load_refinement_config(configs_dir: Path) -> RefinementConfig:
    data = load_yaml_config("ai", configs_dir).get("refinement", {})
    return RefinementConfig(
        mode=data.get("mode", "suggest"),
        auto_apply_min_improvement_pct=data.get("auto_apply_min_improvement_pct", 10.0),
        max_auto_refinements_per_day=data.get("max_auto_refinements_per_day", 1),
    )


def load_news_config(configs_dir: Path) -> NewsConfig:
    data = load_yaml_config("news", configs_dir)
    calendar = data.get("calendar", {})
    default_window = data.get("default_window", {})
    return NewsConfig(
        calendar_source=calendar.get("source", "forexfactory"),
        refresh_minutes=calendar.get("refresh_minutes", 60),
        tracked_events=tuple(
            TrackedEvent(
                name=entry["name"], impact=ImpactLevel(entry["impact"]), skill=entry["skill"]
            )
            for entry in data.get("tracked_events", [])
        ),
        default_before_min=default_window.get("before_min", 30),
        default_after_min=default_window.get("after_min", 60),
    )


def load_accounts_config(configs_dir: Path) -> list[AccountConfig]:
    data = load_yaml_config("accounts", configs_dir)
    return [
        AccountConfig(
            id=entry["id"],
            label=entry["label"],
            gateway_url=entry["gateway_url"],
            gateway_shared_secret_env=entry["gateway_shared_secret_env"],
            mode=entry["mode"],
            enabled=entry.get("enabled", True),
            risk_override_file=entry.get("risk_override_file"),
            mt5_terminal_subpath=entry.get("mt5_terminal_subpath"),
        )
        for entry in data.get("accounts", [])
    ]


def load_alerting_config(configs_dir: Path) -> AlertingConfig:
    data = load_yaml_config("alerting", configs_dir)
    telegram = data.get("telegram", {})
    email = data.get("email", {})
    events = data.get("events", {})
    silence = data.get("silence", {})
    return AlertingConfig(
        telegram_enabled=telegram.get("enabled", False),
        email_enabled=email.get("enabled", False),
        smtp_host=email.get("smtp_host", ""),
        smtp_port=email.get("smtp_port", 587),
        from_address=email.get("from_address", ""),
        to_address=email.get("to_address", ""),
        events=AlertEventFlags(
            fills=events.get("fills", True),
            circuit_breaker=events.get("circuit_breaker", True),
            refinements=events.get("refinements", True),
            gateway_disconnect=events.get("gateway_disconnect", True),
            bot_silence=events.get("bot_silence", True),
        ),
        silence=SilenceConfig(
            poll_interval_s=silence.get("poll_interval_minutes", 15.0) * 60.0,
            lookback_days=silence.get("lookback_days", 30),
            multiplier=silence.get("multiplier", 5.0),
            min_signals=silence.get("min_signals", 5),
        ),
    )


def load_maintenance_config(configs_dir: Path) -> MaintenanceConfig:
    data = load_yaml_config("maintenance", configs_dir)
    activity_log = data.get("activity_log", {})
    wal_checkpoint = data.get("wal_checkpoint", {})
    return MaintenanceConfig(
        activity_log_retention_days=activity_log.get("retention_days", 90),
        activity_log_check_interval_hours=activity_log.get("check_interval_hours", 6.0),
        wal_checkpoint_enabled=wal_checkpoint.get("enabled", True),
        wal_checkpoint_interval_minutes=wal_checkpoint.get("interval_minutes", 15.0),
    )
