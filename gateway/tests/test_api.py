from __future__ import annotations


def _login(api) -> None:
    response = api.post(
        "/login", json={"login": 123456, "password": "pw", "server": "Demo-Server"}
    )
    assert response.status_code == 200


def test_health_reports_disconnected_before_login(api):
    body = api.get("/health").json()
    assert body == {"status": "ok", "terminal_connected": False, "account": None}


def test_login_returns_account_info(api):
    response = api.post(
        "/login", json={"login": 123456, "password": "pw", "server": "Demo-Server"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["login"] == 123456
    assert body["balance"] == 10_000.0
    assert body["currency"] == "USD"


def test_rejected_login_maps_to_502_with_reason(api, fake_mt5):
    fake_mt5.reject_login = True
    response = api.post(
        "/login", json={"login": 123456, "password": "bad", "server": "Demo-Server"}
    )
    assert response.status_code == 502
    assert "Authorization failed" in response.json()["detail"]


def test_health_reports_account_after_login(api):
    _login(api)
    body = api.get("/health").json()
    assert body["terminal_connected"] is True
    assert body["account"]["login"] == 123456


def test_candles_shape(api):
    _login(api)
    response = api.get("/candles", params={"symbol": "XAUUSD", "timeframe": "M5", "count": 3})
    assert response.status_code == 200
    candles = response.json()
    assert len(candles) == 3
    first = candles[0]
    assert set(first) == {"time", "open", "high", "low", "close", "tick_volume", "spread"}
    assert first["time"] % 300 == 0


def test_candles_rejects_unknown_timeframe(api):
    _login(api)
    response = api.get("/candles", params={"symbol": "XAUUSD", "timeframe": "M1"})
    assert response.status_code == 422


def test_market_data_requires_login(api):
    response = api.get("/tick", params={"symbol": "XAUUSD"})
    assert response.status_code == 502
    assert "not logged in" in response.json()["detail"]


def test_symbol_info_includes_live_spread(api):
    _login(api)
    body = api.get("/symbol_info", params={"symbol": "XAUUSD"}).json()
    assert body["spread_points"] == 25
    assert body["stops_level"] == 10
    assert body["point"] == 0.01


def test_shared_secret_enforced_when_configured(api, monkeypatch):
    monkeypatch.setenv("GATEWAY_SHARED_SECRET", "s3cret")
    _login_denied = api.post(
        "/login", json={"login": 123456, "password": "pw", "server": "Demo-Server"}
    )
    assert _login_denied.status_code == 401

    ok = api.post(
        "/login",
        json={"login": 123456, "password": "pw", "server": "Demo-Server"},
        headers={"X-Gateway-Secret": "s3cret"},
    )
    assert ok.status_code == 200
    # /health stays open for probes
    assert api.get("/health").status_code == 200


def test_logout_shuts_terminal_down(api, fake_mt5):
    _login(api)
    assert api.post("/logout").status_code == 200
    assert fake_mt5.shutdown_called is True
    assert api.get("/health").json()["terminal_connected"] is False
