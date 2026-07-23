"""Encrypted credential storage (F11).

Credentials are Fernet-encrypted on disk; the encryption key lives in the OS
keyring, never next to the ciphertext. Plaintext exists only in memory on its
way to the gateway. Nothing here is ever logged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.broker.domain.account import Mt5Credentials
from src.shared.security.keyring_store import (
    KEYRING_KEY_NAME,
    KEYRING_SERVICE,
    keyring_key_provider,
)

__all__ = [
    "KEYRING_KEY_NAME",
    "KEYRING_SERVICE",
    "FernetCredentialStore",
    "credentials_path_for",
    "keyring_key_provider",
]

_CREDENTIALS_DIR = Path("data/credentials")


def credentials_path_for(account_id: str) -> Path:
    """Per-account credential file — `data/credentials/{account_id}.enc`.

    One file per account (not one keyed file) so a corrupt write only loses
    that account's credentials, not every account's (MULTI_ACCOUNT_PLAN.md
    Phase 2). The OS-keyring Fernet key stays global across accounts.
    """
    return _CREDENTIALS_DIR / f"{account_id}.enc"


class FernetCredentialStore:
    def __init__(self, path: Path, key_provider: Callable[[], bytes] = keyring_key_provider):
        self._path = path
        self._key_provider = key_provider

    def save(self, credentials: Mt5Credentials) -> None:
        payload = json.dumps(
            {
                "login": credentials.login,
                "password": credentials.password,
                "server": credentials.server,
            }
        ).encode()
        token = Fernet(self._key_provider()).encrypt(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(token)
        self._path.chmod(0o600)

    def load(self) -> Mt5Credentials | None:
        if not self._path.exists():
            return None
        try:
            payload = Fernet(self._key_provider()).decrypt(self._path.read_bytes())
        except InvalidToken:
            # Key rotated or file corrupted — treat as absent, user logs in again.
            return None
        data = json.loads(payload)
        return Mt5Credentials(login=data["login"], password=data["password"], server=data["server"])

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
