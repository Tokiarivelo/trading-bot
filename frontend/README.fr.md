> 🇬🇧 English version: [README.md](README.md)

# Frontend — Next.js + Tailwind CSS + TypeScript

L'interface du bot de trading : graphique façon TradingView
(`lightweight-charts`), contrôles du bot, journal, upload de PDF et rapports
IA. Les règles du projet vivent dans le `CLAUDE.md` racine ; la conception
complète est dans `IMPLEMENTATION_PLAN.fr.md`.

## Stack

- **Next.js** (App Router, Turbopack) — routes et layout dans `src/app/`
- **Tailwind CSS v4** — design tokens dans le bloc `@theme` de
  `src/app/globals.css` ; pas de hex brut dans les composants, pas de fichiers
  CSS séparés
- **TypeScript** (épinglé en 6.x jusqu'à ce que Next.js supporte TS 7)
- **oxlint** pour le lint
- **lightweight-charts** pour tous les graphiques
- **pnpm** comme unique gestionnaire de paquets (version épinglée via
  `packageManager` dans `package.json` ; pnpm bascule automatiquement) —
  jamais npm ni yarn

Toujours installer les dernières versions stables lors de l'ajout de
dépendances (`pnpm view <pkg> version` pour vérifier).

## Organisation

```
src/
├── app/          ← App Router Next.js : layout, pages, globals.css
├── features/     ← un dossier par fonctionnalité, miroir des modules backend
│   └── chart/
└── shared/
    └── api/      ← client REST (client.ts) + client WebSocket (ws.ts)
```

## Connexion au backend

- REST : proxifié sous `/api` via les rewrites de `next.config.ts`
  (`BACKEND_URL`, par défaut `http://127.0.0.1:8000`).
- Socket.IO : les rewrites Next ne proxifient pas les WS, donc
  `src/shared/api/ws.ts` se connecte directement au backend
  (`NEXT_PUBLIC_WS_URL`, par défaut `http://127.0.0.1:8000`).
- Les types d'API viennent du schéma OpenAPI du backend — ne pas écrire de
  doublons à la main.

## Commandes

Préférez le `Makefile` racine (`make dev-frontend`, `make lint-frontend`,
`make build-frontend`, `make check`). Équivalents directs depuis `frontend/` :

```bash
pnpm install     # dépendances (aussi : make setup-frontend depuis la racine)
pnpm dev         # serveur de dev sur http://localhost:3000
pnpm lint        # oxlint
pnpm build       # build de production (avec vérification des types) — à lancer avant de déclarer terminé
pnpm start       # sert le build de production
```
