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


def test_unconfigured_symbol_has_no_spread_cap():
    gate = make_gate()
    # No config for "Boom 1000 Index" — an enormous spread_points count would
    # have failed any flat cap (e.g. XAUUSD's 35), but there's none to guess
    # at for an arbitrary symbol's own point scale, so it's skipped. Keep
    # `point` tiny so the spread's contribution to the (still-enforced) RR
    # check stays negligible — isolates the spread-cap behavior from RR.
    veto = gate.check(
        "Boom 1000 Index", spread_points=9999, point=0.00001, sl_distance=10.0, tp_distance=20.0
    )
    assert veto is None


def test_unconfigured_symbol_still_enforces_default_rr():
    gate = make_gate()
    veto = gate.check(
        "Boom 1000 Index", spread_points=5, point=0.01, sl_distance=10.0, tp_distance=5.0
    )
    assert veto is not None
    assert "min_rr=1.0" in veto.reason


def test_zero_distance_is_still_rejected_by_rr():
    # sl_distance/tp_distance of 0.0 (not None) means both were *given* as
    # exactly the reference price — a degenerate case the RR check still runs
    # against and rejects, unlike the None ("not provided") case below.
    gate = make_gate()
    veto = gate.check(
        "Boom 1000 Index", spread_points=5, point=0.01, sl_distance=0.0, tp_distance=0.0
    )
    assert veto is not None


def test_missing_sl_or_tp_skips_the_rr_check():
    # sl/tp are optional for manual trades (F-manual-trading) — omitting
    # either one means there's no RR to evaluate, so it's allowed regardless
    # of how bad the ratio would otherwise be.
    gate = make_gate()
    assert (
        gate.check("XAUUSD", spread_points=25, point=0.01, sl_distance=None, tp_distance=None)
        is None
    )
    assert (
        gate.check("XAUUSD", spread_points=25, point=0.01, sl_distance=10.0, tp_distance=None)
        is None
    )
    assert (
        gate.check("XAUUSD", spread_points=25, point=0.01, sl_distance=None, tp_distance=1.0)
        is None
    )


def test_boundary_spread_is_allowed():
    gate = make_gate()
    veto = gate.check("XAUUSD", spread_points=35, point=0.01, sl_distance=10.0, tp_distance=16.0)
    assert veto is None
