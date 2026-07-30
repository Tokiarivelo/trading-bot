> 🇫🇷 Version française : [DEPLOY_DIGITALOCEAN.fr.md](DEPLOY_DIGITALOCEAN.fr.md)

# Deploying to DigitalOcean (GitHub Student Developer Pack)

This guide covers deploying the **backend** (FastAPI) and **frontend**
(Next.js) to a DigitalOcean Droplet using your GitHub Student Developer Pack
credit, keeping the app running 24/7, and setting up a GitHub Actions
workflow that deploys automatically on every push to `main`.

**The MT5 gateway is a separate concern** — read
[Part 5](#part-5--running-the-mt5-gateway-the-bot-itself) before assuming
the bot trades straight out of the Droplet. `MetaTrader5` is Windows-only
(see [`gateway/README.md`](../gateway/README.md)); DigitalOcean does not
offer Windows Droplets, so you have two options and this guide covers both.

## Architecture recap

| Component | What it is | Where it runs in this guide |
|---|---|---|
| `backend/` | FastAPI + Socket.IO, all trading logic, risk engine | DigitalOcean Droplet (Docker) |
| `frontend/` | Next.js dashboard | DigitalOcean Droplet (Docker) |
| `gateway/` | Thin HTTP wrapper around the Windows-only `MetaTrader5` package | Wine on the same Droplet (paper) **or** a separate Windows VPS (live) |

---

## Prerequisites

- A GitHub account enrolled in the [GitHub Student Developer Pack](https://education.github.com/pack) (education.github.com/pack).
- A domain name (optional but recommended for HTTPS — a subdomain works fine).
- `git`, `ssh`, and `docker` installed locally is convenient but not required —
  everything below can be done through the DigitalOcean web console.

---

## Part 1 — Activate your DigitalOcean credit

1. Go to the GitHub Student Developer Pack page and find the DigitalOcean
   offer among the partner offers.
2. Redeem it — this links a DigitalOcean account to your GitHub education
   verification and credits it (check the current amount/validity on the
   offer page; it changes over time).
3. Create/sign in to your DigitalOcean account and confirm the credit is
   applied under **Billing**.

---

## Part 2 — Create and secure the Droplet

### 2.1 Create the Droplet

- **Image:** Ubuntu 24.04 LTS (x64).
- **Size:** a `Basic` Droplet with 2 GB RAM / 1 vCPU is the practical
  minimum — the Next.js build step and running both services at once are
  memory-hungry; 1 GB will swap constantly. 4 GB gives headroom if you also
  run the Wine gateway here (Part 5, Option A).
- **Region:** pick one close to you (for admin latency); it does **not**
  need to be close to your broker — that constraint only applies to the
  gateway/VPS in Part 5.
- **Authentication:** SSH key, not password. Upload your public key
  (`~/.ssh/id_ed25519.pub` or generate one with `ssh-keygen -t ed25519`).
- Enable **backups** if your credit covers it — cheap insurance for a
  money-adjacent app.

### 2.2 Initial hardening

SSH in as `root` once, then:

```bash
# Create a non-root user with sudo
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# Firewall: only SSH, HTTP, HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Optional but recommended: disable root SSH login and password auth
# in /etc/ssh/sshd_config (PermitRootLogin no, PasswordAuthentication no),
# then: systemctl restart ssh
```

From here on, SSH in as `deploy@<droplet-ip>`.

### 2.3 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
newgrp docker
docker compose version   # sanity check — should print a v2 client
```

---

## Part 3 — Get the app onto the server and configure secrets

```bash
sudo mkdir -p /opt/trading-bot && sudo chown deploy:deploy /opt/trading-bot
git clone https://github.com/<you>/<repo>.git /opt/trading-bot
cd /opt/trading-bot
cp .env.example .env
```

Edit `.env` and fill in production values:

- `TB_GATEWAY_SHARED_SECRET` (and any per-account variants) — generate with
  `openssl rand -hex 32`, must match what the gateway(s) use.
- `TB_GATEWAY_URL` — depends on Part 5's option (Wine on this box vs. a
  tunnel to a remote Windows VPS).
- `TB_APP_PASSWORD` — **set this**. The Droplet is public; an unauthenticated
  dashboard next to live order placement is not acceptable.
- AI provider keys, Telegram/SMTP alerting, `TB_FINNHUB_API_KEY` — as needed.
- Leave MT5 login/password out of `.env` entirely — enter them through the
  UI's MT5 Account panel once the app is up, as everywhere else in this
  project.

`configs/*.yaml` (risk caps, accounts, symbols) ship in the repo and are
mounted read-only into the backend container — review `configs/risk.yaml`
before going anywhere near a live account.

---

## Part 4 — Production Docker Compose + HTTPS

The repo's root `docker-compose.yml` is a **dev** stack (bind-mounts the
frontend source and runs `pnpm dev`) — fine on a laptop, not what you want
on a server. For production, build real images and put a reverse proxy in
front for TLS. None of the files below exist in the repo yet; add them as
part of your deployment setup.

### 4.1 `frontend/Dockerfile` (production build)

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

(Optional optimization later: set `output: "standalone"` in
`next.config.ts` to ship a much smaller runner image — not required to get
this working.)

### 4.2 `docker-compose.prod.yml` (repo root)

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

`<owner>/<repo>` must be lowercase (Docker image tag rule) — use your
lowercase GitHub org/user and repo name.

### 4.3 `Caddyfile` (repo root) — automatic HTTPS via Let's Encrypt

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

Point the domain's `A` record at the Droplet's IP before starting Caddy, or
it can't complete the ACME challenge. No domain yet? Replace the site
address with `:80` and skip TLS for now — upgrade later without changing
anything else.

### 4.4 First launch

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f
```

(Part 6 covers building those `ghcr.io/...` images via CI so you never have
to `docker build` by hand on the Droplet.)

---

## Part 5 — Running the MT5 gateway (the bot itself)

`MetaTrader5` only ships Windows wheels and needs a running MT5 desktop
terminal (see [`gateway/README.md`](../gateway/README.md) for the full
rationale). Pick one:

### Option A — Wine on the same Droplet (paper / demo trading)

Works, per the project's own recommendation ("fine for Phases 1–8"), but a
Droplet has no display — Wine needs a virtual framebuffer:

```bash
sudo apt update && sudo apt install --install-recommends -y \
  wine64 wine32 winetricks xvfb
```

Then follow `gateway/README.md`'s Option A (install the MT5 terminal and
Windows Python into a dedicated `WINEPREFIX`), but prefix any step that
launches Wine with `xvfb-run`, e.g.:

```bash
xvfb-run -a --server-args="-screen 0 1024x768x24" \
  make -C /opt/trading-bot dev-gateway ACCOUNT=<your-account-id>
```

To survive reboots, wrap that in a systemd unit instead of a terminal
session:

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
  /usr/bin/make -C /opt/trading-bot dev-gateway ACCOUNT=<your-account-id>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now mt5-gateway
```

### Option B — Separate Windows VPS (recommended before any live trading)

**Full walkthrough (provider choice, hardening, SSH tunnel setup):
[`WINDOWS_VPS_MT5_GATEWAY.md`](WINDOWS_VPS_MT5_GATEWAY.md).** Short version —
per `gateway/README.md`'s Option B: rent a small Windows Server VPS near
your broker's trade servers, run the terminal + gateway there under NSSM,
bind the gateway to `127.0.0.1` only, and reach it from the DigitalOcean
Droplet over an SSH tunnel or WireGuard — **never expose it publicly**.
From the Droplet:

```bash
ssh -N -L 8787:127.0.0.1:8787 user@your-windows-vps &
```

Then set `TB_GATEWAY_URL=http://127.0.0.1:8787` in `.env` on the Droplet.
Keep that tunnel alive with `autossh` + a systemd unit the same way as
Option A above.

DigitalOcean's Student Pack credit only covers the Linux Droplet — the
Windows VPS for live trading is a separate, non-DO cost; the project's own
guidance is to size that choice by proximity to your broker's servers, not
by where your dashboard runs.

---

## Part 6 — GitHub Actions: CI (already in place) + CD

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) already lints and
tests backend, gateway, and frontend on every push/PR. Add a deploy workflow
that only runs once CI has passed on `main`, builds images, pushes them to
GitHub Container Registry (free for public and, within limits, private
repos — no extra account needed beyond GitHub), and tells the Droplet to
pull and restart.

### 6.1 Repository secrets

**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Value |
|---|---|
| `DO_HOST` | Droplet's public IP or domain |
| `DO_USER` | `deploy` |
| `DO_SSH_KEY` | private key matching a public key already in `deploy`'s `~/.ssh/authorized_keys` (generate a dedicated deploy keypair — don't reuse your personal one) |

`GITHUB_TOKEN` for pushing to `ghcr.io` is provided automatically — no
secret needed for that part.

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
      - name: SSH and redeploy
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

Notes:

- `${{ github.repository }}` is `owner/repo` — if either has uppercase
  characters, hardcode the lowercase form in the tags instead (Docker
  rejects uppercase image names).
- The `workflow_run` trigger means `deploy.yml` only fires after `CI`
  finishes on `main`, and only proceeds if it succeeded — a red `ruff`/
  `pytest`/`pnpm build` run never reaches the Droplet.
- This never touches `configs/risk.yaml` or engine/circuit-breaker code —
  it only rebuilds images from what's already been reviewed and merged.

---

## Part 7 — Operations

- **Logs:** `docker compose -f docker-compose.prod.yml logs -f backend`
  (or `frontend`, `caddy`).
- **Manual redeploy:** re-run the `deploy.yml` workflow from the Actions
  tab, or SSH in and run the same `pull && up -d` by hand.
- **Snapshots:** take a DigitalOcean snapshot before any risky change
  (e.g. before flipping an account from demo to live).
- **Cost:** a 2–4 GB Droplet runs roughly $12–24/month — the Student Pack
  credit typically covers many months; check current pricing/credit amount
  in your DigitalOcean billing page, it changes over time.
- **Security checklist:** SSH key-only + no root login, UFW limited to
  22/80/443, `TB_APP_PASSWORD` set, gateway never exposed publicly (tunnel
  only), secrets only in `.env`/GitHub Actions secrets — never committed.
