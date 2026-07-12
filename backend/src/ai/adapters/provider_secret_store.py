"""Encrypted API-key storage for the AI settings page (AI_PROVIDER_SETTINGS_PLAN.md
§6.5 extension) — same Fernet-over-OS-keyring pattern as
`broker/adapters/credential_store.py`'s `FernetCredentialStore`, but holds an
arbitrary `{provider_id: api_key}` map instead of one fixed credential shape,
since the settings page manages a key per provider rather than a single
broker login. A key saved here takes precedence over that provider's `.env`
fallback (wired in `container.py`); nothing here is ever logged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.shared.security.keyring_store import keyring_key_provider


class ProviderSecretStore:
    def __init__(self, path: Path, key_provider: Callable[[], bytes] = keyring_key_provider):
        self._path = path
        self._key_provider = key_provider

    def get(self, provider: str) -> str | None:
        return self._load().get(provider)

    def has(self, provider: str) -> bool:
        return bool(self.get(provider))

    def set(self, provider: str, api_key: str) -> None:
        data = self._load()
        data[provider] = api_key
        self._save(data)

    def clear(self, provider: str) -> None:
        data = self._load()
        if data.pop(provider, None) is not None:
            self._save(data)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            payload = Fernet(self._key_provider()).decrypt(self._path.read_bytes())
        except InvalidToken:
            # Key rotated or file corrupted — treat as empty, operator re-enters keys.
            return {}
        return json.loads(payload)

    def _save(self, data: dict[str, str]) -> None:
        payload = json.dumps(data).encode()
        token = Fernet(self._key_provider()).encrypt(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(token)
        self._path.chmod(0o600)
