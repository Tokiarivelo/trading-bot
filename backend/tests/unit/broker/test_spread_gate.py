from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig

XAUUSD = SymbolTradingConfig(
    symbol="XAUUSD",
    max_spread_points=35,
    min_rr=1.5,
    contract_size=100,
    point=0.01,
    digits=2,
    stops_level=0,
    volume_min=0.01,
    volume_max=50,
    volume_step=0.01,
)


def make_gate() -> SpreadGate:
    return SpreadGate({"XAUUSD": XAUUSD})


def test_allows_trade_within_spread_and_rr():
    gate = make_gate()
    # spread=25pts * point(0.01) = 0.25 spread value; sl=10, required tp = 1.5*(10+0.25)=15.375
    veto = gate.check("XAUUSD", spread_points=25, point=0.01, sl_distance=10.0, tp_distance=16.0)
    assert veto is None


def test_vetoes_when_spread_exceeds_max():
    gate = make_gate()
    veto = gate.check("XAUUSD", spread_points=40, point=0.01, sl_distance=10.0, tp_distance=20.0)
    assert veto is not None
    assert "40pts > max 35pts" in veto.reason


def test_vetoes_when_rr_too_low_after_spread_adjustment():
    gate = make_gate()
    veto = gate.check("XAUUSD", spread_points=25, point=0.01, sl_distance=10.0, tp_distance=10.0)
    assert veto is not None
    assert "min_rr=1.5" in veto.reason


def test_vetoes_unconfigured_symbol():
    gate = make_gate()
    veto = gate.check("BTCUSD", spread_points=5, point=0.01, sl_distance=100.0, tp_distance=500.0)
    assert veto is not None
    assert "no trading config" in veto.reason


def test_boundary_spread_is_allowed():
    gate = make_gate()
    veto = gate.check("XAUUSD", spread_points=35, point=0.01, sl_distance=10.0, tp_distance=16.0)
    assert veto is None
