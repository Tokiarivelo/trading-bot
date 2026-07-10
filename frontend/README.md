> 🇫🇷 Version française : [README.fr.md](README.fr.md)

# Frontend — Next.js + Tailwind CSS + TypeScript

The trading bot UI: TradingView-style chart (`lightweight-charts`), bot
controls, journal, PDF upload, and AI reports. Project-wide rules live in the
root `CLAUDE.md`; the full design is in `IMPLEMENTATION_PLAN.md`.

## Stack

- **Next.js** (App Router, Turbopack) — routes and layout in `src/app/`
- **Tailwind CSS v4** — design tokens in the `@theme` block of
  `src/app/globals.css`; no raw hex in components, no separate CSS files
- **TypeScript** (pinned to 6.x until Next.js supports TS 7)
- **oxlint** for linting
- **lightweight-charts** for all charting
- **pnpm** as the only package manager (version pinned via `packageManager`
  in `package.json`; pnpm auto-switches to it) — never npm or yarn

Always install the latest stable versions when adding dependencies
(`pnpm view <pkg> version` to check).

## Layout

```
src/
├── app/          ← Next.js App Router: layout, pages, globals.css
├── features/     ← one folder per feature, mirrors backend modules
│   └── chart/
└── shared/
    └── api/      ← REST client (client.ts) + WebSocket client (ws.ts)
```

## Backend connectivity

- REST: proxied under `/api` via rewrites in `next.config.ts`
  (`BACKEND_URL`, default `http://127.0.0.1:8000`).
- WebSocket: Next rewrites don't proxy WS, so `src/shared/api/ws.ts` connects
  to the backend directly (`NEXT_PUBLIC_WS_URL`, default `ws://127.0.0.1:8000`).
- API types come from the backend OpenAPI schema — don't hand-write duplicates.

## Commands

Prefer the root `Makefile` (`make dev-frontend`, `make lint-frontend`,
`make build-frontend`, `make check`). Direct equivalents from `frontend/`:

```bash
pnpm install     # deps (also: make setup-frontend from the repo root)
pnpm dev         # dev server on http://localhost:3000
pnpm lint        # oxlint
pnpm build       # production build (also type-checks) — run before declaring done
pnpm start       # serve the production build
```
