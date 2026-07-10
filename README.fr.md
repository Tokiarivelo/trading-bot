> 🇬🇧 English version: [README.md](README.md)

# Bot de Trading IA — XAUUSD / XAGUSD / BTCUSD

Un bot de trading connecté à MT5 et assisté par IA. Entrées en M5 avec
confirmation sur les unités de temps supérieures, graphique façon TradingView,
stratégies générées à partir de documents PDF par une IA (Claude ou Ollama),
et auto-amélioration automatique toutes les 10 trades.

**Conception complète & feuille de route :** voir
[`IMPLEMENTATION_PLAN.fr.md`](IMPLEMENTATION_PLAN.fr.md).

## Organisation du dépôt

| Chemin | Contenu |
|--------|---------|
| `backend/` | Backend FastAPI — moteur, stratégies, couche IA, journal (modules hexagonaux) |
| `frontend/` | UI Next.js + Tailwind CSS + TypeScript — graphique, contrôles du bot, upload PDF, rapports |
| `gateway/` | Service passerelle MT5 — le **seul** code touchant MetaTrader5 (tourne sous Windows/Wine/VPS, voir `gateway/README.fr.md`) |
| `configs/` | Configuration d'exécution (symboles, plafonds de risque, fournisseurs IA, actualités) |
| `Makefile` | Commandes de dev canoniques — setup, serveurs de dev, vérifications, BDD, docker (`make help`) |
| `.claude/` | Skills et réglages Claude Code |

## Démarrage rapide (développement)

Tout passe par le `Makefile` racine — lancez `make help` pour la liste complète.

```bash
make setup             # backend (uv sync) + frontend (pnpm install) + .env
make dev               # backend sur :8000 + frontend sur :3000, Ctrl-C arrête les deux

# ou individuellement :
make dev-backend       # FastAPI avec rechargement auto — http://localhost:8000
make dev-frontend      # serveur de dev Next.js — http://localhost:3000

# Passerelle — nécessite un terminal MT5 ; voir gateway/README.fr.md :
#   Wine sous Linux pour le développement, VPS Windows recommandé pour le
#   trading réel 24h/24
```

Sous le capot : le backend est en Python 3.12 via `uv`, le frontend en Next.js
via `pnpm` (version épinglée dans `frontend/package.json`).

## Vérifications

```bash
make check             # lint (ruff + oxlint) + tests backend + build frontend
```

Portes individuelles : `make lint`, `make test`, `make build-frontend` — voir
`make help`.

## Modèle de sécurité (à ne jamais affaiblir)

- Tout démarre en **mode papier** (`configs/app.yaml : mode: paper`).
- Les plafonds de risque vivent dans `configs/risk.yaml` et appartiennent à
  l'utilisateur — l'IA et le code généré ne les modifient jamais.
- Les stratégies générées par IA tournent en sandbox : pas d'E/S, pas de
  réseau, pas d'accès au courtier.
- Coupe-circuits au niveau du moteur : limite de perte journalière, pause
  après pertes consécutives, bouton d'arrêt d'urgence (kill switch).
