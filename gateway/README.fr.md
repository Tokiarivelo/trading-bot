> 🇬🇧 English version: [README.md](README.md)

# Passerelle MT5 (MT5 Gateway)

Le seul composant qui parle à MetaTrader 5. Il encapsule le paquet Python
officiel `MetaTrader5` (Windows uniquement) derrière une petite API HTTP
FastAPI, pour que le reste du système tourne nativement sous Linux.

**Aucune logique métier ici** — la passerelle rapporte des faits du courtier
(bougies, ticks, spread, positions) et exécute des ordres explicites. Toutes
les décisions se prennent dans `backend/`.

## Pourquoi elle existe

Le paquet pip `MetaTrader5` exige un **terminal MT5 de bureau** en cours
d'exécution et ne fonctionne que sous Windows. La passerelle isole cette
contrainte derrière HTTP : le déploiement devient un détail, pas un problème
de code.

## Choisir où la faire tourner

| Option | Usage | Verdict |
|--------|-------|---------|
| **A. Wine sous Linux** | Développement et trading papier sur cette machine | ✅ Suffisant pour les phases 1–8 |
| **B. VPS Windows** | Trading réel 24h/24 | ✅ **Recommandé pour le réel** (phase 9) |

**Recommandation :** développez avec **Wine** (gratuit, local, largement
suffisant pour le mode papier), puis passez sur un **VPS Windows proche des
serveurs de votre courtier** avant tout trading réel. Un VPS apporte une
latence faible, pas de mise en veille, pas de caprices de Wine en plein
trade, et survit à l'extinction de votre machine — autant de choses qui
comptent dès que de l'argent réel et des positions ouvertes sont en jeu.

## Prérequis (les deux options)

- Un **compte démo** chez un courtier (numéro de login, mot de passe, nom du
  serveur — p. ex. `MetaQuotes-Demo`). Restez en démo tant que les critères de
  passage en réel de la phase 9 ne sont pas remplis.
- L'installateur MT5 de votre courtier (`mt5setup.exe`), ou le générique de
  metatrader5.com.
- Python **3.12+ pour Windows** (la version *Windows*, même sous Wine — le
  paquet `MetaTrader5` ne publie que des wheels Windows).

## Option A — Wine (développement)

1. Installer Wine (Ubuntu/Debian) :
   ```bash
   sudo dpkg --add-architecture i386
   sudo apt update && sudo apt install --install-recommends wine64 wine32 winetricks
   ```
2. Installer le terminal MT5 dans un préfixe dédié :
   ```bash
   export WINEPREFIX=~/.mt5
   winetricks -q corefonts        # interface du terminal lisible
   wine mt5setup.exe
   ```
3. Installer Python 3.12 **Windows** dans le même préfixe :
   ```bash
   wine python-3.12.x-amd64.exe /quiet InstallAllUsers=0 PrependPath=1
   ```
4. Installer les dépendances de la passerelle avec le pip Windows et la
   démarrer :
   ```bash
   wine python -m pip install MetaTrader5 fastapi uvicorn pydantic
   cd gateway
   wine python run_gateway.py
   ```
   Le lanceur `run_gateway.py` ajoute `src/` au `sys.path` automatiquement —
   c'est nécessaire car Wine ne transmet pas `PYTHONPATH` au processus Python
   Windows.
5. Démarrer le terminal MT5 dans le même préfixe et le laisser tourner :
   ```bash
   WINEPREFIX=~/.mt5 wine "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe" &
   ```
   Puis configurer le terminal — voir
   [Configuration du terminal](#configuration-du-terminal-les-deux-options).

Pièges de Wine à connaître :

- Le terminal et la passerelle doivent tourner dans le **même préfixe Wine** —
  le paquet Python retrouve le terminal à travers lui.
- **Wine ne transmet pas `PYTHONPATH`** aux processus Windows — utilisez
  toujours `run_gateway.py` (qui injecte `src/` dans `sys.path`) au lieu
  d'appeler `uvicorn` directement.
- Si le terminal affiche une fenêtre noire/vide, essayez
  `winetricks -q dxvk` ou lancez avec
  `wine explorer /desktop=mt5,1600x900 terminal64.exe`.
- Désactivez la mise en veille pendant le trading papier de nuit ; un
  terminal suspendu est un terminal déconnecté.

## Option B — VPS Windows (recommandé pour le réel)

1. Louez un petit VPS Windows Server **proche des serveurs de trading de
   votre courtier** (les courtiers publient la localisation de leurs
   datacenters ; pinguez le nom de serveur affiché dans la fenêtre de
   connexion MT5 et choisissez la région au RTT le plus bas).
2. Installez le terminal MT5 et Python 3.12, puis :
   ```powershell
   pip install MetaTrader5 fastapi uvicorn pydantic
   ```
3. Copiez le dossier `gateway/` sur le VPS et lancez-le comme service pour
   qu'il survive aux redémarrages — p. ex. avec [NSSM](https://nssm.cc) :
   ```powershell
   nssm install mt5-gateway "C:\Python312\python.exe" ^
     "C:\trading-bot\gateway\run_gateway.py"
   nssm set mt5-gateway AppDirectory "C:\trading-bot\gateway"
   nssm set mt5-gateway AppEnvironmentExtra GATEWAY_SHARED_SECRET=<longue-chaine-aleatoire>
   nssm start mt5-gateway
   ```
   Ajoutez aussi le terminal MT5 au démarrage (Planificateur de tâches →
   lancer `terminal64.exe` à l'ouverture de session, avec connexion
   automatique activée) pour qu'un redémarrage du VPS remette tout en route.
4. **N'exposez jamais la passerelle sur l'internet public.** Liez-la à
   `127.0.0.1` et joignez-la depuis le backend via **WireGuard** ou un tunnel
   SSH :
   ```bash
   ssh -N -L 8787:127.0.0.1:8787 user@votre-vps   # le backend utilise alors 127.0.0.1:8787
   ```
5. Configurez le terminal — section suivante.

## Configuration du terminal (les deux options)

À faire une fois dans le terminal MT5, connecté à votre compte **démo** :

1. **Connexion** : Fichier → *Se connecter à un compte de trading* → saisir
   login / mot de passe / serveur. Cochez *Enregistrer le mot de passe* pour
   que le terminal se reconnecte après un redémarrage. (La connexion depuis
   l'UI de l'app (F11) se ré-authentifie de toute façon via la passerelle ;
   un terminal déjà connecté maintient le flux de données entre deux
   redémarrages du backend.)
2. **Activer le trading algorithmique** : Outils → Options → *Expert
   Advisors* → cocher **Autoriser le trading algorithmique**, et vérifier que
   le bouton **Algo Trading** de la barre d'outils est ACTIVÉ (vert). Sans
   cela, les ordres de la phase 3+ échouent avec le code retour `10027`
   (trading algo désactivé côté client).
3. **Symboles du Market Watch** : clic droit sur le Market Watch →
   *Symboles* → rendre visibles **XAUUSD, XAGUSD, BTCUSD**. La passerelle
   appelle `symbol_select` par précaution, mais vérifiez les **noms exacts**
   utilisés par votre courtier — certains les suffixent (`XAUUSD.a`,
   `GOLDmicro`, `BTCUSD.x`). S'ils diffèrent, mettez à jour
   `configs/app.yaml` et `configs/symbols/*.yaml` en conséquence.
4. **Profondeur d'historique** : Outils → Options → Graphiques → régler
   *Nombre max de barres par graphique* au maximum. MT5 ne sert que
   l'historique déjà téléchargé ; ouvrez une fois un graphique M5/H1/H4/D1 de
   chaque symbole et faites défiler vers le passé pour forcer le
   téléchargement avant de lancer `POST /market-data/backfill`.
5. **Le laisser tourner** : l'API Python ne fonctionne que si le processus du
   terminal est actif et connecté. Le `/health` de la passerelle rapporte
   `terminal_connected: false` dès que ce n'est pas le cas, et le backend met
   le streaming en pause jusqu'au retour.

## Relier le backend à la passerelle

Dans le `.env` à la racine du dépôt (voir `.env.example`) :

```bash
TB_GATEWAY_URL=http://127.0.0.1:8787         # ou l'extrémité du tunnel
TB_GATEWAY_SHARED_SECRET=<même valeur que GATEWAY_SHARED_SECRET côté passerelle>
```

Chaque requête sauf `/health` doit porter le secret dans l'en-tête
`X-Gateway-Secret` — les adaptateurs du backend le font automatiquement. Si
`GATEWAY_SHARED_SECRET` n'est pas défini côté passerelle, la vérification est
sautée ; acceptable uniquement quand les deux processus partagent la même
machine et que le port est lié à localhost.

## Test de bon fonctionnement

```bash
# 1. Passerelle en vie ? (pas de secret requis)
curl -s http://127.0.0.1:8787/health
#    → {"status":"ok","terminal_connected":false,"account":null}

# 2. Connexion via la passerelle (ou utilisez simplement le panneau
#    « MT5 Account » de l'UI) :
curl -s -X POST http://127.0.0.1:8787/login \
  -H "X-Gateway-Secret: $TB_GATEWAY_SHARED_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"login": 12345678, "password": "...", "server": "MetaQuotes-Demo"}'

# 3. Les bougies arrivent ?
curl -s "http://127.0.0.1:8787/candles?symbol=XAUUSD&timeframe=M5&count=3" \
  -H "X-Gateway-Secret: $TB_GATEWAY_SHARED_SECRET"
```

Démarrez ensuite le backend (`make dev-backend`) et connectez-vous depuis le
panneau **MT5 Account** de l'UI — le statut passe au vert et le flux de
bougies commence à journaliser des lignes `candle closed …` à chaque clôture
M5.

## Dépannage

| Symptôme | Cause probable / correctif |
|----------|----------------------------|
| `502 login rejected: [-6] Authorization failed` | Mauvais login/mot de passe/**nom de serveur** (copiez-le exactement depuis l'e-mail du courtier) |
| `502 not logged in — POST /login first` | Backend pas encore connecté — utilisez le panneau de connexion de l'UI |
| `terminal_connected: false` alors que la connexion marchait | Terminal fermé/planté ou lien courtier perdu — redémarrez-le, la passerelle se reconnecte au prochain `/login` |
| `/candles` renvoie très peu de barres | Le terminal n'a pas téléchargé cet historique — ouvrez le graphique et remontez le temps (voir Profondeur d'historique) |
| `401 bad or missing X-Gateway-Secret` | `TB_GATEWAY_SHARED_SECRET` (backend) ≠ `GATEWAY_SHARED_SECRET` (passerelle) |
| Les ordres échouent avec le code `10027` (phase 3+) | Trading algo désactivé dans le terminal — voir Configuration du terminal, étape 2 |
| Le terminal sous Wine perd la connexion quand le portable se met en veille | Désactivez la veille, ou passez à l'option VPS |

## API (implémentée en phase 1)

| Endpoint | Rôle |
|----------|------|
| `POST /login` | Connexion à un compte MT5 (identifiants gardés en mémoire uniquement) |
| `POST /logout` | Coupe la connexion au terminal |
| `GET /health` | État de connexion terminal & compte (sans auth) |
| `GET /candles` | Historique OHLCV (symbole, unité de temps M5/H1/H4/D1, nombre) |
| `GET /tick` | Dernier bid/ask |
| `GET /symbol_info` | Spécifications du contrat + spread en direct + stops level |
| `POST /order` | Ouvrir/modifier un ordre *(phase 3)* |
| `POST /close` | Fermer une position *(phase 3)* |
| `GET /positions` | Positions ouvertes *(phase 3)* |
