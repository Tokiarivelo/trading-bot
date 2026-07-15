"""Sandbox validation for custom indicator code (mirrors `strategies/sandbox.py`).

This is the ONLY place indicator code (stored in the `indicators` table's
`code` column) is compiled and executed before it's trusted enough to run
against real candle history. Two layers, both must pass:

1. Static AST scan — reject forbidden imports and dangerous nodes (dunder
   attribute access, `exec`/`eval`/`open`/`__import__` calls, `global`/
   `nonlocal`) before a single line of the code runs.
2. Restricted exec — the module runs with a minimal `__builtins__` and its
   own `__import__` that only allows the whitelisted modules, so even a
   trick the AST scan didn't anticipate has nothing dangerous within reach.

After loading, a smoke test calls `compute()` once against a synthetic candle
DataFrame in a worker thread with a wall-clock timeout, so an infinite loop
or a multi-second computation fails validation instead of stalling a request.
This is a lightweight guard, not a full process sandbox — same posture as
`strategies/sandbox.py`.

Deliberately NOT imported from/into `strategies/sandbox.py` — CLAUDE.md:
modules communicate via the event bus or container-wired application-service
calls, never by reaching into another module's internals. This is a small,
independent copy of the same safety pattern (see `ai/domain/models.py` vs.
`strategies/api/schemas.py`'s legacy-indicator regex for the same convention
already used elsewhere in this codebase).
"""

from __future__ import annotations

import ast
import builtins
import math
import threading

import pandas as pd

from src.indicators.domain.models import Indicator

ALLOWED_IMPORT_MODULES = frozenset({"math", "statistics", "numpy", "pandas"})
FORBIDDEN_CALL_NAMES = frozenset({"exec", "eval", "compile", "open", "__import__", "input"})
_SMOKE_TIMEOUT_SECONDS = 2.0


def validate_and_load(source: str) -> tuple[Indicator | None, tuple[str, ...]]:
    """Validate `source` and, if it passes, return a ready-to-use `Indicator`
    instance. On failure, the instance is `None` and the errors explain why —
    callers surface these directly to the trader rather than guessing."""
    static_errors = _static_scan(source)
    if static_errors:
        return None, tuple(static_errors)

    module_globals: dict[str, object] = {
        "__name__": "sandboxed_indicator",
        "__builtins__": _safe_builtins(),
    }
    try:
        code = compile(source, "<generated-indicator>", "exec")
        exec(code, module_globals)  # noqa: S102 — restricted namespace, see module docstring
    except Exception as exc:
        return None, (f"execution error while loading module: {exc!r}",)

    indicator_cls = _find_indicator_class(module_globals)
    if indicator_cls is None:
        return None, (
            "no class implementing the Indicator protocol (a `compute` method) was found",
        )

    try:
        instance = indicator_cls()
    except Exception as exc:
        return None, (f"could not instantiate indicator: {exc!r}",)

    if not isinstance(instance, Indicator):
        return None, ("class does not satisfy the Indicator protocol (missing compute())",)

    smoke_errors = _smoke_test(instance)
    if smoke_errors:
        return None, smoke_errors

    return instance, ()


def _static_scan(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORT_MODULES:
                    errors.append(f"forbidden import: {alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED_IMPORT_MODULES:
                errors.append(f"forbidden import: {node.module!r}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                errors.append(f"forbidden dunder attribute access: {node.attr!r}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALL_NAMES:
                errors.append(f"forbidden call: {node.func.id}()")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            errors.append("global/nonlocal statements are not allowed")
    return errors


def _safe_import(name: str, *args: object, **kwargs: object) -> object:
    # See strategies/sandbox.py's `_safe_import` for why submodule imports of
    # an already-whitelisted top-level package (numpy/pandas lazily
    # `__import__`-ing their own internals) are allowed through.
    top_level = name.partition(".")[0]
    if name not in ALLOWED_IMPORT_MODULES and top_level not in ALLOWED_IMPORT_MODULES:
        raise ImportError(f"import of {name!r} is not allowed in sandboxed indicator code")
    return __import__(name, *args, **kwargs)


def _safe_builtins() -> dict[str, object]:
    names = [
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "issubclass",
        "len",
        "list",
        "map",
        "max",
        "min",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
        "object",
        "super",
        "staticmethod",
        "classmethod",
        "property",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "StopIteration",
        "ZeroDivisionError",
        "ArithmeticError",
    ]
    safe = {name: getattr(builtins, name) for name in names if hasattr(builtins, name)}
    safe["__import__"] = _safe_import
    safe["__build_class__"] = builtins.__build_class__  # required for `class` statements
    safe["True"] = True
    safe["False"] = False
    safe["None"] = None
    return safe


def _find_indicator_class(module_globals: dict[str, object]) -> type | None:
    for value in module_globals.values():
        if (
            isinstance(value, type)
            and getattr(value, "__module__", None) == "sandboxed_indicator"
            and hasattr(value, "compute")
        ):
            return value
    return None


def _smoke_test(instance: Indicator) -> tuple[str, ...]:
    candles = _synthetic_candles()
    outcome: dict[str, object] = {}

    def _run() -> None:
        try:
            outcome["result"] = instance.compute(candles, {})
        except Exception as exc:
            outcome["error"] = exc

    # A Python thread can't be force-killed, so a hung `compute()` leaks a
    # worker thread if it never returns. `daemon=True` at least means that
    # leak can't block interpreter shutdown — acceptable for a
    # validation-time smoke test (see module docstring).
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_SMOKE_TIMEOUT_SECONDS)
    if thread.is_alive():
        return (f"compute() did not return within {_SMOKE_TIMEOUT_SECONDS}s",)
    if "error" in outcome:
        return (f"compute() raised during smoke test: {outcome['error']!r}",)

    result = outcome.get("result")
    if not isinstance(result, dict):
        return (f"compute() must return a dict[str, list], got {type(result).__name__}",)
    for series_name, values in result.items():
        if not isinstance(series_name, str):
            return (f"compute() dict keys must be strings, got {type(series_name).__name__!r}",)
        try:
            list(values)
        except TypeError:
            return (f"compute() series {series_name!r} is not list-like: {values!r}",)
    return ()


def _synthetic_candles(rows: int = 60) -> pd.DataFrame:
    price = 2000.0
    data = []
    for i in range(rows):
        price += math.sin(i / 5) * 2
        data.append(
            {
                "open": price,
                "high": price + 1.5,
                "low": price - 1.5,
                "close": price + math.cos(i / 7),
                "tick_volume": 100 + i,
            }
        )
    return pd.DataFrame(data)
