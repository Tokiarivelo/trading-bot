> 🇬🇧 English version: [WINDOWS_VPS_MT5_GATEWAY.md](WINDOWS_VPS_MT5_GATEWAY.md)

# Configuration du VPS Windows pour la gateway MT5

Ceci détaille l'**Option B** de [`gateway/README.md`](../gateway/README.md)
et de [`DEPLOY_DIGITALOCEAN.md`](DEPLOY_DIGITALOCEAN.fr.md) Partie 5 : un
VPS Windows dédié qui fait tourner le terminal MT5 + la gateway, joignable
uniquement via un tunnel SSH depuis le Droplet backend. À utiliser une fois
passée la phase de trading papier sous Wine, en préparation du passage en
live.

---

## 1. Où l'héberger ?

### Y a-t-il une option Windows dans le GitHub Student Developer Pack ?

**Oui — Microsoft Azure.** Le pack inclut une offre Azure for Students :
**100 $ de crédit Azure pendant 12 mois**, sans carte bancaire requise pour
l'activer. Azure supporte nativement les VM Windows Server, contrairement
à DigitalOcean.

**Le piège :** les VM Windows sur Azure ont un surcoût de licence en plus
du prix du calcul. Une taille réellement confortable pour le terminal MT5 +
la gateway (2 vCPU / 4 Go — `Standard_B2s`) coûte environ **60–70 $/mois**
en Windows sur une région classique, une fois la remise gratuite de la
série B non applicable. À ce tarif, 100 $ couvrent **quelques semaines**,
pas 12 mois, si la VM tourne 24h/24. C'est réellement utile pour :

- Le test initial de préparation au live (checklist go-live de la Phase 9)
  avant de s'engager dans un VPS payant sur la durée.
- Des sessions courtes — démarrer la VM, valider, la désallouer (Azure ne
  facture pas le calcul d'une VM *désallouée*, seulement le stockage)
  quand vous ne testez pas.

Ce n'est **pas** le choix le plus économique pour un bot qui doit rester
connecté 24h/24 pendant des mois. Pour ça, un VPS Forex spécialisé est moins
cher et — surtout — vous permet en général de choisir un datacenter proche
des serveurs de votre broker, ce qui réduit la latence bien plus qu'une
région cloud générique.

### Alternatives moins chères, spécialisées

Les fournisseurs de "VPS Forex" vendent de petites instances Windows
Server déjà optimisées pour MT4/MT5, licence Windows incluse dans le prix :

| Type | Prix typique | Remarques |
|---|---|---|
| VPS Forex spécialisé (offres orientées MT4/MT5) | **~10–15 $/mois** en entrée de gamme | Licence Windows incluse ; datacenters choisis pour la proximité broker (emplacements type NY4/LD4/Equinix) ; support habitué aux spécificités MT5 |
| VPS Windows générique bon marché (Contabo, OVH, similaires) | **~7–15 $/mois** | Calcul brut moins cher, mais région générique — testez le ping vers le serveur de votre broker vous-même avant de vous engager |
| Azure for Students (pack GitHub) | 100 $ de crédit / 12 mois, puis paiement à l'usage | Idéal pour des validations courtes, pas pour un usage live continu 24h/24 — voir le calcul de licence ci-dessus |
| Instances Windows AWS / GCP | Comparable à Azure | Pas de crédit étudiant spécifique Windows dans le pack GitHub pour l'un ou l'autre ; leurs offres gratuites sont Linux uniquement |

**Recommandation :** validez d'abord avec le crédit gratuit Azure (déjà
"gratuit" via le Student Pack), puis passez à un VPS Forex spécialisé à
~10–15 $/mois dans la région de votre broker pour l'installation live sur
la durée. Dans les deux cas, les étapes ci-dessous (à partir de
"Provisionnement") sont identiques une fois que vous avez un accès RDP à
une machine Windows.

---

## 2. Dimensionnement & région

- **Taille :** 2 vCPU / 4 Go de RAM minimum. Le terminal MT5 est une
  véritable application desktop graphique, en plus du processus Python de
  la gateway et de la charge de Windows Server — 1 vCPU / 2 Go sera juste.
- **OS :** Windows Server 2019/2022, ou Windows 10/11 si c'est ce que
  propose le fournisseur — les deux fonctionnent ; le package
  `MetaTrader5` a seulement besoin d'un Python Windows, selon
  `gateway/README.md`.
- **Région — c'est la décision qui compte vraiment pour la qualité du
  trading, plus que le prix :** récupérez le nom/l'adresse du serveur que
  MT5 affiche dans sa boîte de connexion pour votre broker, et faites un
  `ping` (ou `tracert`) depuis quelques régions/fournisseurs candidats
  avant de louer quoi que ce soit. Choisissez le round-trip le plus bas,
  pas l'offre la moins chère.

---

## 3. Provisionnement

### Voie A — Azure (crédit GitHub Student Pack)

1. Activez l'offre Azure for Students depuis le GitHub Student Developer
   Pack (education.github.com/pack) — aucune carte bancaire requise.
2. Dans le [portail Azure](https://portal.azure.com), **Créer une
   ressource → Windows Server** (2022 Datacenter Azure Edition est un choix
   sûr par défaut).
3. Taille : `Standard_B2s` (2 vCPU / 4 Go) pour commencer.
4. **Networking → Inbound port rules :** n'ouvrez que le **RDP (3389)**, et
   limitez sa source à **votre propre IP**, pas `Any` — le portail Azure a
   un préréglage "My IP" prévu exactement pour ça.
5. Créez la VM et téléchargez le fichier `.rdp` proposé, ou connectez-vous
   avec n'importe quel client RDP à l'IP publique de la VM.
6. **Quand vous ne testez pas activement, désallouez (arrêtez) la VM**
   depuis le portail — Azure ne facture que le stockage en désalloué, pas
   le calcul, ce qui étire considérablement le crédit de 100 $ pendant la
   phase de validation.

### Voie B — VPS Forex spécialisé / VPS Windows bon marché

1. Inscrivez-vous, choisissez une offre dans le datacenter le plus proche
   (ping le plus bas) des serveurs de trading de votre broker, et payez.
2. Le fournisseur envoie les identifiants RDP par e-mail (IP, utilisateur,
   mot de passe) — généralement prêt en quelques minutes.
3. Connectez-vous avec un client RDP (Windows : "Connexion Bureau à
   distance" intégrée ; macOS/Linux : Microsoft Remote Desktop / Remmina).

---

## 4. Première connexion & durcissement de base

Une fois connecté en RDP en tant qu'Administrateur :

1. **Changez immédiatement le mot de passe Administrateur** — les
   fournisseurs en définissent souvent un temporaire que vous n'avez pas
   choisi.
2. Lancez **Windows Update** et redémarrez si demandé.
3. **Restreignez le RDP** aux seules IP depuis lesquelles vous vous
   connecterez réellement :
   - Azure : la source de la règle NSG, comme ci-dessus.
   - N'importe quelle machine Windows : Pare-feu Windows Defender avec
     fonctions avancées → Règles de trafic entrant → règles "Bureau à
     distance" → Portée → restreindre les adresses IP distantes à la
     vôtre.
   Laisser le RDP ouvert à `0.0.0.0/0` sur une machine qui détiendra des
   identifiants de broker est la manière la plus courante dont ces VPS se
   font compromettre — ne sautez pas cette étape.

---

## 5. Installer le terminal MT5 + la gateway

Suivez les étapes de l'Option B de `gateway/README.md` sur cette machine :

```powershell
# Python 3.12 Windows, puis :
pip install MetaTrader5 fastapi uvicorn pydantic
```

Installez le terminal MT5 de votre broker (`mt5setup.exe`), puis copiez le
dossier `gateway/` de ce repo sur le VPS (par ex. `C:\trading-bot\gateway`,
via le transfert de fichiers du presse-papiers RDP, un lecteur partagé, ou
`git clone`).

Connectez-vous au terminal avec votre compte (toujours **démo**, jusqu'à ce
que les critères de go-live de la Phase 9 soient remplis) et configurez-le
selon la section "Terminal configuration" de `gateway/README.md` (trading
algorithmique activé, imports DLL désactivés, etc.).

---

## 6. Redémarrage automatique après un reboot

Un VPS redémarre parfois (maintenance du fournisseur, Windows Update). Deux
choses doivent revenir sans que vous ayez à vous reconnecter en RDP à la
main :

### 6.1 La gateway — en tant que service NSSM

```powershell
nssm install mt5-gateway "C:\Python312\python.exe" ^
  "C:\trading-bot\gateway\run_gateway.py"
nssm set mt5-gateway AppDirectory "C:\trading-bot\gateway"
nssm set mt5-gateway AppEnvironmentExtra GATEWAY_SHARED_SECRET=<le-même-secret-que-TB_GATEWAY_SHARED_SECRET-dans-.env>
nssm start mt5-gateway
```

NSSM le relance automatiquement s'il plante, et le démarre au boot puisque
les services Windows démarrent avant toute connexion utilisateur.

### 6.2 Le terminal MT5 — connexion automatique + Planificateur de tâches

Le terminal est une application graphique, il a donc besoin d'une session
de bureau connectée pour tourner — ce qui veut dire activer la connexion
automatique Windows :

1. Lancez `netplwiz` (ou éditez
   `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon` —
   `AutoAdminLogon=1`, `DefaultUserName`, `DefaultPassword`) pour que
   Windows se connecte automatiquement à une session après un redémarrage,
   sans que personne ne se connecte en RDP.
2. **Planificateur de tâches → Créer une tâche** (pas "Tâche de base", pour
   avoir les options supplémentaires) :
   - Déclencheur : **à la connexion** (de l'utilisateur en auto-logon).
   - Action : démarrer `terminal64.exe` depuis l'endroit où MT5 l'a
     installé.
   - Onglet Général : **ne cochez pas** "Exécuter que l'utilisateur soit
     connecté ou non" ici — le terminal a besoin de la vraie session de
     bureau interactive fournie par l'auto-logon, pas d'une session de
     service cachée.
3. Redémarrez le VPS une fois pour vérifier : le bureau doit se connecter
   automatiquement, le terminal doit se lancer et se reconnecter, et
   `mt5-gateway` doit déjà tourner en tant que service.

---

## 7. Joindre la gateway depuis le Droplet backend — tunnel SSH

`gateway/README.md` recommande de lier la gateway à `127.0.0.1` et de la
joindre via un tunnel SSH ou WireGuard depuis le backend. Voici le côté
Windows, puisque Windows n'embarque pas de serveur SSH par défaut.

### 7.1 Activer OpenSSH Server sur le VPS

PowerShell (en Administrateur) :

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

### 7.2 Autoriser la clé du Droplet

Sur le **Droplet DigitalOcean** (voir `DEPLOY_DIGITALOCEAN.fr.md` Partie 6),
générez une paire de clés dédiée à ce tunnel si ce n'est pas déjà fait :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mt5_vps_tunnel -N ""
cat ~/.ssh/mt5_vps_tunnel.pub
```

Sur le **VPS Windows**, si le compte RDP est **administrateur**, OpenSSH
utilise un fichier différent du classique `~/.ssh/authorized_keys` — c'est
un piège classique :

```
C:\ProgramData\ssh\administrators_authorized_keys
```

Collez la clé publique du Droplet dans ce fichier, puis réappliquez les
permissions requises (OpenSSH refuse d'utiliser le fichier si les
permissions sont trop ouvertes) :

```powershell
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /grant "Administrators:F" /grant "SYSTEM:F"
```

(Si vous avez plutôt créé un utilisateur Windows **non-administrateur**
pour ça, le fichier classique `C:\Users\<user>\.ssh\authorized_keys`
fonctionne normalement.)

### 7.3 Pare-feu : restreindre le port 22 à l'IP du Droplet uniquement

Même principe que pour le RDP — ne laissez jamais le SSH ouvert au monde
entier sur une machine qui parle à votre broker :

- Azure : règle NSG entrante pour le port 22, source = l'IP publique du
  Droplet (une IP statique — réservez une "Reserved IP" DigitalOcean pour
  le Droplet afin que cette règle ne casse pas lors d'une reconstruction).
- N'importe quelle machine Windows : Pare-feu Windows Defender → Règles de
  trafic entrant → la règle `OpenSSH SSH Server (sshd)` → Portée →
  restreindre les adresses distantes à l'IP du Droplet.

### 7.4 Ouvrir et maintenir le tunnel depuis le Droplet

```bash
ssh -N -L 8787:127.0.0.1:8787 -i ~/.ssh/mt5_vps_tunnel administrator@<ip-du-vps>
```

Gardez-le actif à travers les reconnexions/redémarrages avec `autossh` + une
unité systemd sur le Droplet (à l'image de l'unité de la gateway dans
`DEPLOY_DIGITALOCEAN.fr.md` Partie 5) :

```ini
# /etc/systemd/system/mt5-tunnel.service
[Unit]
Description=Tunnel SSH vers le VPS Windows de la gateway MT5
After=network.target

[Service]
User=deploy
ExecStart=/usr/bin/autossh -M 0 -N \
  -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" \
  -i /home/deploy/.ssh/mt5_vps_tunnel \
  -L 8787:127.0.0.1:8787 administrator@<ip-du-vps>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo apt install -y autossh
sudo systemctl enable --now mt5-tunnel
```

Définissez `TB_GATEWAY_URL=http://127.0.0.1:8787` (et le
`TB_GATEWAY_SHARED_SECRET` correspondant) dans le `.env` du backend sur le
Droplet — le backend parle alors à la gateway exactement comme si elle
était locale.

---

## 8. Vérification de bout en bout

Depuis le Droplet, une fois le tunnel actif :

```bash
curl http://127.0.0.1:8787/health
```

`/health` ne nécessite pas l'en-tête `X-Gateway-Secret` (voir
`gateway/src/gateway/main.py`), donc un `200` ici confirme que le tunnel et
le processus de la gateway sont vivants, indépendamment du fait que le
secret partagé ou la connexion MT5 soient déjà correctement configurés.
Vérifiez ensuite le panneau MT5 Account de l'app / `make status` (depuis la
machine backend) pour confirmer que `terminal_connected` vaut `true`.

---

## 9. Checklist

- [ ] VPS dimensionné ≥ 2 vCPU / 4 Go, région choisie par ping vers le
      serveur du broker, pas seulement par le prix.
- [ ] Mot de passe Administrateur changé par rapport à celui du
      fournisseur.
- [ ] RDP (3389) restreint à votre propre IP.
- [ ] SSH (22) restreint à l'IP (statique) du Droplet uniquement.
- [ ] Gateway liée à `127.0.0.1` — jamais exposée publiquement.
- [ ] Service NSSM `mt5-gateway` installé et configuré en démarrage
      automatique.
- [ ] Connexion automatique Windows + tâche planifiée qui lance le
      terminal au redémarrage sans RDP manuel.
- [ ] Tunnel maintenu via `autossh` + systemd côté Droplet.
- [ ] `curl http://127.0.0.1:8787/health` réussit depuis le Droplet.
- [ ] Toujours un compte **démo** tant que les critères de go-live de la
      Phase 9 ne sont pas remplis (selon `gateway/README.md` et les règles
      de risque du projet).
