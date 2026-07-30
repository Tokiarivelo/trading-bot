> 🇬🇧 English version: [DEPLOY_DIGITALOCEAN.md](DEPLOY_DIGITALOCEAN.md)

# Déployer sur DigitalOcean (GitHub Student Developer Pack)

Ce guide explique comment déployer le **backend** (FastAPI) et le
**frontend** (Next.js) sur un Droplet DigitalOcean en utilisant le crédit du
GitHub Student Developer Pack, comment garder l'application active 24h/24,
et comment configurer un workflow GitHub Actions qui déploie automatiquement
à chaque push sur `main`.

**La gateway MT5 est un sujet à part** — lisez la
[Partie 5](#partie-5--faire-tourner-la-gateway-mt5-le-bot-lui-même) avant de
supposer que le bot trade directement depuis le Droplet. `MetaTrader5` est
Windows uniquement (voir [`gateway/README.md`](../gateway/README.md)) ;
DigitalOcean ne propose pas de Droplet Windows, donc deux options existent
et ce guide couvre les deux.

## Rappel d'architecture

| Composant | Ce que c'est | Où il tourne dans ce guide |
|---|---|---|
| `backend/` | FastAPI + Socket.IO, toute la logique de trading, le moteur de risque | Droplet DigitalOcean (Docker) |
| `frontend/` | Dashboard Next.js | Droplet DigitalOcean (Docker) |
| `gateway/` | Fine couche HTTP autour du package `MetaTrader5` (Windows uniquement) | Wine sur le même Droplet (démo) **ou** un VPS Windows séparé (live) |

---

## Prérequis

- Un compte GitHub inscrit au [GitHub Student Developer Pack](https://education.github.com/pack) (education.github.com/pack).
- Un nom de domaine (optionnel mais recommandé pour le HTTPS — un
  sous-domaine suffit).
- Avoir `git`, `ssh` et `docker` en local est pratique mais pas obligatoire —
  tout ce qui suit peut se faire depuis la console web DigitalOcean.

---

## Partie 1 — Activer votre crédit DigitalOcean

1. Rendez-vous sur la page du GitHub Student Developer Pack et repérez
   l'offre DigitalOcean parmi les offres partenaires.
2. Activez-la — cela relie un compte DigitalOcean à votre vérification
   étudiante GitHub et le crédite (vérifiez le montant/la durée actuels sur
   la page de l'offre, ils évoluent dans le temps).
3. Créez/connectez-vous à votre compte DigitalOcean et vérifiez que le
   crédit apparaît dans **Billing**.

---

## Partie 2 — Créer et sécuriser le Droplet

### 2.1 Créer le Droplet

- **Image :** Ubuntu 24.04 LTS (x64).
- **Taille :** un Droplet `Basic` à 2 Go de RAM / 1 vCPU est le minimum
  pratique — le build Next.js et les deux services tournant en même temps
  consomment de la mémoire ; avec 1 Go, le swap sera permanent. 4 Go donne
  de la marge si vous faites aussi tourner la gateway Wine ici (Partie 5,
  Option A).
- **Région :** choisissez-en une proche de vous (pour la latence
  d'administration) ; elle n'a **pas** besoin d'être proche de votre
  broker — cette contrainte ne s'applique qu'à la gateway/VPS de la Partie 5.
- **Authentification :** clé SSH, pas de mot de passe. Uploadez votre clé
  publique (`~/.ssh/id_ed25519.pub`, ou générez-en une avec
  `ssh-keygen -t ed25519`).
- Activez les **backups** si votre crédit le permet — une assurance peu
  chère pour une application qui touche à de l'argent.

### 2.2 Durcissement initial

Connectez-vous une fois en SSH en tant que `root`, puis :

```bash
# Créer un utilisateur non-root avec sudo
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# Pare-feu : seulement SSH, HTTP, HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Optionnel mais recommandé : désactiver la connexion root en SSH et
# l'authentification par mot de passe dans /etc/ssh/sshd_config
# (PermitRootLogin no, PasswordAuthentication no), puis :
# systemctl restart ssh
```

À partir de là, connectez-vous en `deploy@<ip-du-droplet>`.

### 2.3 Installer Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
newgrp docker
docker compose version   # vérification — doit afficher un client v2
```

---

## Partie 3 — Mettre l'app sur le serveur et configurer les secrets

```bash
sudo mkdir -p /opt/trading-bot && sudo chown deploy:deploy /opt/trading-bot
git clone https://github.com/<vous>/<repo>.git /opt/trading-bot
cd /opt/trading-bot
cp .env.example .env
```

Éditez `.env` et remplissez les valeurs de production :

- `TB_GATEWAY_SHARED_SECRET` (et les variantes par compte) — générez-les
  avec `openssl rand -hex 32`, elles doivent correspondre à ce
  qu'utilise(nt) la ou les gateway(s).
- `TB_GATEWAY_URL` — dépend de l'option choisie en Partie 5 (Wine sur cette
  machine ou tunnel vers un VPS Windows distant).
- `TB_APP_PASSWORD` — **à définir absolument**. Le Droplet est public ; un
  dashboard sans authentification à côté du passage d'ordres réels n'est
  pas acceptable.
- Les clés des fournisseurs IA, l'alerting Telegram/SMTP,
  `TB_FINNHUB_API_KEY` — selon vos besoins.
- Ne mettez jamais le login/mot de passe MT5 dans `.env` — saisissez-les via
  le panneau MT5 Account de l'UI une fois l'app démarrée, comme partout
  ailleurs dans ce projet.

Les fichiers `configs/*.yaml` (plafonds de risque, comptes, symboles) sont
déjà dans le repo et montés en lecture seule dans le conteneur backend —
relisez `configs/risk.yaml` avant d'approcher un compte live.

---

## Partie 4 — Docker Compose de production + HTTPS

Le `docker-compose.yml` à la racine du repo est une stack de **dev**
(bind-mount du code frontend, lance `pnpm dev`) — parfait sur un
laptop, pas ce qu'il vous faut sur un serveur. Pour la production,
construisez de vraies images et mettez un reverse proxy devant pour le
TLS. Aucun des fichiers ci-dessous n'existe encore dans le repo ; ajoutez-les
lors de la mise en place du déploiement.

### 4.1 `frontend/Dockerfile` (build de production)

```dockerfile
FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS build
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:24-alpine AS runner
WORKDIR /app
RUN corepack enable
ENV NODE_ENV=production
COPY --from=build /app/public ./public
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.ts ./
EXPOSE 3000
CMD ["pnpm", "start"]
```

(Optimisation optionnelle plus tard : ajouter `output: "standalone"` dans
`next.config.ts` pour une image finale bien plus légère — pas nécessaire
pour que ça fonctionne.)

### 4.2 `docker-compose.prod.yml` (racine du repo)

```yaml
services:
  backend:
    image: ghcr.io/<owner>/<repo>-backend:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./configs:/app/configs:ro
      - ./data:/app/data
    expose:
      - "8000"

  frontend:
    image: ghcr.io/<owner>/<repo>-frontend:latest
    restart: unless-stopped
    environment:
      - BACKEND_URL=http://backend:8000
    expose:
      - "3000"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on:
      - backend
      - frontend

volumes:
  caddy_data:
```

`<owner>/<repo>` doit être en minuscules (règle des tags Docker) — utilisez
la forme minuscule de votre org/utilisateur GitHub et du nom du repo.

### 4.3 `Caddyfile` (racine du repo) — HTTPS automatique via Let's Encrypt

```
your-domain.com {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle /socket.io/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3000
    }
}
```

Pointez l'enregistrement `A` du domaine vers l'IP du Droplet avant de
démarrer Caddy, sinon il ne pourra pas compléter le challenge ACME. Pas
encore de domaine ? Remplacez l'adresse du site par `:80` et laissez le TLS
de côté pour l'instant — vous pourrez l'ajouter plus tard sans rien changer
d'autre.

### 4.4 Premier lancement

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f
```

(La Partie 6 explique comment construire ces images `ghcr.io/...` via la CI
pour ne jamais avoir à faire `docker build` à la main sur le Droplet.)

---

## Partie 5 — Faire tourner la gateway MT5 (le bot lui-même)

`MetaTrader5` ne fournit que des wheels Windows et a besoin d'un terminal
MT5 desktop en cours d'exécution (voir
[`gateway/README.md`](../gateway/README.md) pour toute la justification).
Choisissez une option :

### Option A — Wine sur le même Droplet (trading démo/papier)

Ça fonctionne, et c'est la recommandation du projet lui-même ("fine for
Phases 1–8"), mais un Droplet n'a pas d'écran — Wine a besoin d'un
framebuffer virtuel :

```bash
sudo apt update && sudo apt install --install-recommends -y \
  wine64 wine32 winetricks xvfb
```

Suivez ensuite l'Option A de `gateway/README.md` (installer le terminal MT5
et Python Windows dans un `WINEPREFIX` dédié), mais préfixez toute étape qui
lance Wine avec `xvfb-run`, par exemple :

```bash
xvfb-run -a --server-args="-screen 0 1024x768x24" \
  make -C /opt/trading-bot dev-gateway ACCOUNT=<id-du-compte>
```

Pour survivre aux redémarrages, encapsulez ça dans une unité systemd plutôt
qu'une session de terminal :

```ini
# /etc/systemd/system/mt5-gateway.service
[Unit]
Description=MT5 gateway (Wine, headless)
After=network.target

[Service]
User=deploy
WorkingDirectory=/opt/trading-bot
Environment=WINEPREFIX=/home/deploy/.mt5
Environment=WINEDEBUG=fixme-all
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1024x768x24" \
  /usr/bin/make -C /opt/trading-bot dev-gateway ACCOUNT=<id-du-compte>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now mt5-gateway
```

### Option B — VPS Windows séparé (recommandé avant tout trading live)

**Guide détaillé (choix du fournisseur, durcissement, configuration du
tunnel SSH) : [`WINDOWS_VPS_MT5_GATEWAY.fr.md`](WINDOWS_VPS_MT5_GATEWAY.fr.md).**
Version courte — selon l'Option B de `gateway/README.md` : louez un petit VPS Windows Server
proche des serveurs de trading de votre broker, faites-y tourner le
terminal + la gateway sous NSSM, liez la gateway à `127.0.0.1` uniquement,
et joignez-la depuis le Droplet DigitalOcean via un tunnel SSH ou
WireGuard — **ne l'exposez jamais publiquement**. Depuis le Droplet :

```bash
ssh -N -L 8787:127.0.0.1:8787 user@votre-vps-windows &
```

Puis définissez `TB_GATEWAY_URL=http://127.0.0.1:8787` dans le `.env` du
Droplet. Gardez ce tunnel actif avec `autossh` + une unité systemd, de la
même manière que pour l'Option A ci-dessus.

Le crédit du Student Pack DigitalOcean ne couvre que le Droplet Linux — le
VPS Windows pour le live est un coût séparé, hors DO ; la recommandation du
projet lui-même est de choisir ce VPS selon la proximité avec les serveurs
de votre broker, pas selon l'endroit où tourne votre dashboard.

---

## Partie 6 — GitHub Actions : CI (déjà en place) + CD

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) fait déjà le lint
et les tests du backend, de la gateway et du frontend à chaque push/PR.
Ajoutez un workflow de déploiement qui ne se lance qu'une fois la CI passée
sur `main`, construit les images, les pousse vers GitHub Container Registry
(gratuit pour les repos publics et, dans certaines limites, privés — aucun
compte supplémentaire nécessaire au-delà de GitHub), puis demande au
Droplet de les récupérer et de redémarrer.

### 6.1 Secrets du repository

**Settings → Secrets and variables → Actions → New repository secret :**

| Secret | Valeur |
|---|---|
| `DO_HOST` | IP publique ou domaine du Droplet |
| `DO_USER` | `deploy` |
| `DO_SSH_KEY` | clé privée correspondant à une clé publique déjà présente dans `~/.ssh/authorized_keys` de `deploy` (générez une paire de clés dédiée au déploiement — ne réutilisez pas votre clé personnelle) |

Le `GITHUB_TOKEN` pour pousser vers `ghcr.io` est fourni automatiquement —
pas de secret à créer pour ça.

### 6.2 `.github/workflows/deploy.yml`

```yaml
name: Deploy to DigitalOcean

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
    branches: [main]

jobs:
  build-and-push:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/build-push-action@v6
        with:
          context: ./backend
          push: true
          tags: ghcr.io/${{ github.repository }}-backend:latest

      - uses: docker/build-push-action@v6
        with:
          context: ./frontend
          push: true
          tags: ghcr.io/${{ github.repository }}-frontend:latest

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - name: SSH et redéploiement
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.DO_HOST }}
          username: ${{ secrets.DO_USER }}
          key: ${{ secrets.DO_SSH_KEY }}
          script: |
            cd /opt/trading-bot
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d
            docker image prune -f
```

Notes :

- `${{ github.repository }}` vaut `owner/repo` — si l'un des deux contient
  des majuscules, écrivez la forme minuscule en dur dans les tags à la
  place (Docker refuse les majuscules dans les noms d'image).
- Le déclencheur `workflow_run` fait que `deploy.yml` ne se déclenche
  qu'après la fin de `CI` sur `main`, et ne continue que si elle a réussi —
  un `ruff`/`pytest`/`pnpm build` en échec n'atteint jamais le Droplet.
- Ça ne touche jamais à `configs/risk.yaml` ni au code du moteur/coupe-circuit —
  ça ne fait que reconstruire des images à partir de ce qui a déjà été relu
  et mergé.

---

## Partie 7 — Exploitation

- **Logs :** `docker compose -f docker-compose.prod.yml logs -f backend`
  (ou `frontend`, `caddy`).
- **Redéploiement manuel :** relancez le workflow `deploy.yml` depuis
  l'onglet Actions, ou connectez-vous en SSH et lancez le même
  `pull && up -d` à la main.
- **Snapshots :** prenez un snapshot DigitalOcean avant tout changement
  risqué (par ex. avant de basculer un compte de démo à live).
- **Coût :** un Droplet 2–4 Go coûte environ 12–24 $/mois — le crédit du
  Student Pack couvre en général plusieurs mois ; vérifiez le montant/le
  tarif actuels sur votre page de facturation DigitalOcean, ils évoluent
  dans le temps.
- **Checklist sécurité :** SSH par clé uniquement + pas de login root, UFW
  limité à 22/80/443, `TB_APP_PASSWORD` défini, gateway jamais exposée
  publiquement (tunnel uniquement), secrets uniquement dans `.env`/les
  secrets GitHub Actions — jamais commités.
