> 🇬🇧 English version: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
> *(la version anglaise fait foi ; tenez les deux à jour ensemble)*

# Bot de Trading IA — Plan d'implémentation

> Un bot de trading connecté à MT5, assisté par IA, spécialisé sur **XAUUSD, XAGUSD, BTCUSD**.
> Entrées toujours sur l'unité de temps **5 minutes**, confirmées par les unités supérieures.
> Les stratégies sont générées à partir de **documents PDF analysés par une IA** (Claude ou Ollama),
> et le bot **s'auto-améliore toutes les 10 trades** sur la base d'une analyse IA de ses résultats.

---

## Table des matières

1. [Vision & fonctionnalités clés](#1-vision--fonctionnalités-clés)
2. [Contrainte de plateforme critique (à lire d'abord)](#2-contrainte-de-plateforme-critique-à-lire-dabord)
3. [Stack technologique](#3-stack-technologique)
4. [Architecture globale](#4-architecture-globale)
5. [Dépôt & structure des dossiers](#5-dépôt--structure-des-dossiers)
6. [Conception module par module](#6-conception-module-par-module)
7. [Spécification de la logique de trading](#7-spécification-de-la-logique-de-trading)
8. [Couche IA : PDF → stratégie, et boucle d'auto-amélioration](#8-couche-ia--pdf--stratégie-et-boucle-dauto-amélioration)
9. [Règles & skills Claude Code](#9-règles--skills-claude-code)
10. [Plan de configuration complet](#10-plan-de-configuration-complet)
11. [Sécurité](#11-sécurité)
12. [Checklist d'implémentation (phases)](#12-checklist-dimplémentation-phases)
13. [Stratégie de test & validation](#13-stratégie-de-test--validation)
14. [Avertissement sur les risques](#14-avertissement-sur-les-risques)

---

## 1. Vision & fonctionnalités clés

| # | Fonctionnalité | Résumé |
|---|----------------|--------|
| F1 | Flux de données MT5 | Ticks en direct + bougies OHLCV tirés de MetaTrader 5 |
| F2 | Graphique façon TradingView | UI web affichant bougies, indicateurs et trades exécutés |
| F3 | Trading automatique | Le bot ouvre **et** ferme les positions automatiquement |
| F4 | PDF → Stratégie | Importer un PDF ; l'IA (API Claude ou Ollama local) extrait la méthode et génère le code de stratégie |
| F5 | Auto-amélioration | Toutes les **10 trades clôturées**, l'IA passe en revue les trades + les données de marché au moment du trade, et améliore le code/les paramètres si besoin |
| F6 | Multi-unités de temps | Entrées toujours en **M5** ; H1/H4/D1 consultées pour confirmation |
| F7 | Marqueurs de trades | Chaque position (entrée, SL, TP, sortie) est dessinée sur le graphique |
| F8 | Système de skills | Un skill « trading normal » + des skills spéciaux pour les news à forte volatilité (NFP, CPI, FOMC…) |
| F9 | Symboles | XAUUSD (principal), XAGUSD, BTCUSD |
| F10 | Prise en compte du spread | Spread du courtier mesuré en direct et intégré aux décisions d'entrée/SL/TP |
| F11 | Connexion au compte | L'utilisateur saisit login / mot de passe / serveur MT5 dans l'UI de l'app |

---

## 2. Contrainte de plateforme critique (à lire d'abord)

Le paquet Python officiel `MetaTrader5` **ne tourne que sous Windows**, car il
dialogue avec un terminal MT5 de bureau en cours d'exécution. Vous êtes sous
Linux, donc choisissez :

| Option | Description | Recommandation |
|--------|-------------|----------------|
| **A. Wine sous Linux** | Terminal MT5 + Python Windows sous Wine ; le *service connecteur MT5* du bot tourne dans Wine et expose une API locale (gRPC/HTTP) au reste de l'app qui tourne nativement sous Linux | ✅ Bien pour développer sur votre machine |
| **B. VPS Windows** | MT5 + service connecteur sur un petit VPS Windows ; le reste de l'app n'importe où | ✅ Idéal pour le trading réel 24h/24 (latence faible, pas de veille) |
| **C. Pont tiers** | Bibliothèques comme `mt5linux` (encapsule l'option A) ou API REST de courtiers | ⚠️ Pratique mais ajoute une couche de dépendance |

**Décision architecturale qui règle le problème proprement :** isoler *tout*
ce qui est spécifique à MT5 derrière un petit **service passerelle MT5** avec
une API réseau. Le reste du système n'importe jamais `MetaTrader5`
directement. Le problème de plateforme devient un détail de déploiement, pas
un problème de code, et on peut brancher une passerelle simulée pour le
backtest.

---

## 3. Stack technologique

| Couche | Choix | Pourquoi |
|--------|-------|----------|
| Langage (backend/bot) | **Python 3.12+** | Paquet MT5, SDK IA, écosystème pandas/numpy |
| Passerelle MT5 | paquet pip `MetaTrader5` + **FastAPI** (tourne sous Wine/Windows) | Seul pont officiellement supporté |
| API backend | **FastAPI** + WebSockets | Async, typé, streaming WS facile vers le graphique |
| Frontend | **Next.js (App Router) + Tailwind CSS + TypeScript** | Framework React de production, styles utilitaires, boucle de dev rapide (Turbopack) |
| Graphiques | **`lightweight-charts`** (la bibliothèque open source de TradingView) | Littéralement le look & feel TradingView ; marqueurs, lignes de prix, overlays |
| Base de données | **SQLite** (départ) → PostgreSQL (plus tard) | Trades, versions de stratégies, analyses IA, config |
| IA — cloud | **API Claude** (`claude-sonnet-5` pour analyse/génération de code, `claude-haiku-4-5` pour les vérifications de routine) | Meilleure génération de code & analyse de documents |
| IA — local | **Ollama** (p. ex. `llama3.1`, `qwen2.5-coder`) | Repli gratuit/hors-ligne, au choix de l'utilisateur |
| Analyse de PDF | `pymupdf` (texte + images) → IA | Extraction robuste avant que l'IA ne voie le contenu |
| Planification de tâches | `APScheduler` | Ticks de la boucle de trading, rafraîchissement du calendrier des news |
| Calendrier des news | Scrape Forex Factory / investing.com ou API `finnhub`/`fmp` | Détecter les fenêtres NFP/CPI/FOMC |
| Secrets | Trousseau OS (paquet `keyring`) + chiffrement au repos (`cryptography`/Fernet) | Identifiants MT5 jamais en clair |
| Packaging | `docker-compose` pour les services Linux ; passerelle documentée à part | Reproductible |
| Outillage de dev | `uv` (backend), `pnpm` (frontend), `Makefile` racine comme point d'entrée | Une commande par tâche, politique toujours-à-jour |

---

## 4. Architecture globale

```
┌─────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (Next.js)                        │
│  Graphique (lightweight-charts) · Marqueurs de trades ·            │
│  Contrôles du bot · Upload PDF · Connexion MT5 ·                    │
│  Visualiseur de stratégies & analyses                               │
└───────────────▲─────────────────────────────▲──────────────────────┘
                │ REST (commandes/config)     │ WebSocket (bougies, ticks,
                │                             │  positions, événements bot)
┌───────────────┴─────────────────────────────┴──────────────────────┐
│                        API BACKEND (FastAPI)                       │
│   auth · config · gestion stratégies · données graphique ·         │
│   contrôle du bot                                                   │
└──────┬──────────────┬──────────────┬──────────────┬────────────────┘
       │              │              │              │
┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐ ┌─────▼──────────────┐
│ MOTEUR BOT │ │ COUCHE IA  │ │ SERVICE NEWS│ │  PERSISTANCE (BDD) │
│ exécution  │ │ pdf→méthode│ │ calendrier  │ │ trades · versions  │
│ stratégies,│ │ revue 10   │ │ détection   │ │ analyses · configs │
│ gestion du │ │ trades,    │ │ NFP/CPI,    │ │                    │
│ risque,    │ │ refonte du │ │ bascule de  │ │                    │
│ skills     │ │ code       │ │ skill       │ │                    │
└──────┬─────┘ └────────────┘ └─────────────┘ └────────────────────┘
       │  gRPC/HTTP (frontière réseau — règle le problème Linux)
┌──────▼──────────────────────────────────────────────────────────────┐
│              PASSERELLE MT5 (Windows / Wine / VPS)                  │
│  login · bougies · ticks · spread · envoi/modif/clôture d'ordres   │
└──────────────────────────────▲──────────────────────────────────────┘
                               │
                        Terminal MetaTrader 5 → Courtier
```

**Principes clés**

- **Hexagonal (ports & adaptateurs) par module** : chaque module expose des
  interfaces (`ports/`), avec des implémentations concrètes (`adapters/`)
  interchangeables (MT5 réel ↔ simulateur de backtest, Claude ↔ Ollama).
- **Le bot n'appelle jamais MT5 directement** — uniquement via l'interface
  `BrokerPort`.
- **Les stratégies sont des artefacts données + code**, versionnés en BDD et
  sur disque, pour que la boucle d'amélioration IA puisse diff/rollback.
- **Cœur événementiel** : le moteur émet des événements (`CandleClosed`,
  `PositionOpened`, `PositionClosed`, `TenTradesCompleted`,
  `NewsWindowEntered`) auxquels les autres modules s'abonnent.

---

## 5. Dépôt & structure des dossiers

Chaque dossier de premier niveau sous `backend/src/` est un **module
autonome** avec sa propre mini clean-architecture : `domain/` (logique pure,
sans E/S), `application/` (cas d'usage), `ports/` (interfaces), `adapters/`
(implémentations), `api/` (routes FastAPI si le module en a).

```
trading-bot/
├── IMPLEMENTATION_PLAN.md            ← ce document (version anglaise)
├── README.md
├── docker-compose.yml
├── .env.example
├── CLAUDE.md                         ← règles projet Claude Code (voir §9)
├── .claude/
│   ├── settings.json                 ← permissions & hooks pour Claude Code
│   └── skills/                       ← skills Claude Code (voir §9)
│       ├── new-strategy/SKILL.md
│       ├── refine-bot/SKILL.md
│       ├── backtest/SKILL.md
│       ├── trade-review/SKILL.md
│       └── news-skill-gen/SKILL.md
│
├── gateway/                          ← PASSERELLE MT5 (tourne sous Windows/Wine)
│   ├── pyproject.toml
│   ├── src/gateway/
│   │   ├── main.py                   ← app FastAPI
│   │   ├── mt5_client.py             ← le SEUL fichier qui importe MetaTrader5
│   │   ├── routes/
│   │   │   ├── auth.py               ← login/logout du compte MT5
│   │   │   ├── market_data.py        ← bougies, ticks, spread, infos symbole
│   │   │   └── trading.py            ← ouverture/modif/clôture d'ordres, positions
│   │   └── schemas.py                ← modèles pydantic partagés sur le réseau
│   └── README.md                     ← instructions d'installation Wine/VPS
│
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py                   ← point d'entrée FastAPI, câble les modules
│   │   ├── container.py              ← injection de dépendances / racine de composition
│   │   │
│   │   ├── shared/                   ← transverse, aucune logique métier
│   │   │   ├── events/               ← bus d'événements (pub/sub), définitions
│   │   │   ├── config/               ← chargeur de réglages (pydantic-settings)
│   │   │   ├── db/                   ← moteur SQLAlchemy, migrations (alembic)
│   │   │   └── logging/
│   │   │
│   │   ├── market_data/              ← F1 : bougies, ticks, spread
│   │   │   ├── domain/               ← modèles Candle, Tick, Timeframe, Spread
│   │   │   ├── application/          ← cas d'usage stream_candles, get_history
│   │   │   ├── ports/                ← MarketDataPort
│   │   │   ├── adapters/
│   │   │   │   ├── mt5_gateway.py    ← appelle l'API HTTP de la passerelle
│   │   │   │   └── replay.py         ← rejeu historique pour les backtests
│   │   │   └── api/                  ← endpoints REST + WS pour le graphique
│   │   │
│   │   ├── broker/                   ← F3, F10, F11 : exécution des ordres
│   │   │   ├── domain/               ← Order, Position, ExecutionResult, SpreadModel
│   │   │   ├── application/          ← open_position, close_position, apply_spread_rules
│   │   │   ├── ports/                ← BrokerPort, AccountPort
│   │   │   ├── adapters/
│   │   │   │   ├── mt5_gateway.py
│   │   │   │   └── paper.py          ← simulateur de trading papier (même interface)
│   │   │   └── api/                  ← endpoint de connexion aux identifiants MT5
│   │   │
│   │   ├── engine/                   ← F3, F6 : le cœur battant du bot
│   │   │   ├── domain/               ← Signal, TradePlan, RiskParams, EngineState
│   │   │   ├── application/
│   │   │   │   ├── trade_loop.py     ← à la clôture M5 → évaluer → agir
│   │   │   │   ├── mtf_confirm.py    ← confirmation sur unités supérieures
│   │   │   │   ├── risk_manager.py   ← taille de lot, drawdown max, plafond de perte journalière
│   │   │   │   └── position_manager.py ← trailing, passage à BE, clôture auto
│   │   │   ├── ports/                ← StrategyPort, SkillSelectorPort
│   │   │   └── adapters/
│   │   │
│   │   ├── strategies/               ← F4 : artefacts de stratégies (générés par IA)
│   │   │   ├── domain/               ← modèles Strategy, StrategyVersion, Rule
│   │   │   ├── application/          ← charger, valider, activer, rollback
│   │   │   ├── registry.py           ← découvre les fichiers de stratégies
│   │   │   ├── sandbox.py            ← wrapper d'exécution sûre (surface d'API restreinte)
│   │   │   └── generated/            ← le code de stratégie écrit par l'IA vit ICI
│   │   │       ├── xauusd_breakout_v1.py
│   │   │       └── ...               ← chaque fichier versionné + hash suivi en BDD
│   │   │
│   │   ├── skills/                   ← F8 : skills de trading du BOT (≠ skills Claude Code)
│   │   │   ├── domain/               ← modèles Skill, ActivationCondition
│   │   │   ├── application/          ← skill_selector (normal vs news vs par symbole)
│   │   │   ├── normal/               ← comportement de trading par défaut par symbole
│   │   │   │   ├── xauusd.yaml
│   │   │   │   ├── xagusd.yaml
│   │   │   │   └── btcusd.yaml
│   │   │   └── news/                 ← playbooks haute volatilité
│   │   │       ├── nfp.yaml
│   │   │       ├── cpi.yaml
│   │   │       ├── fomc.yaml
│   │   │       └── generic_high_impact.yaml
│   │   │
│   │   ├── ai/                       ← F4, F5 : toute l'interaction IA
│   │   │   ├── domain/               ← AnalysisReport, RefinementProposal, StrategySpec
│   │   │   ├── application/
│   │   │   │   ├── pdf_to_strategy.py    ← PDF → StrategySpec → génération de code
│   │   │   │   ├── ten_trade_review.py   ← déclenché par l'événement TenTradesCompleted
│   │   │   │   └── code_refiner.py       ← applique les diffs proposés par l'IA avec validation
│   │   │   ├── ports/                ← LLMPort (indépendant du fournisseur)
│   │   │   ├── adapters/
│   │   │   │   ├── claude.py         ← SDK Anthropic
│   │   │   │   └── ollama.py         ← modèles locaux
│   │   │   ├── prompts/              ← templates de prompts versionnés (jinja2)
│   │   │   │   ├── extract_method_from_pdf.md
│   │   │   │   ├── generate_strategy_code.md
│   │   │   │   ├── review_ten_trades.md
│   │   │   │   └── refine_strategy_code.md
│   │   │   └── api/                  ← endpoint d'upload PDF, API du visualiseur d'analyses
│   │   │
│   │   ├── news/                     ← F8 : calendrier économique
│   │   │   ├── domain/               ← NewsEvent, ImpactLevel, NewsWindow
│   │   │   ├── application/          ← fetch_calendar, detect_active_window
│   │   │   ├── ports/ · adapters/    ← adaptateurs forexfactory / finnhub
│   │   │   └── api/
│   │   │
│   │   ├── journal/                  ← F5, F7 : historique des trades & capture de contexte
│   │   │   ├── domain/               ← TradeRecord (entrée/sortie/SL/TP/spread/skill/
│   │   │   │                            version de stratégie/instantanés M5+HTF à l'entrée)
│   │   │   ├── application/          ← record_trade, snapshot_market_context,
│   │   │   │                            get_last_n_trades
│   │   │   └── api/                  ← alimente les marqueurs du graphique & la revue IA
│   │   │
│   │   └── backtest/                 ← validation avant toute mise en réel
│   │       ├── application/          ← run_backtest(strategy, period, symbol)
│   │       ├── adapters/             ← utilise market_data.replay + broker.paper
│   │       └── reports/
│   │
│   └── tests/
│       ├── unit/                     ← miroir de la structure des modules src/
│       ├── integration/
│       └── fixtures/                 ← données de bougies enregistrées pour tests déterministes
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── app/                      ← App Router Next.js : layout, pages, globals.css
│   │   ├── features/                 ← un dossier par fonctionnalité (miroir du backend)
│   │   │   ├── chart/                ← wrapper lightweight-charts, indicateurs,
│   │   │   │                            marqueurs de trades, sélecteur d'unité de temps
│   │   │   ├── account/              ← formulaire de connexion MT5, état de connexion
│   │   │   ├── bot-control/          ← start/stop, mode (réel/papier), curseur de risque
│   │   │   ├── strategies/           ← upload PDF, liste des stratégies, vue diff des versions
│   │   │   ├── journal/              ← table des trades, détail par trade, statistiques
│   │   │   ├── ai-reports/           ← analyses des 10 trades, historique des améliorations
│   │   │   └── news/                 ← événements à venir, bannière de fenêtre de news active
│   │   ├── shared/                   ← client api, client ws, kit UI, hooks
│   │   └── types/                    ← générés depuis le schéma OpenAPI du backend
│   └── ...
│
└── configs/                          ← configuration d'exécution (voir §10)
    ├── app.yaml
    ├── symbols/
    │   ├── xauusd.yaml
    │   ├── xagusd.yaml
    │   └── btcusd.yaml
    ├── risk.yaml
    ├── ai.yaml
    └── news.yaml
```

---

## 6. Conception module par module

### 6.1 `gateway/` — Passerelle MT5
- Fine, bête, stable. **Aucune logique métier.** Endpoints : `POST /login`,
  `GET /candles`, `GET /tick`, `GET /symbol_info` (avec spread en direct),
  `POST /order`, `POST /close`, `GET /positions`, `WS /ticks`.
- Retourne des faits bruts du courtier ; toutes les décisions se prennent
  dans le backend.
- Endpoint de santé pour que le backend détecte les déconnexions
  passerelle/terminal et mette le trading en pause.

### 6.2 `market_data/`
- Diffuse les bougies M5/H1/H4/D1 ; met en cache l'historique récent en
  mémoire ; persiste en BDD pour les backtests et les instantanés IA.
- Émet les événements `CandleClosed(symbol, timeframe)` — l'horloge du moteur.

### 6.3 `broker/`
- `SpreadModel` : moyenne glissante + spread en direct par symbole. Règles
  (depuis la config) : sauter l'entrée si `spread > max_spread_points` ;
  élargir le SL du spread ; exiger `expected_move ≥ k × spread` pour qu'un
  trade vaille la peine.
- L'adaptateur `paper.py` simule les exécutions **spread compris**, pour que
  les résultats papier soient honnêtes.

### 6.4 `engine/`
- Une boucle par symbole. À `CandleClosed(M5)` :
  1. Le sélecteur de skill choisit le skill actif (normal vs fenêtre de news).
  2. La stratégie active évalue → `Signal | None`.
  3. Si signal : `mtf_confirm` vérifie les unités supérieures (selon la spec).
  4. `risk_manager` calcule le lot (risque % fixe), vérifie les plafonds
     (perte journalière, positions simultanées max, spread max).
  5. `broker.open_position` → `journal.record_trade` (avec instantané complet
     du contexte de marché).
- `position_manager` tourne à chaque tick/bougie : SL au breakeven, trailing,
  sortie temporelle, clôture forcée selon les règles du skill (p. ex. flat
  2 min avant le NFP).

### 6.5 `strategies/`
- Une stratégie = un fichier Python implémentant une interface fixe :
  ```python
  class Strategy(Protocol):
      spec: StrategySpec            # symboles, UT utilisées, params, règles HTF
      def evaluate(self, ctx: MarketContext) -> Signal | None: ...
  ```
- `sandbox.py` : le code généré est importé dans un espace de noms restreint —
  il ne reçoit que `MarketContext` (bougies, indicateurs, spread) et retourne
  un `Signal`. **Il ne peut jamais toucher le courtier, le système de
  fichiers ni le réseau.** Le moteur est le seul composant qui exécute des
  trades.
- Chaque version est stockée avec : hash du fichier, version parente,
  l'analyse IA qui l'a produite, et les résultats de backtest. Rollback =
  déplacer le pointeur actif.

### 6.6 `skills/` (skills du bot — pas ceux de Claude Code)
- YAML déclaratif, interprété par le moteur :
  ```yaml
  # skills/news/nfp.yaml
  name: nfp
  activation:
    calendar_event: ["Non-Farm Payrolls"]
    window: { before_min: 30, after_min: 60 }
    symbols: [XAUUSD, XAGUSD]
  rules:
    pre_event:  { close_all: true, block_new_entries: true }
    post_event: { wait_candles_m5: 3, strategy_override: "news_breakout",
                  max_spread_points: 80, risk_multiplier: 0.5 }
  ```
- `skill_selector` résout la priorité : **skill news > skill normal du
  symbole > défaut global**.

### 6.7 `ai/`
- `LLMPort` avec deux adaptateurs (Claude / Ollama), sélectionnables dans
  `configs/ai.yaml` par tâche — p. ex. Claude pour la génération de code,
  Ollama pour les commentaires de routine.
- **Pipeline PDF** : `pymupdf` extrait texte+images → prompt
  `extract_method_from_pdf` → `StrategySpec` structurée (JSON : règles
  d'entrée, de sortie, UT, indicateurs, notes de risque) → l'utilisateur
  relit la spec dans l'UI → prompt `generate_strategy_code` → fichier dans
  `strategies/generated/` → **backtest obligatoire** → activation par
  l'utilisateur.
- **Revue des 10 trades** : `journal` émet `TenTradesCompleted` → collecte
  des 10 `TradeRecord` avec instantanés de bougies M5 + HTF autour de chaque
  trade → prompt `review_ten_trades` → `AnalysisReport` (ce qui a marché, ce
  qui a échoué, hypothèse) → éventuellement `RefinementProposal` (changement
  de paramètre ou diff de code) → **backtest automatique de la proposition ;
  appliquer seulement si elle bat la version courante ; toujours conserver
  l'ancienne version**. Un drapeau de config choisit `auto-apply` vs
  `ask-user`.

### 6.8 `journal/`
- La source de vérité unique pour F5 et F7. Chaque `TradeRecord` stocke tout
  ce dont l'IA aura besoin : version de stratégie, skill actif, spread à
  l'entrée, slippage, et fenêtres de bougies sérialisées (M5 ±50 bougies,
  H1 ±20) à l'entrée et à la sortie.
- API des marqueurs du graphique :
  `GET /journal/markers?symbol=&from=&to=` → le frontend dessine flèches
  d'entrée, lignes SL/TP, drapeaux de sortie.

### 6.9 `frontend/features/chart/`
- Série de chandeliers `lightweight-charts` + volume ; sélecteur d'unité de
  temps (M5 par défaut, H1/H4/D1 en lecture seule) ; overlays d'indicateurs
  définis par la spec de la stratégie active ; mises à jour en direct par
  WebSocket ; marqueurs de trades depuis le journal ; ombrage des fenêtres de
  news sur l'axe temporel.

---

## 7. Spécification de la logique de trading

### 7.1 Flux d'entrée (toujours M5)
```
La bougie M5 clôture
 └─ passerelle en vie ? compte connecté ? moteur activé ?      → sinon passer
 └─ fenêtre de news active ?  → appliquer les règles du skill news (peut tout bloquer)
 └─ strategy.evaluate(contexte M5) → Signal(dir, sl, tp, confiance) ?
 └─ confirmation HTF (selon la spec de la stratégie, p. ex.) :
     • la direction de tendance H1 est d'accord (pente EMA200 / structure)
     • H4 pas sur un S/R majeur contre le trade
     → tout veto ⇒ log « signal vetoed by HTF » et passer
 └─ vérification du spread : live_spread ≤ symbol.max_spread_points
     ET (tp_distance ≥ min_rr × (sl_distance + spread))
 └─ gestionnaire de risque : lot = solde_compte × risk_pct / valeur_distance_sl
     plafonds : max_open_positions, daily_loss_limit, max_trades_per_day
 └─ envoi de l'ordre (SL/TP ajustés du spread) → instantané dans le journal
```

### 7.2 Flux de sortie
- SL/TP durs toujours placés chez le courtier (jamais de stops mentaux).
- `position_manager` : SL au breakeven à +1R ; trailing optionnel selon la
  spec ; stop temporel (clôture après N bougies sans progression) ; mise à
  plat forcée avant les news à fort impact si le skill l'exige.

### 7.3 Gestion du spread (F10)
- Spread en direct via `symbol_info` à chaque évaluation.
- Les achats s'exécutent à l'ask / les ventes au bid — le simulateur papier
  doit modéliser cela à l'identique.
- Toutes les distances SL/TP sont validées contre le `stops_level` du
  courtier.
- `max_spread_points` par symbole (le spread du XAUUSD explose pendant les
  news — c'est le tueur n°1 des scalpeurs d'or en conditions réelles).

---

## 8. Couche IA : PDF → stratégie, et boucle d'auto-amélioration

### 8.1 Pipeline PDF → stratégie
```
Upload du PDF → extraction texte/images → LLM : extraire la StrategySpec (JSON)
   → L'UTILISATEUR RELIT la spec dans l'UI (édite/approuve)
   → LLM : générer le code de stratégie depuis la spec approuvée
   → validation statique (respect de l'interface, imports interdits, typage)
   → backtest automatique sur 6–12 mois de données
   → résultats montrés à l'utilisateur → activation (papier d'abord, puis réel)
```
Ne jamais sauter la relecture humaine de la spec — les PDF sont ambigus et la
spec est le contrat.

### 8.2 Boucle d'amélioration toutes les 10 trades
```
Événement TenTradesCompleted
   → constituer le dossier de revue : 10 TradeRecords + instantanés de marché
     + code courant + spec
   → LLM : review_ten_trades → AnalysisReport
       (taux de réussite, distribution des R, motif d'échec récurrent,
        corrélation session/news)
   → si le LLM propose une amélioration :
        changement de paramètres seulement → mettre à jour la spec, re-backtester
        changement de code                 → le LLM produit un diff → validation
                                             sandbox → re-backtest
   → politique d'application (configs/ai.yaml) :
        mode: "suggest"  → afficher dans l'UI, attendre l'approbation   ← DÉFAUT
        mode: "auto"     → appliquer seulement si le backtest s'améliore ≥ seuil
   → nouvelle StrategyVersion enregistrée ; l'ancienne conservée pour rollback
```

**Garde-fous (non négociables) :**
- Le code amélioré tourne dans le même sandbox avec la même API restreinte.
- Une amélioration ne peut jamais augmenter les plafonds de risque (risque %,
  limite de perte journalière : config appartenant à l'utilisateur, pas à la
  stratégie).
- Max 1 auto-amélioration par jour et par stratégie ; le coupe-circuit sur
  pertes consécutives (p. ex. 5 pertes → pause + notification) est au niveau
  du moteur et intouchable par l'IA.

---

## 9. Règles & skills Claude Code

Cette section concerne l'usage de **Claude Code comme copilote de
développement** sur ce dépôt (distinct des skills d'exécution du bot dans
`backend/src/skills/`).

### 9.1 `CLAUDE.md` (règles projet) — à la racine du dépôt
Contenu à inclure :
```markdown
# Règles projet
- Architecture : hexagonale par module. Logique métier dans domain/ et
  application/ UNIQUEMENT. Rien en dehors de gateway/src/gateway/mt5_client.py
  ne peut importer MetaTrader5.
- Les stratégies dans backend/src/strategies/generated/ implémentent le
  protocole Strategy et sont sûres en sandbox : pas d'imports au-delà de
  math/statistics/numpy/pandas, pas d'E/S.
- Tout changement touchant le courtier exige : tests unitaires + un test
  d'intégration en mode papier.
- Les plafonds de risque (risque %, perte journalière, positions max) vivent
  dans configs/risk.yaml et ne sont jamais modifiés par du code généré ni par
  la logique d'amélioration IA.
- Lancer `pytest backend/tests` et `ruff check` avant de déclarer une tâche
  terminée.
- Chemins de code touchant l'argent : préférer l'explicite au malin ;
  journaliser chaque décision (signal, raison de veto, spread, calcul de lot)
  au niveau INFO.
- Frontend : Next.js (App Router) + Tailwind CSS ; les features reflètent les
  modules backend ; graphiques via lightweight-charts uniquement ; toujours
  les derniers paquets stables.
```

### 9.2 `.claude/skills/` (skills de dev Claude Code)

| Skill | Déclencheur | Rôle |
|-------|-------------|------|
| `new-strategy` | `/new-strategy <fichier-spec ou description>` | Génère un fichier de stratégie depuis une StrategySpec : interface correcte, imports sûrs, squelette de test unitaire, enregistrement dans le registre, backtest |
| `refine-bot` | `/refine-bot <id-rapport-analyse>` | Lit un AnalysisReport IA en BDD, propose/applique l'amélioration de code avec comparaison de backtests avant/après |
| `backtest` | `/backtest <stratégie> <symbole> <période>` | Lance la CLI de backtest, affiche le rapport, résume taux de réussite / PF / DD max |
| `trade-review` | `/trade-review [n]` | Récupère les n derniers trades du journal, les corrèle aux instantanés de marché, rédige une revue lisible |
| `news-skill-gen` | `/news-skill-gen <nom-événement>` | Génère un nouveau skill news YAML (fenêtre d'activation, plafonds de spread, multiplicateur de risque) depuis un template + la volatilité historique de l'événement |
| `frontend-feature` | `/frontend-feature <description>` | Crée/étend une feature frontend à la façon du projet : Next.js App Router + Tailwind, dossier feature miroir d'un module backend, clients api/ws partagés, derniers paquets stables, validation `pnpm lint` + `pnpm build` |

Chaque `SKILL.md` doit contenir : objectif, étapes exactes, fichiers qu'il
peut toucher, commandes de validation à lancer, et ce qu'il ne doit jamais
faire (p. ex. `refine-bot` ne doit jamais éditer `configs/risk.yaml`).

### 9.3 `.claude/settings.json` (hooks & permissions)
- Autoriser : `pytest`, `ruff`, `uv run`, la CLI de backtest.
- Hook (PostToolUse sur Edit/Write sous `strategies/generated/`) : lancer
  automatiquement la validation statique du sandbox.
- Hook (Stop) : rappeler de lancer les tests si `backend/src/` a changé et
  que pytest n'a pas tourné.

---

## 10. Plan de configuration complet

### 10.1 Carte des fichiers
| Fichier | Possède | Rechargeable à chaud ? |
|---------|---------|------------------------|
| `.env` | références de secrets, URL BDD, URL passerelle, clé Anthropic | non |
| `configs/app.yaml` | mode (papier/réel), symboles activés, moteur on/off, fuseau | oui |
| `configs/symbols/<sym>.yaml` | paramètres de trading par symbole | oui |
| `configs/risk.yaml` | plafonds de risque de l'utilisateur (l'IA ne peut jamais écrire) | oui |
| `configs/ai.yaml` | choix du fournisseur, modèles, mode d'amélioration | oui |
| `configs/news.yaml` | source du calendrier, événements suivis, fenêtres par défaut | oui |

### 10.2 Exemples

```yaml
# configs/app.yaml
mode: paper            # paper | live   ← TOUT démarre en papier
timezone: "Europe/Paris"
symbols: [XAUUSD, XAGUSD, BTCUSD]
engine:
  enabled: true
  entry_timeframe: M5
  # Pas de confirmation_timeframes ici : le veto HTF de chaque bot est
  # l'unique unité de temps juste au-dessus de son propre entry_timeframe
  # (M1→M5, M5→M15, M15→M30, …) — calculé automatiquement, pas configuré.
```

```yaml
# configs/symbols/xauusd.yaml
symbol: XAUUSD
max_spread_points: 35        # sauter les entrées au-dessus
min_rr: 1.5                  # après ajustement du spread
sessions:                    # ne trader que celles-ci (heure serveur)
  - { start: "09:00", end: "12:00" }
  - { start: "14:30", end: "18:00" }
default_skill: normal/xauusd
```

```yaml
# configs/risk.yaml            ← PROPRIÉTÉ DE L'UTILISATEUR. IA/code généré : lecture seule.
risk_per_trade_pct: 0.5
daily_loss_limit_pct: 2.0
max_open_positions: 2
max_trades_per_day: 8
consecutive_loss_pause: 5     # coupe-circuit
```

```yaml
# configs/ai.yaml
provider_per_task:
  pdf_extraction:  { provider: claude, model: claude-sonnet-5 }
  code_generation: { provider: claude, model: claude-sonnet-5 }
  ten_trade_review:{ provider: claude, model: claude-haiku-4-5 }
  # ou provider: ollama, model: qwen2.5-coder:14b
refinement:
  mode: suggest               # suggest | auto
  auto_apply_min_improvement_pct: 10
  max_auto_refinements_per_day: 1
review_every_n_trades: 10
```

### 10.3 Identifiants MT5 (F11)
- Saisis dans le formulaire de connexion du frontend → envoyés en HTTPS au
  backend → le backend les stocke **chiffrés** (clé Fernet dans le trousseau
  OS) → transmis à la passerelle uniquement au moment de la connexion → la
  passerelle les garde en mémoire seulement.
- Jamais écrits dans les logs, les fichiers de config, ni la BDD en clair.
  `.env.example` le documente explicitement.

---

## 11. Sécurité

- [ ] Identifiants chiffrés au repos (Fernet + trousseau OS) ; en mémoire
      seulement dans la passerelle.
- [ ] Backend↔passerelle sur localhost ou réseau privé / WireGuard si VPS ;
      en-tête d'authentification à secret partagé.
- [ ] Code de stratégie généré : liste blanche d'imports, scan AST des nœuds
      interdits (`exec`, `open`, `socket`, accès aux dunders), limites de
      ressources/temps sur `evaluate()`.
- [ ] Auth frontend (même mono-utilisateur : un mot de passe local) puisque
      l'UI peut démarrer un bot en réel.
- [ ] Kill switch : un endpoint + un bouton UI → fermer toutes les positions,
      désactiver le moteur.

---

## 12. Checklist d'implémentation (phases)

### Phase 0 — Fondations (dépôt & outillage)
- [x] Init du dépôt git, `README.md`, ce plan
- [x] `CLAUDE.md` + `.claude/settings.json` + squelettes de skills (§9)
- [x] Squelette backend : app FastAPI, squelettes de modules, conteneur DI, bus d'événements
- [x] Squelette frontend : Next.js (App Router) + Tailwind CSS + TS, layout, client api/ws
- [x] SQLite + migrations alembic
- [x] `docker-compose.yml` (backend, frontend, bdd) + doc d'installation de la passerelle (Wine ou VPS — à décider maintenant, voir §2)
- [x] CI : ruff + pytest à chaque commit

### Phase 1 — Passerelle MT5 & données de marché
- [x] Passerelle : login, bougies, tick, symbol_info (spread), santé
- [x] Module backend `market_data` + adaptateur `mt5_gateway`
- [x] Streaming de bougies M5/H1/H4/D1 pour les 3 symboles ; événements `CandleClosed`
- [x] Téléchargement d'historique → BDD (le streaming persiste les bougies clôturées ; `POST /market-data/backfill` pour le volume)
- [x] Connexion MT5 de bout en bout depuis l'UI (F11), stockage chiffré

### Phase 2 — Graphique (F2, F7 partiel)
- [ ] Chandeliers + volume lightweight-charts, thème sombre
- [ ] Mises à jour en direct par WebSocket ; sélecteur d'unité de temps
- [ ] Sélecteur de symbole (XAUUSD/XAGUSD/BTCUSD)
- [ ] Indicateur de spread dans l'en-tête du graphique

### Phase 3 — Courtier & trading papier
- [ ] Endpoints de trading de la passerelle : ouverture/modif/clôture/positions
- [ ] Module `broker` : modèles de domaine, règles de spread, adaptateurs `mt5_gateway` + `paper`
- [ ] Module `journal` : TradeRecord + instantanés du contexte de marché
- [ ] Marqueurs de trades sur le graphique (F7 complet)

### Phase 4 — Moteur & première stratégie (manuelle, pas encore d'IA)
- [ ] Boucle de trading à la clôture M5 ; confirmation HTF ; gestionnaire de risque ; gestionnaire de positions
- [ ] Une stratégie de référence écrite à la main (p. ex. breakout simple) pour valider le tuyau
- [ ] Sélecteur de skills + skills `normal/` pour les 3 symboles
- [ ] Coupe-circuits (perte journalière, pertes consécutives) + kill switch
- [ ] **Tourner 2+ semaines en mode papier** — ne pas passer en réel avant

### Phase 5 — Backtesting
- [ ] Adaptateur de rejeu + courtier papier → runner de backtest déterministe
- [ ] Simulation d'exécution consciente du spread
- [ ] Rapport : taux de réussite, profit factor, drawdown max, distribution des R, courbe d'équité
- [ ] CLI de backtest + page de rapport dans l'UI

### Phase 6 — IA : PDF → Stratégie (F4)
- [ ] `LLMPort` + adaptateur Claude + adaptateur Ollama ; config du fournisseur
- [ ] Upload PDF + extraction + prompt `extract_method_from_pdf` → StrategySpec
- [ ] UI de relecture/édition de la spec
- [ ] Prompt `generate_strategy_code` → validation sandbox → backtest auto
- [ ] Versionnage des stratégies + flux d'activation (papier d'abord)

### Phase 7 — IA : boucle d'amélioration toutes les 10 trades (F5)
- [ ] Événement `TenTradesCompleted` depuis le journal
- [ ] Constructeur du dossier de revue (trades + instantanés + code + spec)
- [ ] Prompt `review_ten_trades` → AnalysisReport → page UI
- [ ] `refine_strategy_code` → diff → sandbox → comparaison de backtests
- [ ] Politique suggest/auto + UI de rollback

### Phase 8 — Skills de news (F8)
- [ ] Module `news` : récupération du calendrier, classification d'impact, détection de fenêtres
- [ ] Skills news YAML (NFP, CPI, FOMC, générique) + surcharge de skill dans le moteur
- [ ] Mise à plat pré-news / blocage d'entrées ; stratégie de substitution post-news
- [ ] Fenêtres de news ombrées sur le graphique ; panneau des événements à venir

### Phase 9 — Durcissement & passage en réel
- [ ] Checklist de sécurité (§11) entièrement terminée
- [ ] Logique de reconnexion/reprise (chute de la passerelle, redémarrage du terminal, redémarrage du backend avec positions ouvertes)
- [ ] Alertes (Telegram/email) pour exécutions, coupe-circuits, améliorations
- [ ] 30 jours de trading papier rentable+stable → plus petite taille réelle → montée en charge lente

---

## 13. Stratégie de test & validation

| Couche | Comment |
|--------|---------|
| Logique de domaine | Tests unitaires purs (sans E/S), bougies en fixtures |
| Maths du spread & du risque | Tests par propriétés (hypothesis) — taille de lot, RR, ajustement du spread |
| Sandbox des stratégies | Tests adverses : du code généré tentant des imports/E-S interdits doit être rejeté |
| Moteur | Tests d'intégration sur fixtures de bougies enregistrées avec le courtier papier |
| Passerelle | Tests de contrat contre un simulacre ; test de fumée manuel sur compte démo |
| Prompts IA | Tests en golden-file : même dossier d'entrée → validation de la forme de la spec/du rapport (schéma, pas texte exact) |
| Bout en bout | Compte MT5 démo, pipeline papier→démo-réel, répétition générale d'un événement de news complet |

---

## 14. Avertissement sur les risques

Le trading automatisé d'instruments à effet de levier (surtout le XAUUSD)
peut perdre de l'argent **vite**. Ce plan intègre délibérément : le papier
d'abord partout, des plafonds de risque appartenant à l'utilisateur que l'IA
ne peut pas toucher, des coupe-circuits, des backtests obligatoires avant
activation, et l'approbation humaine par défaut pour les améliorations IA.
Conservez-les. Utilisez un **compte démo** jusqu'à ce que les critères de la
phase 9 soient remplis, et ne risquez jamais d'argent que vous ne pouvez pas
vous permettre de perdre.
