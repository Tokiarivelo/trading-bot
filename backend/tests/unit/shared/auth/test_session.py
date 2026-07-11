import time

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.shared.auth.dependencies import require_session
from src.shared.auth.session import SessionTokenIssuer


def _issuer() -> SessionTokenIssuer:
    key = Fernet.generate_key()
    return SessionTokenIssuer(key_provider=lambda: key)


def test_issue_then_verify_succeeds():
    issuer = _issuer()
    token = issuer.issue()
    assert issuer.verify(token, max_age_seconds=3600)


def test_verify_rejects_garbage_token():
    issuer = _issuer()
    assert not issuer.verify("not-a-real-token", max_age_seconds=3600)
    assert not issuer.verify("", max_age_seconds=3600)


def test_verify_rejects_expired_token():
    issuer = _issuer()
    token = issuer.issue()
    time.sleep(2.2)
    assert not issuer.verify(token, max_age_seconds=1)


def test_verify_rejects_token_signed_with_a_different_key():
    issuer_a = _issuer()
    issuer_b = _issuer()
    token = issuer_a.issue()
    assert not issuer_b.verify(token, max_age_seconds=3600)


def _protected_app(app_password: str, session_issuer: SessionTokenIssuer | None = None) -> FastAPI:
    app = FastAPI()

    class FakeSettings:
        pass

    settings = FakeSettings()
    settings.app_password = app_password

    class FakeContainer:
        pass

    container = FakeContainer()
    container.settings = settings
    container.session_issuer = session_issuer or _issuer()
    app.state.container = container

    @app.get("/protected", dependencies=[Depends(require_session)])
    def protected():
        return {"ok": True}

    return app


def test_require_session_is_a_noop_when_no_app_password_configured():
    client = TestClient(_protected_app(app_password=""))
    assert client.get("/protected").status_code == 200


def test_require_session_rejects_missing_or_bad_token_when_password_set():
    issuer = _issuer()
    app = _protected_app(app_password="secret", session_issuer=issuer)
    client = TestClient(app)

    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer garbage"}).status_code == 401

    token = issuer.issue()
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
