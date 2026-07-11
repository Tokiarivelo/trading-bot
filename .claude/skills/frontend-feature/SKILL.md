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
  `frontend/src/app/globals.css` (`bg`, `panel`, `line`, `ink`, `ink-muted`,
  `accent`, `ok`, `err`) — extend the theme there; never raw hex in components,
  never separate CSS files.
- All charting via `lightweight-charts` only.
- API types come from the backend OpenAPI schema — don't hand-write duplicates.
  Every backend route is fully documented (response_model, summary,
  description, typed errors); browse it live at `http://localhost:8000/docs`
  or dump it with `make openapi` before wiring a new API call.

## Steps
1. Create/extend the feature folder `frontend/src/features/<feature>/` — the
   name mirrors the backend module it talks to (chart, account, bot-control,
   strategies, journal, ...).
2. Components that use hooks, browser APIs, or `lightweight-charts` need
   `"use client"`; keep server components the default otherwise.
3. Talk to the backend through `src/shared/api/client.ts` (REST, proxied under
   `/api` via `next.config.ts` rewrites) and `src/shared/api/ws.ts`
   (WebSocket — connects to the backend directly; Next rewrites don't proxy WS).
4. If a new dependency is needed, install the **latest stable** version with
   **pnpm only** (`pnpm view <pkg> version` first, then `pnpm add <pkg>`).
   Pin below latest only for a real incompatibility and say why in the commit.
5. Wire the feature into the page/layout under `frontend/src/app/`.
6. Validate: `make lint-frontend` and `make build-frontend` from the repo root
   (or `pnpm lint` / `pnpm build` from `frontend/`) — both must pass before
   the task is done.

## Must never
- Reintroduce Vite artifacts (`vite.config.ts`, `index.html`, `main.tsx`).
- Add another charting or styling library.
- Hardcode backend URLs in components (use the shared api/ws clients).
- Touch backend code, `configs/risk.yaml`, or `backend/src/engine/`.
