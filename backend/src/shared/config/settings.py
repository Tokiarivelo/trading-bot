"""Application settings.

Secrets and deployment values come from the environment / `.env`.
Trading behavior (symbols, risk, AI providers, news) comes from YAML files in
`configs/`, loaded via `load_yaml_config`. Risk caps in `configs/risk.yaml`
are user-owned: nothing in this codebase may write that file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIGS_DIR = REPO_ROOT / "configs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_prefix="TB_", extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./data/trading.db"
    gateway_url: str = "http://127.0.0.1:8787"
    gateway_shared_secret: str = ""
    anthropic_api_key: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    configs_dir: Path = CONFIGS_DIR


def load_yaml_config(name: str, configs_dir: Path = CONFIGS_DIR) -> dict[str, Any]:
    """Load `configs/<name>.yaml` (e.g. "app", "risk", "symbols/xauusd")."""
    path = configs_dir / f"{name}.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping, got {type(data).__name__}")
    return data
