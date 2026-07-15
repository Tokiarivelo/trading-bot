"""Adversarial sandbox tests for custom indicators — mirrors
`tests/unit/strategies/test_sandbox.py`: forbidden imports/IO/reflection
tricks must be rejected, and a hung `compute()` must not hang validation."""

from __future__ import annotations

import pytest

from src.indicators.sandbox import _safe_import, validate_and_load

VALID_INDICATOR = """
import pandas as pd


class SimpleMovingAverage:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict:
        period = int(params.get("period", 20))
        sma = candles["close"].rolling(period).mean()
        return {"value": sma.tolist()}
"""


def test_valid_indicator_loads():
    instance, errors = validate_and_load(VALID_INDICATOR)
    assert errors == ()
    assert instance is not None


def test_forbidden_import_rejected():
    code = """
import os


class Evil:
    def compute(self, candles, params):
        os.system("echo pwned")
        return {}
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("os" in e for e in errors)


def test_forbidden_import_from_rejected():
    code = """
from socket import socket


class Evil:
    def compute(self, candles, params):
        return {}
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("socket" in e for e in errors)


def test_dunder_sandbox_escape_rejected():
    code = """
class Evil:
    def compute(self, candles, params):
        return ().__class__.__bases__[0].__subclasses__()
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("dunder" in e for e in errors)


def test_exec_call_rejected():
    code = """
class Evil:
    def compute(self, candles, params):
        exec("print(1)")
        return {}
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("exec" in e for e in errors)


def test_open_call_rejected():
    code = """
class Evil:
    def compute(self, candles, params):
        open("/etc/passwd")
        return {}
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("open" in e for e in errors)


def test_syntax_error_rejected():
    instance, errors = validate_and_load("def broken(:\n    pass")
    assert instance is None
    assert any("syntax error" in e for e in errors)


def test_missing_indicator_class_rejected():
    instance, errors = validate_and_load("x = 1\n")
    assert instance is None
    assert any("no class implementing" in e for e in errors)


def test_hung_compute_times_out_without_hanging_validation():
    code = """
class Infinite:
    def compute(self, candles, params):
        while True:
            pass
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("did not return within" in e for e in errors)


def test_non_dict_return_rejected():
    code = """
class NotADict:
    def compute(self, candles, params):
        return [1, 2, 3]
"""
    instance, errors = validate_and_load(code)
    assert instance is None
    assert any("must return a dict" in e for e in errors)


def test_safe_import_allows_numpy_internal_submodule():
    assert _safe_import("numpy._core._methods") is not None
    assert _safe_import("pandas._libs.lib") is not None


def test_safe_import_still_rejects_unrelated_dotted_import():
    with pytest.raises(ImportError, match="os.path"):
        _safe_import("os.path")


def test_indicator_using_numpy_reductions_loads():
    code = """
import numpy as np
import pandas as pd


class NumpyUser:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict:
        mean_close = float(candles["close"].mean())
        total_volume = float(np.array(candles["tick_volume"].to_numpy()).sum())
        return {"value": [mean_close + total_volume] * len(candles)}
"""
    instance, errors = validate_and_load(code)
    assert errors == ()
    assert instance is not None
