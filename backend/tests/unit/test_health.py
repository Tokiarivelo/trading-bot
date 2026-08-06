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


def test_metrics_endpoint_is_unauthenticated_and_scrapes_prometheus_text():
    # OBSERVABILITY_PLAN.md Phase 5 — unauthenticated like /health (a
    # Prometheus scraper has no session token), and served as Prometheus
    # text exposition format, not JSON.
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP tradingbot_engine_loop_duration_seconds" in response.text
    assert "# HELP tradingbot_open_positions" in response.text


def test_openapi_schema_documents_metrics_without_a_spurious_json_content_type():
    # Regression test: FastAPI derives its *default* 200 content type from
    # the route's `response_class` (JSONResponse unless overridden),
    # independent of the function's `-> Response` return annotation or
    # `response_model=None` — leaving `response_class` unset on `/metrics`
    # silently merged an empty-schema `application/json` entry alongside the
    # real `text/plain` one in the generated OpenAPI doc.
    schema = app.openapi()
    content = schema["paths"]["/metrics"]["get"]["responses"]["200"]["content"]
    assert "application/json" not in content
    assert any(media_type.startswith("text/plain") for media_type in content)
