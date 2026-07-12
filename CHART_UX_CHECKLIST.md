# Chart & Bot UX — Implementation Checklist

Scope: five UX issues on the chart panel and symbol picker, plus opening up
bot/strategy generation to any symbol. Each section lists root cause (from
reading the current code), the fix, and files touched.

---

## 1. TradingView attribution logo on the chart

**Context:** `frontend/src/features/chart/ChartPanel.tsx` creates the chart
via `createChart()` (lightweight-charts v5, `package.json:13`) without
setting `layout.attributionLogo`. The free tier of `lightweight-charts` is
licensed on condition that this attribution mark stays visible — it must
not be removed or hidden without a commercial TradingView license.

- [ ] Explicitly set `layout.attributionLogo: true` in the `createChart()`
      options in `ChartPanel.tsx` (don't rely on the implicit default —
      make the license condition visible in the code).
- [ ] Check the current CSS doesn't clip/overlap it: the chart container is
      `<div ref={containerRef} className="h-full w-full" />` inside a
      `relative` wrapper that also absolutely-positions `newsBands` and the
      "Loading history…" badge (`ChartPanel.tsx:476-499`) — verify z-index /
      corner placement don't overlap the attribution mark in the bottom-right.
- [ ] Confirm in both light and dark theme (`--color-panel` background) the
      logo remains legible.
- [ ] Do **not** attempt to swap in a different/custom logo image — that
      would violate the attribution license; the ask is to make sure
      TradingView's own mark renders, not to reskin it.

---

## 2. Reload always lands on XAUUSD instead of the last-viewed symbol

**Root cause:** `frontend/src/app/page.tsx` seeds state with
`useState("XAUUSD")` (`page.tsx:19`) and only overrides it from the
`?symbol=` query string inside a `useEffect` (`page.tsx:26-47`). Anything
that drops the query param — a bookmarked bare `/`, a link without the
query, clearing the URL bar, some proxy/rewrite stripping query strings —
falls back to the hardcoded default. There is currently no persistence of
"last selected symbol" outside the URL; `EXTRA_SYMBOLS_KEY` in
`localStorage` only remembers *extra/browsed* symbols, not the active one.

- [ ] Add a `tb.lastSymbol` `localStorage` key, written in the same effect
      that currently does `url.searchParams.set(SYMBOL_QUERY_KEY, symbol)`
      (`page.tsx:51-55`).
- [ ] On mount, resolve the initial symbol with this precedence: `?symbol=`
      query param → `tb.lastSymbol` from `localStorage` → first configured
      symbol (see §4 — no more hardcoded `XAUUSD` fallback).
- [ ] Remove the `useState("XAUUSD")` hardcoded seed; initialize to `null`/
      "resolving" and render a lightweight loading state for `ChartPanel`
      until the effect resolves the real symbol, so there's no visible flash
      of XAUUSD before the correct symbol swaps in.
- [ ] Unit/manual test: set symbol to something not in `DEFAULT_SYMBOLS`,
      hard-reload with no query string (simulate clearing it), confirm it
      restores from `localStorage` instead of falling back.

---

## 3. Switching symbols loses candle position / chart looks trimmed

**Root cause:** in `ChartPanel.tsx`'s symbol/timeframe effect
(`ChartPanel.tsx:196-324`), history load calls
`chart?.timeScale().scrollToRealTime()` (`ChartPanel.tsx:280`) once candles
are set. `scrollToRealTime()` only scrolls the time axis to "now" — it does
**not** reset the logical range/zoom level or the price scale, so whatever
zoom/pan and autoscale state was active for the *previous* symbol's price
range carries over. Since each symbol has a wildly different price scale
(e.g. BTCUSD ~60000 vs XAGUSD ~30), the inherited logical range can put the
new candles partly or fully outside the visible viewport, and the visible
window can end up narrower than the loaded data ("trimmed" look) if the old
zoom level doesn't match the new bar spacing.

- [ ] Replace (or follow) `scrollToRealTime()` with `fitContent()` — or
      explicitly compute and set a visible logical range covering the last
      N bars — right after `render()` in the `getCandles(...).then(...)`
      handler (`ChartPanel.tsx:269-281`), so the new symbol always opens
      fully fit to its own data instead of inheriting the old viewport.
- [ ] Force the price scale to autoscale on symbol switch: call
      `candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true })`
      (or re-apply default price scale options) when the symbol changes, in
      case a manual zoom/drag on the previous symbol left `autoScale: false`.
- [ ] Verify the "trimmed" complaint isn't a pagination artifact: confirm
      `hasMoreHistoryRef` / `loadingMoreRef` are correctly reset per symbol
      (they already are, `ChartPanel.tsx:207-210`) and that the initial
      `CANDLE_COUNT` (300, `ChartPanel.tsx:35`) fetch actually resolves
      before `fitContent()` runs — race with the WS `historyLoadedRef` gate
      if needed.
- [ ] Manual test matrix: switch XAUUSD → BTCUSD → XAGUSD → back to XAUUSD,
      across each timeframe, confirming candles are always centered/fit and
      never rendered off-screen above/below the visible price axis.

---

## 4. Remove hardcoded default symbols; add favorites/bookmarks

**Root cause:** `DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "BTCUSD"]`
(`page.tsx:14`) is used both as the nav bar's symbol chips
(`configuredSymbols = config?.symbols ?? DEFAULT_SYMBOLS`, `page.tsx:57`)
and as a fallback for `getAppConfig()`. `config.symbols` itself comes from
`configs/app.yaml: symbols: [XAUUSD, XAGUSD, BTCUSD]` — the **engine's**
automated-trading symbol list, which is a separate concern from "what's
pinned in the chart nav bar." Today the UI conflates the two: the nav bar
always shows exactly the engine's trading symbols plus whatever was
transiently browsed via `SymbolPicker` (`extraSymbols`, cleared on removal,
never explicitly "kept").

- [ ] Introduce a distinct `tb.favoriteSymbols` `localStorage` list,
      independent from both `configuredSymbols` (engine-traded) and
      `extraSymbols` (transient browse history) — this is the user's
      pinned/bookmarked set for quick chart access.
- [ ] Change the nav bar in `page.tsx` (`page.tsx:90-123`) to render
      favorites (persisted, user-controlled) instead of hardcoding
      `configuredSymbols` as the default chip set. Still show which symbols
      are engine-traded (e.g. a small badge/tooltip) since that's
      operationally relevant, but stop treating "engine-traded" and
      "shown in nav" as the same list.
- [ ] Add a star/bookmark toggle:
  - In `SymbolPicker.tsx`'s result list (`SymbolPicker.tsx:133-149`), add a
    star icon per row to add/remove from favorites without necessarily
    switching the active chart symbol.
  - In `page.tsx`'s existing chip rendering (both the `configuredSymbols`
    map and `extraSymbols` map, `page.tsx:90-121`), add the same toggle so
    any symbol currently on screen can be pinned/unpinned in place.
- [ ] Decide de-dup/ordering rules: favorites persist across sessions;
      non-favorited "browsed" symbols keep today's transient behavior
      (shown until explicitly removed via the `×`, per `removeExtraSymbol`,
      `page.tsx:70-75`); the last-selected symbol (§2) always resolves even
      if it isn't a favorite.
- [ ] `removeExtraSymbol`'s fallback of `setSymbol(configuredSymbols[0])`
      (`page.tsx:74`) needs a new fallback once `configuredSymbols` is no
      longer guaranteed non-empty/relevant to the nav — fall back to first
      favorite, else first engine-configured symbol.
- [ ] Migration: on first load after this ships, seed
      `tb.favoriteSymbols` from the current `DEFAULT_SYMBOLS` /
      `config.symbols` once, so existing users don't lose their nav bar
      contents outright — but stop hardcoding the constant going forward.

---

## 5. Bot/strategy generation for any symbol — choose, duplicate, rename

**Context:** there's no separate "bot" entity today — a strategy version
(`backend/src/strategies/domain/versioning.py`, exposed via
`backend/src/strategies/api/routes.py`) *is* the bot, produced by the PDF
pipeline (`StrategyUploadForm.tsx` → `StrategyDraftDetail.tsx` →
`generateStrategyCode`). The `symbols` field is already free-text/editable
per draft (`StrategyDraftDetail.tsx:127-134`, comma-separated, not limited
to XAUUSD/XAGUSD/BTCUSD) — generation itself isn't actually hardcoded to
the three default symbols. What's missing: an explicit symbol picker (vs.
typing comma-separated text pulled from whatever the PDF extracted),
duplicate, and rename, none of which exist in
`backend/src/strategies/api/routes.py` or the versioning service today.

- [ ] **Symbol selection UX:** replace the free-text "Symbols
      (comma-separated)" input in `StrategyDraftDetail.tsx:127-134` with a
      multi-select built on the same broker symbol catalog
      `SymbolPicker.tsx` already queries (`getBrokerSymbols`,
      `shared/api/client`) — so users pick from real tradeable symbols
      instead of hand-typing them, and any symbol the broker offers is a
      valid target, not just the three in `configs/app.yaml`.
- [ ] Clarify in the UI (tooltip/help text) that a strategy's `symbols`
      list is independent from `configs/app.yaml: symbols` — generating a
      bot for a new symbol does not automatically make the engine trade it
      live; that's still the user-owned config per `CLAUDE.md`'s
      "Strategies & AI safety" rules (generated code/AI logic must never
      edit `risk.yaml` or route around limits — extend that same posture to
      `app.yaml`'s trading-symbol list: UI can *suggest* adding a symbol
      there, but the actual toggle should be an explicit, separate,
      human-confirmed action, not implicit in strategy generation).
- [ ] **Duplicate a bot:** add `POST /strategies/versions/{version_id}/duplicate`
      in `backend/src/strategies/api/routes.py`, backed by a new method on
      `StrategyVersionService` (`backend/src/strategies/application/versioning.py`)
      that clones the version's code + spec into a **new strategy family**
      (new `name`, `version=1`, `parent_version_id=None`, fresh `id`,
      `source="manual"` or a new `"duplicated"` `CodeSource` variant) rather
      than a new version of the same family — duplicating is for
      forking/retargeting (e.g. same logic, different symbol), not
      superseding. Re-run sandbox validation on the clone before persisting.
  - [ ] Optionally accept a `symbols` override in the duplicate request body
        so "duplicate this bot for a different symbol" is a single action.
  - [ ] Frontend: add a "Duplicate" button next to each row in
        `StrategyVersionList.tsx` and on `StrategyVersionDetail.tsx`,
        opening a small form (new name + symbol picker) before calling the
        new endpoint, then routing to the new version's detail page.
- [ ] **Rename a bot:** add `PATCH /strategies/versions/{version_id}` (or a
      dedicated `/rename` endpoint) to update the display `name` without
      breaking the existing version chain — decide whether rename applies
      to the whole family (all versions share `name` today, per
      `StrategyVersionOut.name` description "versions of the same strategy
      share it," `schemas.py:33`) or just relabels going forward. Renaming
      the whole family in place (updating stored records, not the
      generated file's internal identifiers) is the simplest option
      consistent with current data model — confirm this doesn't collide
      with `file_path`/`code_hash` uniqueness assumptions in
      `strategies/adapters/repository.py`.
  - [ ] Frontend: inline-editable name field (pencil icon) on
        `StrategyVersionDetail.tsx` and in the `StrategyDraftDetail.tsx`
        header, wired to the new endpoint.
- [ ] **Tests** (per `CLAUDE.md` quality bar — "every broker-affecting
      change requires unit tests plus a paper-mode integration test," and
      this touches strategy activation which is adjacent):
  - [ ] Unit tests for `duplicate_version` / rename in
        `backend/tests/unit/strategies/` (mirror existing versioning test
        patterns).
  - [ ] Confirm duplicated/renamed versions still round-trip through
        `activate_version` (sandbox re-validation) correctly.
- [ ] **List/manage UI:** since bots are no longer implicitly tied to 3
      symbols, `StrategyDraftList.tsx` / `StrategyVersionList.tsx` should
      show the symbol(s) per bot as a visible column/badge (currently only
      name/status/created are listed, `StrategyDraftList.tsx:34-39`) so a
      growing list of per-symbol bots stays scannable — this is the "good
      UX/UI design" ask; treat it as a real design pass (grouping by
      symbol or family, search/filter by symbol) once duplicate/rename
      exist and the list is expected to grow past 3 entries.

---

## Suggested order

1. §2 (last-symbol persistence) and §3 (viewport fit on switch) — same
   file (`ChartPanel.tsx`/`page.tsx`), independent bugs, low risk, do
   together.
2. §4 (favorites, remove hardcoded defaults) — builds directly on §2's
   persistence pattern.
3. §1 (attribution logo) — trivial, one-line config change, do whenever.
4. §5 (bot symbol picker, duplicate, rename) — largest scope, spans
   backend (new endpoints/service methods) and frontend; do last and treat
   as its own mini design pass per the "good UX/UI" ask.

Before declaring any part done: `make lint-frontend && make build-frontend`
for frontend changes; `uv run ruff check src tests && uv run pytest` from
`backend/` for backend changes (per `CLAUDE.md`).
