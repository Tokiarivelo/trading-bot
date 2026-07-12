"""Sandbox validation for AI-generated strategy code (§6.5, §11).

This is the ONLY place generated code (`strategies/generated/*.py`) is
compiled and executed before it is trusted enough to register in the
`StrategyRegistry`. Two layers, both must pass:

1. Static AST scan — reject forbidden imports and dangerous nodes (dunder
   attribute access, `exec`/`eval`/`open`/`__import__` calls, `global`/
   `nonlocal`) before a single line of the code runs.
2. Restricted exec — the module runs with a minimal `__builtins__` and its
   own `__import__` that only allows the whitelisted modules, so even a
   trick the AST scan didn't anticipate has nothing dangerous within reach.

After loading, a smoke test calls `evaluate()` once against synthetic candles
in a worker thread with a wall-clock timeout, so an infinite loop or a
multi-second computation fails validation instead of stalling the engine.
This is a lightweight guard, not a full process sandbox — good enough for
"AI-generated code that's supposed to just look at a DataFrame and do
arithmetic", not a defense against a deliberately hostile actor with shell
access to this repo.
"""

from __future__ import annotations

import ast
import builtins
import math
import threading

import pandas as pd

from src.strategies.domain.models import MarketContext, Strategy

ALLOWED_IMPORT_MODULES = frozenset(
    {"math", "statistics", "numpy", "pandas", "src.strategies.domain.models"}
)
FORBIDDEN_CALL_NAMES = frozenset({"exec", "eval", "compile", "open", "__import__", "input"})
_SMOKE_TIMEOUT_SECONDS = 2.0


def validate_and_load(source: str) -> tuple[Strategy | None, tuple[str, ...]]:
    """Validate `source` and, if it passes, return a ready-to-use `Strategy`
    instance. On failure, the instance is `None` and the errors explain why —
    callers (the AI codegen pipeline, `new-strategy`/`refine-bot` skills)
    surface these directly to the user rather than guessing."""
    static_errors = _static_scan(source)
    if static_errors:
        return None, tuple(static_errors)

    module_globals: dict[str, object] = {
        "__name__": "sandboxed_strategy",
        "__builtins__": _safe_builtins(),
    }
    try:
        code = compile(source, "<generated-strategy>", "exec")
        exec(code, module_globals)  # noqa: S102 — restricted namespace, see module docstring
    except Exception as exc:
        return None, (f"execution error while loading module: {exc!r}",)

    strategy_cls = _find_strategy_class(module_globals)
    if strategy_cls is None:
        return None, ("no class implementing the Strategy protocol (spec + evaluate) was found",)

    try:
        instance = strategy_cls()
    except Exception as exc:
        return None, (f"could not instantiate strategy: {exc!r}",)

    if not isinstance(instance, Strategy):
        return None, ("class does not satisfy the Strategy protocol (missing spec/evaluate)",)

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
    if name not in ALLOWED_IMPORT_MODULES:
        raise ImportError(f"import of {name!r} is not allowed in sandboxed strategy code")
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


def _find_strategy_class(module_globals: dict[str, object]) -> type | None:
    for value in module_globals.values():
        if (
            isinstance(value, type)
            and getattr(value, "__module__", None) == "sandboxed_strategy"
            and hasattr(value, "evaluate")
        ):
            return value
    return None


def _smoke_test(instance: Strategy) -> tuple[str, ...]:
    ctx = _synthetic_context(instance.spec)
    outcome: dict[str, object] = {}

    def _run() -> None:
        try:
            outcome["result"] = instance.evaluate(ctx)
        except Exception as exc:
            outcome["error"] = exc

    # A Python thread can't be force-killed, so a hung `evaluate()` leaks a
    # worker thread if it never returns. `daemon=True` at least means that
    # leak can't block interpreter shutdown — acceptable for a
    # validation-time smoke test (see module docstring), never acceptable
    # for the request/test process itself to hang.
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_SMOKE_TIMEOUT_SECONDS)
    if thread.is_alive():
        return (f"evaluate() did not return within {_SMOKE_TIMEOUT_SECONDS}s",)
    if "error" in outcome:
        return (f"evaluate() raised during smoke test: {outcome['error']!r}",)
    return ()


def _synthetic_context(spec: object) -> MarketContext:
    symbols = getattr(spec, "symbols", None) or ("XAUUSD",)
    confirmation_tfs = getattr(spec, "confirmation_timeframes", ())
    timeframes = {getattr(spec, "entry_timeframe", "M5"), *confirmation_tfs}
    return MarketContext(
        symbol=symbols[0],
        candles={tf: _synthetic_candles() for tf in timeframes},
        spread_points=20.0,
    )


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
