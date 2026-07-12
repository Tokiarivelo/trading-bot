"""OS-keyring-backed Fernet key retrieval, shared by every at-rest secret
store in the backend (broker MT5 credentials, AI provider API keys). The
encryption key itself lives in the OS keyring, never next to the ciphertext
on disk.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

KEYRING_SERVICE = "trading-bot"
KEYRING_KEY_NAME = "credential-encryption-key"


def keyring_key_provider() -> bytes:
    """Fetch (or create once) the encryption key from the OS keyring."""
    import keyring

    key = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
    if key is None:
        key = Fernet.generate_key().decode()
        keyring.set_password(KEYRING_SERVICE, KEYRING_KEY_NAME, key)
    return key.encode()
