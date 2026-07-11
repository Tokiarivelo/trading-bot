"""Session tokens for the single-user app password (§11).

Reuses `cryptography.fernet.Fernet` — already a dependency, and already used
identically by `broker/adapters/credential_store.py` — instead of hand-rolling
a signed-token format. The signing key lives in the OS keyring, generated
once on first use, mirroring `credential_store.keyring_key_provider`.
Fernet's built-in `ttl` on `decrypt()` gives expiry for free.
"""

from __future__ import annotations

from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken

KEYRING_SERVICE = "trading-bot"
KEYRING_KEY_NAME = "session-signing-key"

_SESSION_PAYLOAD = b"tb-session"


def keyring_session_key_provider() -> bytes:
    """Fetch (or create once) the session-signing key from the OS keyring."""
    import keyring

    key = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
    if key is None:
        key = Fernet.generate_key().decode()
        keyring.set_password(KEYRING_SERVICE, KEYRING_KEY_NAME, key)
    return key.encode()


class SessionTokenIssuer:
    def __init__(self, key_provider: Callable[[], bytes] = keyring_session_key_provider) -> None:
        self._key_provider = key_provider

    def issue(self) -> str:
        return Fernet(self._key_provider()).encrypt(_SESSION_PAYLOAD).decode()

    def verify(self, token: str, max_age_seconds: int) -> bool:
        if not token:
            return False
        try:
            payload = Fernet(self._key_provider()).decrypt(token.encode(), ttl=max_age_seconds)
        except (InvalidToken, ValueError):
            return False
        return payload == _SESSION_PAYLOAD
