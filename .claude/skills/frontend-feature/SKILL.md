---
name: frontend-feature
description: Scaffold or extend a frontend feature the project way — Next.js App Router + Tailwind CSS, feature folder mirroring a backend module, typed API client usage, latest stable packages, lint + build validation.
---

# Frontend Feature

Build the frontend feature described in `$ARGUMENTS` following the project's
frontend stack: **Next.js (App Router) + Tailwind CSS + TypeScript**.

## Stack rules (from CLAUDE.md — binding)
- Next.js App Router only: routes/layout in `frontend/src/app/`. No Vite, no
  CRA, no pages router, no CSS-in-JS.
- Tailwind utilities only. Design tokens live in the `@theme` block of
  `frontend/src/app/globals.css`: `bg`, `panel`, `line`, `ink`, `ink-muted`,
  `accent`, `ok`, `err`, plus `buy`/`sell` (used for position entry lines on
  the chart — deliberately distinct from `ok`/`err`, which are reserved for
  TP/SL). Extend the theme there; never raw hex in components, never a
  separate CSS file.
- All charting via `lightweight-charts` only (current: v5). Drawing tools use
  the `lightweight-charts-drawing` package on top of it (see
  `features/chart/ChartPanel.tsx` / `DrawingToolbar.tsx`) — don't add a
  second charting or drawing library for a new chart-adjacent feature.
- API types are **hand-maintained, not code-generated** — there is no
  openapi-typescript step in this repo. `src/shared/api/client.ts` is one
  ~1100-line file holding every `export interface` (mirroring a backend
  Pydantic schema field-for-field) plus its typed fetch wrapper function.
  Every backend route is fully documented (`response_model`, `summary`,
  `description`, typed errors per CLAUDE.md's OpenAPI rules) — check
  `http://localhost:8000/docs` or `make openapi` for the exact current shape
  before hand-writing the matching interface, and add both the interface and
  the fetch function to `client.ts` alongside the existing ones for that
  module rather than starting a new per-feature types file.

## Steps
1. Create/extend the feature folder `frontend/src/features/<feature>/` — the
   name mirrors the backend module it talks to (chart, strategies, backtest,
   bot-control, journal → history, ...). Layout is flat: PascalCase
   component files and `use*.ts` hook files sit directly in the folder, no
   nested `components/`/`hooks/` subfolders (see `features/strategies/` or
   `features/backtest/` for the pattern).
2. Components that use hooks, browser APIs, or `lightweight-charts` need
   `"use client"`; keep server components the default otherwise.
3. Talk to the backend through `src/shared/api/client.ts` (REST, proxied under
   `/api` via `next.config.ts` rewrites — the frontend never hardcodes the
   backend URL) and `src/shared/api/ws.ts` (WebSocket — connects to the
   backend directly on its real port; Next rewrites don't proxy WS). Auth is
   a bearer token from `getToken()`/`setToken()` in `client.ts`
   (`localStorage`, not cookies) — reuse those helpers rather than reading
   `localStorage` directly, and let the existing `UNAUTHORIZED_EVENT` /
   `ApiError` handling do its job on a 401 instead of adding a new one.
4. If a new dependency is needed, install the **latest stable** version with
   **pnpm only** (`pnpm view <pkg> version` first, then `pnpm add <pkg>`).
   Pin below latest only for a real incompatibility and say why in the
   commit — e.g. `typescript` is currently pinned to `^6.0.3` because Next.js
   doesn't yet support TS 7; don't "fix" that pin without checking first.
5. Wire the feature into the page/layout under `frontend/src/app/` — route
   segments there mirror top-level features (`app/strategies/`,
   `app/backtest/[id]/`, `app/ai-reports/proposals/`, ...).
6. Validate: `make lint-frontend` and `make build-frontend` from the repo root
   (or `pnpm lint` / `pnpm build` from `frontend/`) — both must pass before
   the task is done. `build-frontend` also runs TypeScript type-checking, so
   it's the real gate for a `client.ts` interface drifting from the backend
   schema.

## Must never
- Reintroduce Vite artifacts (`vite.config.ts`, `index.html`, `main.tsx`).
- Add another charting, drawing, or styling library.
- Hardcode backend URLs in components (use the shared api/ws clients).
- Hand-write a duplicate types file instead of extending `client.ts`.
- Touch backend code, `configs/risk.yaml`, or `backend/src/engine/`.
