"""Correlation-id ContextVar plumbing (OBSERVABILITY_PLAN.md Phase 5) — see
`shared/logging/account_context.py`'s module docstring for why the
set/reset shape matters (asyncio.gather copies the context into subscriber
tasks, but a plain thread does not — see `test_logging_setup.py` /
`test_log_handler.py` for the bug that gap caused)."""

from src.shared.logging.account_context import (
    bind_account_id,
    bind_signal_id,
    current_account_id,
    current_signal_id,
)


def test_current_signal_id_defaults_to_none():
    assert current_signal_id.get() is None


def test_bind_signal_id_sets_and_resets():
    assert current_signal_id.get() is None
    with bind_signal_id("sig-1"):
        assert current_signal_id.get() == "sig-1"
    assert current_signal_id.get() is None


def test_bind_signal_id_nests_and_restores_outer_value():
    with bind_signal_id("outer"):
        assert current_signal_id.get() == "outer"
        with bind_signal_id("inner"):
            assert current_signal_id.get() == "inner"
        assert current_signal_id.get() == "outer"
    assert current_signal_id.get() is None


def test_bind_signal_id_resets_even_on_exception():
    try:
        with bind_signal_id("sig-err"):
            assert current_signal_id.get() == "sig-err"
            raise ValueError("boom")
    except ValueError:
        pass
    assert current_signal_id.get() is None


def test_bind_account_id_and_bind_signal_id_are_independent():
    with bind_account_id("acct-1"), bind_signal_id("sig-1"):
        assert current_account_id.get() == "acct-1"
        assert current_signal_id.get() == "sig-1"
    assert current_account_id.get() == "default"
    assert current_signal_id.get() is None
