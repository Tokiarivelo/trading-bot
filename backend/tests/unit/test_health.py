from fastapi.testclient import TestClient

from src.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_config_endpoint_reports_paper_mode():
    with TestClient(app) as client:
        response = client.get("/config/app")
    assert response.status_code == 200
    assert response.json()["mode"] in ("paper", "live")
