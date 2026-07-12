from gateway import mt5_client
from gateway.mt5_client import _retcode_reason


def test_known_retcode_is_decoded():
    assert "autotrading disabled in the terminal" in _retcode_reason(10027)


def test_unknown_retcode_is_silent():
    assert _retcode_reason(99999) == ""


def test_none_retcode_is_silent():
    assert _retcode_reason(None) == ""


def test_filling_type_prefers_fok_when_supported(fake_mt5):
    fake_mt5.filling_mode = fake_mt5.SYMBOL_FILLING_FOK | fake_mt5.SYMBOL_FILLING_IOC
    assert mt5_client.client._filling_type("XAUUSD") == fake_mt5.ORDER_FILLING_FOK


def test_filling_type_falls_back_to_ioc(fake_mt5):
    fake_mt5.filling_mode = fake_mt5.SYMBOL_FILLING_IOC
    assert mt5_client.client._filling_type("XAUUSD") == fake_mt5.ORDER_FILLING_IOC


def test_filling_type_falls_back_to_return_when_neither_supported(fake_mt5):
    # e.g. a synthetic index whose broker only does exchange-style execution —
    # this is exactly what caused retcode=10030 with a hardcoded IOC.
    fake_mt5.filling_mode = 0
    assert mt5_client.client._filling_type("Boom 1000 Index") == fake_mt5.ORDER_FILLING_RETURN


def test_normalize_volume_bumps_up_to_symbol_minimum(fake_mt5):
    # Boom/Crash-style synthetics reject anything below their (much coarser)
    # minimum with retcode=10014 (invalid volume) rather than adjusting it —
    # a forex-sized default of 0.01 should be bumped up to what's tradeable.
    fake_mt5.volume_min = 0.2
    fake_mt5.volume_max = 50.0
    fake_mt5.volume_step = 0.2
    assert mt5_client.client._normalize_volume("Boom 1000 Index", 0.01) == 0.2


def test_normalize_volume_snaps_to_step(fake_mt5):
    fake_mt5.volume_min = 0.2
    fake_mt5.volume_max = 50.0
    fake_mt5.volume_step = 0.2
    assert mt5_client.client._normalize_volume("Boom 1000 Index", 0.5) == 0.4


def test_normalize_volume_caps_at_symbol_maximum(fake_mt5):
    fake_mt5.volume_max = 10.0
    assert mt5_client.client._normalize_volume("XAUUSD", 25.0) == 10.0


def test_normalize_volume_leaves_valid_volume_untouched(fake_mt5):
    assert mt5_client.client._normalize_volume("XAUUSD", 0.5) == 0.5
