"""Structured (JSON) log output, selectable alongside the existing human
format (OBSERVABILITY_PLAN.md Phase 5) — see `shared/logging/setup.py`."""

from __future__ import annotations

import json
import logging

from src.shared.logging.account_context import bind_account_id, bind_signal_id
from src.shared.logging.context_filter import ContextFilter
from src.shared.logging.setup import _HUMAN_FORMAT, _JSONFormatter, configure_logging


def _make_record(msg: str = "hello", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="src.engine.application.trade_loop",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_context_filter_stamps_account_and_signal_id_from_contextvars():
    record = _make_record()
    with bind_account_id("acct-1"), bind_signal_id("sig-1"):
        ContextFilter().filter(record)
    assert record.account_id == "acct-1"  # type: ignore[attr-defined]
    assert record.signal_id == "sig-1"  # type: ignore[attr-defined]


def test_context_filter_stamps_none_signal_id_outside_a_signals_window():
    record = _make_record()
    ContextFilter().filter(record)
    assert record.account_id == "default"  # type: ignore[attr-defined]
    assert record.signal_id is None  # type: ignore[attr-defined]


def test_json_formatter_emits_one_valid_json_object_with_expected_fields():
    record = _make_record(msg="SIGNAL: XAUUSD buy")
    ContextFilter().filter(record)
    line = _JSONFormatter().format(record)

    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "src.engine.application.trade_loop"
    assert payload["message"] == "SIGNAL: XAUUSD buy"
    assert payload["account_id"] == "default"
    assert payload["signal_id"] is None
    assert "timestamp" in payload


def test_json_formatter_carries_the_bound_signal_id():
    record = _make_record()
    with bind_account_id("acct-2"), bind_signal_id("sig-2"):
        ContextFilter().filter(record)
    payload = json.loads(_JSONFormatter().format(record))
    assert payload["account_id"] == "acct-2"
    assert payload["signal_id"] == "sig-2"


def test_json_formatter_includes_exception_text_when_present():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record()
        record.exc_info = sys.exc_info()
    ContextFilter().filter(record)
    payload = json.loads(_JSONFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_configure_logging_defaults_to_human_format():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging(level="INFO", database_url=None)
        handler = root.handlers[0]
        assert isinstance(handler.formatter, logging.Formatter)
        assert not isinstance(handler.formatter, _JSONFormatter)
        assert handler.formatter._fmt == _HUMAN_FORMAT  # type: ignore[attr-defined]
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_configure_logging_json_selects_the_json_formatter():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging(level="INFO", database_url=None, log_format="json")
        handler = root.handlers[0]
        assert isinstance(handler.formatter, _JSONFormatter)
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
