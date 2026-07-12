import stat

import pytest
from cryptography.fernet import Fernet

from src.ai.adapters.provider_secret_store import ProviderSecretStore


@pytest.fixture
def store(tmp_path) -> ProviderSecretStore:
    key = Fernet.generate_key()
    return ProviderSecretStore(tmp_path / "keys.enc", key_provider=lambda: key)


def test_get_returns_none_when_absent(store):
    assert store.get("openai") is None
    assert store.has("openai") is False


def test_set_then_get_roundtrips(store):
    store.set("openai", "sk-abc123")
    assert store.get("openai") == "sk-abc123"
    assert store.has("openai") is True


def test_set_does_not_clobber_other_providers(store):
    store.set("openai", "sk-abc123")
    store.set("gemini", "gm-xyz789")
    assert store.get("openai") == "sk-abc123"
    assert store.get("gemini") == "gm-xyz789"


def test_clear_removes_only_that_provider(store):
    store.set("openai", "sk-abc123")
    store.set("gemini", "gm-xyz789")
    store.clear("openai")
    assert store.get("openai") is None
    assert store.get("gemini") == "gm-xyz789"
    store.clear("openai")  # idempotent


def test_file_is_encrypted_and_owner_only(tmp_path, store):
    store.set("openai", "sk-abc123")
    path = tmp_path / "keys.enc"
    raw = path.read_bytes()
    assert b"sk-abc123" not in raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_wrong_key_treated_as_absent(tmp_path):
    ProviderSecretStore(tmp_path / "keys.enc", key_provider=lambda: Fernet.generate_key()).set(
        "openai", "sk-abc123"
    )
    reader = ProviderSecretStore(tmp_path / "keys.enc", key_provider=lambda: Fernet.generate_key())
    assert reader.get("openai") is None
