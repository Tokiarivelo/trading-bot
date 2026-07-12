"""Adversarial sandbox tests (§6.5, §11) — generated code trying forbidden
imports/IO/reflection tricks must be rejected, and a hung `evaluate()` must
not hang validation itself."""

from __future__ import annotations

from src.strategies.sandbox import validate_and_load

VALID_STRATEGY = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class GoldEmaPullback:
    def __init__(self):
        self.spec = StrategySpec(
            name="gold_ema_pullback",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M5",
            confirmation_timeframes=("H1",),
            params={},
        )

    def evaluate(self, ctx: MarketContext):
        m5 = ctx.candles.get("M5")
        if m5 is None or len(m5) < 5:
            return None
        if m5.iloc[-1]["close"] > m5.iloc[-2]["close"]:
            return Signal(
                direction=Direction.BUY, sl_points=5.0, tp_points=10.0, reason="test"
            )
        return None
"""


def test_valid_strategy_loads():
    instance, errors = validate_and_load(VALID_STRATEGY)
    assert errors == ()
    assert instance is not None
    assert instance.spec.name == "gold_ema_pullback"


def test_forbidden_import_rejected():
    code = """
import os
from src.strategies.domain.models import MarketContext, StrategySpec


class Evil:
    def __init__(self):
        self.spec = StrategySpec(
            name="evil", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        os.system("echo pwned")
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("os" in e for e in errors)


def test_forbidden_import_from_rejected():
    code = """
from socket import socket
from src.strategies.domain.models import MarketContext, StrategySpec


class Evil:
    def __init__(self):
        self.spec = StrategySpec(
            name="evil", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        return None
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("socket" in e for e in errors)


def test_dunder_sandbox_escape_rejected():
    code = """
from src.strategies.domain.models import MarketContext, StrategySpec


class Evil:
    def __init__(self):
        self.spec = StrategySpec(
            name="evil", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        return ().__class__.__bases__[0].__subclasses__()
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("dunder" in e for e in errors)


def test_exec_call_rejected():
    code = """
from src.strategies.domain.models import MarketContext, StrategySpec


class Evil:
    def __init__(self):
        self.spec = StrategySpec(
            name="evil", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        exec("print(1)")
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("exec" in e for e in errors)


def test_open_call_rejected():
    code = """
from src.strategies.domain.models import MarketContext, StrategySpec


class Evil:
    def __init__(self):
        self.spec = StrategySpec(
            name="evil", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        open("/etc/passwd")
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("open" in e for e in errors)


def test_syntax_error_rejected():
    instance, errors = validate_and_load("def broken(:\n    pass")
    assert instance is None
    assert any("syntax error" in e for e in errors)


def test_missing_strategy_class_rejected():
    code = "x = 1\n"
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("no class implementing" in e for e in errors)


def test_hung_evaluate_times_out_without_hanging_validation():
    code = """
from src.strategies.domain.models import MarketContext, StrategySpec


class Infinite:
    def __init__(self):
        self.spec = StrategySpec(
            name="infinite", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        while True:
            pass
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("did not return within" in e for e in errors)


def test_empty_symbols_rejected_before_smoke_test():
    code = """
from src.strategies.domain.models import MarketContext, StrategySpec


class NoSymbols:
    def __init__(self):
        self.spec = StrategySpec(
            name="no_symbols", version=1, symbols=(), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx):
        return None
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("no symbols configured" in e for e in errors)
