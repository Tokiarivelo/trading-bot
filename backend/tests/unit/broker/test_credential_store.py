import stat

import pytest
from cryptography.fernet import Fernet

from src.broker.adapters.credential_store import FernetCredentialStore
from src.broker.domain.account import Mt5Credentials

CREDS = Mt5Credentials(login=123456, password="s3cret-pw", server="Demo-Server")


@pytest.fixture
def store(tmp_path) -> FernetCredentialStore:
    key = Fernet.generate_key()
    return FernetCredentialStore(tmp_path / "credentials.enc", key_provider=lambda: key)


def test_roundtrip(store):
    store.save(CREDS)
    assert store.load() == CREDS


def test_load_returns_none_when_absent(store):
    assert store.load() is None


def test_clear_removes_file(store):
    store.save(CREDS)
    store.clear()
    assert store.load() is None
    store.clear()  # idempotent


def test_file_is_encrypted_and_owner_only(tmp_path, store):
    store.save(CREDS)
    path = tmp_path / "credentials.enc"
    raw = path.read_bytes()
    assert b"s3cret-pw" not in raw
    assert b"123456" not in raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_wrong_key_treated_as_absent(tmp_path):
    FernetCredentialStore(
        tmp_path / "credentials.enc", key_provider=lambda: Fernet.generate_key()
    ).save(CREDS)
    reader = FernetCredentialStore(
        tmp_path / "credentials.enc", key_provider=lambda: Fernet.generate_key()
    )
    assert reader.load() is None


def test_password_never_in_repr():
    assert "s3cret-pw" not in repr(CREDS)
