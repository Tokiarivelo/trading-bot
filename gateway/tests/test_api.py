from __future__ import annotations


def _login(api) -> None:
    response = api.post("/login", json={"login": 123456, "password": "pw", "server": "Demo-Server"})
    assert response.status_code == 200


def test_health_reports_disconnected_before_login(api):
    body = api.get("/health").json()
    assert body == {"status": "ok", "terminal_connected": False, "account": None}


def test_login_returns_account_info(api):
    response = api.post("/login", json={"login": 123456, "password": "pw", "server": "Demo-Server"})
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


def test_candles_accepts_m1_timeframe(api):
    _login(api)
    response = api.get("/candles", params={"symbol": "XAUUSD", "timeframe": "M1", "count": 3})
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_candles_rejects_unknown_timeframe(api):
    _login(api)
    response = api.get("/candles", params={"symbol": "XAUUSD", "timeframe": "M2"})
    assert response.status_code == 422


def test_candles_before_returns_older_bars_strictly_before_cutoff(api):
    _login(api)
    cutoff = 1_752_000_000
    response = api.get(
        "/candles",
        params={"symbol": "XAUUSD", "timeframe": "M5", "count": 3, "before": cutoff},
    )
    assert response.status_code == 200
    candles = response.json()
    assert len(candles) == 3
    times = [c["time"] for c in candles]
    assert times == sorted(times)
    assert all(t < cutoff for t in times)


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


def test_symbols_lists_broker_catalog(api):
    _login(api)
    body = api.get("/symbols").json()
    assert {s["name"] for s in body["items"]} == {"XAUUSD", "XAGUSD", "EURUSD", "BTCUSD"}
    assert body["total"] == 4
    eurusd = next(s for s in body["items"] if s["name"] == "EURUSD")
    assert eurusd["path"] == "Forex\\Majors"
    assert eurusd["visible"] is False


def test_symbols_search_filters_by_name_or_description(api):
    _login(api)
    body = api.get("/symbols", params={"search": "gold"}).json()
    assert [s["name"] for s in body["items"]] == ["XAUUSD"]
    assert body["total"] == 1


def test_symbols_respects_limit(api):
    _login(api)
    body = api.get("/symbols", params={"limit": 2}).json()
    assert len(body["items"]) == 2
    assert body["total"] == 4  # total reflects the full (filtered) catalog, not just this page


def test_symbols_pages_with_offset(api):
    _login(api)
    first = api.get("/symbols", params={"limit": 2, "offset": 0}).json()
    second = api.get("/symbols", params={"limit": 2, "offset": 2}).json()
    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    first_names = {s["name"] for s in first["items"]}
    second_names = {s["name"] for s in second["items"]}
    assert first_names.isdisjoint(second_names)
    assert first_names | second_names == {"XAUUSD", "XAGUSD", "EURUSD", "BTCUSD"}


def test_symbols_requires_login(api):
    response = api.get("/symbols")
    assert response.status_code == 502
    assert "not logged in" in response.json()["detail"]


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


def test_order_opens_a_position(api):
    _login(api)
    response = api.post(
        "/order",
        json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl": 2390.0, "tp": 2420.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "XAUUSD"
    assert body["side"] == "buy"
    assert body["price"] == 2400.35  # buy fills at ask
    assert body["profit"] is None
    assert body["ticket"] > 0

    positions = api.get("/positions").json()
    assert len(positions) == 1
    assert positions[0]["ticket"] == body["ticket"]
    assert positions[0]["sl"] == 2390.0


def test_order_bumps_volume_up_to_symbol_minimum(api, fake_mt5):
    # A synthetic index (e.g. Deriv's Boom/Crash) with a coarser minimum
    # than the forex-sized default rejected with retcode=10014 (invalid
    # volume) before order_send clamped/snapped to what the symbol accepts.
    fake_mt5.volume_min = 0.2
    fake_mt5.volume_max = 50.0
    fake_mt5.volume_step = 0.2
    _login(api)
    response = api.post("/order", json={"symbol": "Boom 1000 Index", "side": "buy", "volume": 0.01})
    assert response.status_code == 200
    assert response.json()["volume"] == 0.2


def test_order_rejects_unknown_side(api):
    _login(api)
    response = api.post("/order", json={"symbol": "XAUUSD", "side": "long", "volume": 0.1})
    assert response.status_code == 422


def test_order_maps_rejection_to_502(api, fake_mt5):
    _login(api)
    fake_mt5.reject_order = True
    response = api.post("/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1})
    assert response.status_code == 502
    # FakeMt5.reject_order returns retcode=10004 (requote) — the message
    # should decode it in plain English, not just the bare number.
    assert "requote" in response.json()["detail"]


def test_close_position_returns_realized_profit(api):
    _login(api)
    ticket = api.post("/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1}).json()[
        "ticket"
    ]

    response = api.post(f"/positions/{ticket}/close")
    assert response.status_code == 200
    body = response.json()
    assert body["price"] == 2400.10  # buy closes at bid
    assert body["profit"] == 12.5

    assert api.get("/positions").json() == []


def test_modify_position_updates_sl_tp(api):
    _login(api)
    ticket = api.post("/order", json={"symbol": "XAUUSD", "side": "sell", "volume": 0.1}).json()[
        "ticket"
    ]

    response = api.post(f"/positions/{ticket}/modify", json={"sl": 2410.0, "tp": 2380.0})
    assert response.status_code == 200

    positions = api.get("/positions").json()
    assert positions[0]["sl"] == 2410.0
    assert positions[0]["tp"] == 2380.0


def test_close_unknown_position_returns_502(api):
    _login(api)
    response = api.post("/positions/999/close")
    assert response.status_code == 502


def test_trading_requires_login(api):
    response = api.post("/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1})
    assert response.status_code == 502
    assert "not logged in" in response.json()["detail"]
