---
name: new-strategy
description: Scaffold a new trading strategy from a StrategySpec or a plain description — correct Strategy protocol, sandbox-safe imports, unit test stub, registry entry, and a first backtest.
---

# New Strategy

Build a strategy that is not just a `.py` file: "done" means sandbox-valid,
unit-tested, registered as a real `StrategyVersion` (so it shows up in the
Bots page / `GET /strategies/versions` / `GET /backtest/bots`), and backtested
with an actual report. A file dropped into `generated/` without a DB row is
inert — invisible to the registry, the UI, and the backtest CLI. That exact
mistake already exists once in this repo (see step 4) — do not repeat it.

## 1. Get or draft the StrategySpec

`$ARGUMENTS` is either a path to a StrategySpec (JSON/YAML) or a plain
description. If it's a description, draft a `StrategySpec` first and show it
for confirmation before writing any code. Fields, per
`backend/src/strategies/domain/models.py`:

- `name` — snake_case, no spaces, e.g. `xauusd_liquidity_sweep`. This becomes
  both the DB family name and the generated filename stem. Several existing
  files in `generated/` have spaces in the name (typed straight from a
  free-text description, e.g. `"pob_price_action_snd for vix75"`) — that
  breaks normal module import (`from src.strategies.generated.X import Y`
  isn't a valid identifier) and forces their tests to load the file via
  `importlib.util` instead. Don't produce another one of these.
- `symbols` — tuple of exact strings matching an existing
  `configs/symbols/*.yaml`'s `symbol:` field: `XAUUSD`, `XAGUSD`, `BTCUSD`,
  `"Boom 1000 Index"`, `"Volatility 75 Index"`. A symbol with no config file
  has no `max_spread_points`/`min_rr` cap (falls back to
  `SpreadGate.DEFAULT_MIN_RR = 1.0`, no spread cap at all) — fine for a
  backtest, not something to rely on for live trading without flagging it to
  the user.
- `entry_timeframe` — always `"M5"` (project rule, F6).
- `confirmation_timeframes` — higher-TF confluence the strategy checks before
  entering. Usually `("H1", "H4")`; an intrabar zone-retest strategy may use
  `("M15", "M30")` instead (see `pob_snd_zones_vix75_v1.py`) — pick whatever
  the spec's confirmation logic actually reads. Valid values: `M1 M5 M15 M30
  H1 H4 D1 W1 MN`.
- `params` — every tunable constant `evaluate()` uses (lookbacks, ATR
  multipliers, RR ratio, confidence thresholds…). Nothing that should be
  tunable stays hardcoded inline.

## 2. Write the strategy source

One class implementing the `Strategy` protocol: a `spec: StrategySpec`
attribute and `def evaluate(self, ctx: MarketContext) -> Signal | None`.
`__init__` takes no required args.

Sandbox constraints (`backend/src/strategies/sandbox.py` enforces these by
AST scan, then again at restricted-exec time — violating any of them fails
validation, not just a lint warning):
- Imports: **only** `math`, `statistics`, `numpy`, `pandas`,
  `src.strategies.domain.models`. Nothing else — no `os`, no `datetime`
  (candle timestamps arrive as pandas `Timestamp` already), no local helper
  modules.
- No dunder attribute access (`x.__class__`, etc.), no
  `exec`/`eval`/`compile`/`open`/`__import__`/`input`, no `global`/`nonlocal`.
- `evaluate()` is a pure function: reads `ctx.candles[timeframe]` (a pandas
  DataFrame with `open/high/low/close/tick_volume`, plus `time` if the
  strategy needs it for `PriceZone`/`StructurePoint` annotations) and
  `ctx.spread_points`. No I/O, no randomness, no mutated module state across
  calls.
- Guard short history explicitly and `return None` — the sandbox smoke-tests
  `evaluate()` once against ~60 bars of synthetic data at validation time
  (2s timeout in a worker thread); an unguarded index/lookback that assumes
  more history than that will fail validation, not just fail at runtime.
- `Signal.sl_points`/`tp_points` are **positive price distances**, not price
  levels.
- Size the reward:risk with headroom over the target symbol's
  `configs/symbols/<symbol>.yaml` `min_rr` (currently 1.5 for XAUUSD/BTCUSD/
  Boom 1000/Volatility 75, 1.8 for XAGUSD). `SpreadGate.check()` requires
  `tp_distance >= min_rr * (sl_distance + spread)` before any trade is taken
  — cut it too close (or match `min_rr` exactly) and every single signal gets
  vetoed at the broker layer, which shows up as a mysteriously trade-free
  backtest with no error. `breakout_v1.py` sets `TP_RR = 2.2` against a 1.5
  floor for exactly this reason — mirror that margin, don't just clear the
  floor.
- Put the concrete numbers that justified the decision in `Signal.reason`
  (entry/sl/tp prices, the pattern matched, confirmation count) — this string
  is what shows up in the activity log and backtest report; "money-touching
  code paths: explicit over clever" per project rules.

Match style to the closest existing strategy rather than inventing
conventions: `backend/src/strategies/generated/breakout_v1.py` for a simple
single-timeframe strategy, `pob_snd_zones_vix75_v1.py` for a multi-timeframe
supply/demand zone-and-confirmation strategy.

## 3. Validate in the sandbox before writing anything permanent

Iterate against the exact gate the DB/registry will apply, on a scratch file,
before touching `generated/`:

```bash
cd backend && uv run python -c "
from src.strategies.sandbox import validate_and_load
src = open('/tmp/candidate.py').read()
instance, errors = validate_and_load(src)
print(errors if errors else f'OK: {instance.spec.name}')
"
```

Fix everything here first. This is the same function `save_generated_code`,
`activate_version`, and the AI codegen pipeline all call — passing it here
means it will pass for real in step 4.

## 4. Persist and register — do not hand-place the file

**Do not `Write` the `.py` file straight into `generated/`.** That is exactly
how `pob_snd_zones_vix75_v1.py` ended up in this repo unregistered — a file
with a matching unit test, but no `StrategyVersion` row, invisible to
`StrategyRegistry`, the Bots page, and the backtest CLI/API alike. Always go
through `StrategyVersionService.save_generated_code`, which validates again,
picks the canonical filename (`<name>_v1.py`), writes it, and inserts the DB
row as `VALIDATED`:

```bash
cd backend && uv run python -c "
from pathlib import Path
from src.shared.config.settings import Settings
from src.shared.db.base import make_session_factory
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.domain.versioning import CodeSource
from src.strategies.registry import StrategyRegistry

settings = Settings()
repo = StrategyVersionRepository(make_session_factory(settings.database_url))
svc = StrategyVersionService(
    repository=repo,
    registry=StrategyRegistry(),
    generated_dir=Path('src/strategies/generated'),
)
code = Path('/tmp/candidate.py').read_text()
version = svc.save_generated_code(name='<family_name>', code=code, source=CodeSource.MANUAL)
print(version.id, version.file_path, version.status)
"
```

Record the printed `version.id` (a UUID) and `version.file_path` — both are
needed below. Status will always be `VALIDATED`. **Never call
`svc.activate_version(...)` or `POST /strategies/versions/{id}/activate`** —
per project rules, activating for live trading is a user action taken in the
UI, not something this skill does on the user's behalf.

## 5. Unit tests

`backend/tests/unit/strategies/test_<name>.py`. Because the family name is a
clean identifier, import the class directly — no `importlib.util` needed:

```python
from src.strategies.generated.<name>_v1 import <ClassName>
```

Minimum coverage:
- `evaluate()` returns a `Signal` on a fixture that hand-builds the exact
  setup, candle by candle (see `pob_snd_zones_vix75_v1`'s `_bar()` helper for
  the pattern) — assert direction, `sl_points > 0`, `tp_points/sl_points`
  matches the configured RR, and anything in `reason` worth pinning.
- Returns `None` on too-short history.
- Returns `None` when the setup exists but its confirmation doesn't (e.g. no
  HTF engulf, stale retest, pattern in the wrong direction) — the negative
  cases are usually where real bugs hide.
- If the strategy has internal helper functions (zone/pattern detection,
  indicator math), test those directly too, not only end-to-end through
  `evaluate()`.

## 6. Run the quality gate

```bash
cd backend && uv run ruff check src tests
cd backend && uv run pytest tests/unit/strategies/test_<name>.py
```

## 7. Backtest

`python -m src.backtest.cli` / `make backtest` only resolve a strategy that
is either one of the four hardcoded baselines (`breakout_v1`,
`trend_structure_v1/v2`, `mean_reversion_v1`) or already `ACTIVE` — a
freshly `VALIDATED` version from step 4 is invisible to it. Use the same job
API the UI's "Run Backtest" panel uses, targeting the **version id**, not the
family name (needs the backend running — `make dev-backend` in another
terminal):

```bash
curl -s -X POST http://localhost:8000/backtest/run \
  -H 'content-type: application/json' \
  -d '{"strategy_id":"<version.id>","symbol":"<symbol>","period":"2025-01:2025-06"}'
# -> {"job_id": "...", "status": "pending"}

curl -s http://localhost:8000/backtest/run/<job_id>   # poll until status == "done"
curl -s http://localhost:8000/backtest/reports/<report_id>
```

If the requested period isn't in the local candle DB yet, `/backtest/run`
auto-backfills it from the gateway before replaying — no separate
`/market-data/backfill` call needed. (Once the user activates the strategy,
the plain CLI/`make backtest strategy=<name> symbol=<symbol> period=...`
works too, per `.claude/skills/backtest`.)

## 8. Report to the user

- Spec summary: symbols, timeframes, entry logic in 2-3 sentences, key params.
- File path, strategy version id, DB status (`VALIDATED`).
- ruff/pytest result.
- Backtest metrics: trades, win rate, profit factor, max drawdown, avg R. If
  trades = 0 against real market data, say so explicitly and check the RR
  floor / gating logic first — a silently-vetoed strategy looks identical to
  "no setups occurred" otherwise.
- Remind the user that activation (`POST /strategies/versions/{id}/activate`
  or the Bots page) is their call, not something this skill did.

## Must never

- Touch `configs/risk.yaml` or `backend/src/engine/`.
- Add imports outside `math`, `statistics`, `numpy`, `pandas`,
  `src.strategies.domain.models`.
- Call `activate_version` / `POST /strategies/versions/{id}/activate` —
  activation for live trading is a user action.
- Write the generated `.py` file directly instead of going through
  `StrategyVersionService.save_generated_code` — that produces an orphaned,
  unregistered strategy that nothing in the app can see.
- Run backtests against anything but the replay/paper path (already true of
  `/backtest/run` and the CLI) — never a live account.
