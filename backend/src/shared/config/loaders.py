"""Config -> domain dataclass loaders shared by the app composition root
(`container.py`) and the backtest composition root (`backtest/application/run_backtest.py`).
"""

from __future__ import annotations

from pathlib import Path

from src.ai.domain.models import RefinementConfig
from src.ai.ports.llm import ProviderSpec
from src.alerting.domain.models import AlertEventFlags, AlertingConfig
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.engine.domain.models import RiskCaps
from src.news.domain.models import ImpactLevel, NewsConfig, TrackedEvent
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
        max_trades_per_day=data["max_trades_per_day"],
        consecutive_loss_pause=data["consecutive_loss_pause"],
        min_lot_fallback_enabled=data.get("min_lot_fallback_enabled", False),
        max_risk_per_trade_pct=data.get("max_risk_per_trade_pct"),
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


def load_alerting_config(configs_dir: Path) -> AlertingConfig:
    data = load_yaml_config("alerting", configs_dir)
    telegram = data.get("telegram", {})
    email = data.get("email", {})
    events = data.get("events", {})
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
        ),
    )
