> 🇫🇷 Version française : [WINDOWS_VPS_MT5_GATEWAY.fr.md](WINDOWS_VPS_MT5_GATEWAY.fr.md)

# Windows VPS setup for the MT5 gateway

This is the detailed setup for **Option B** from
[`gateway/README.md`](../gateway/README.md) and
[`DEPLOY_DIGITALOCEAN.md`](DEPLOY_DIGITALOCEAN.md) Part 5: a dedicated
Windows VPS running the MT5 terminal + gateway, reachable only through an
SSH tunnel from the backend Droplet. Use this once you're past paper
trading on Wine and preparing to go live.

---

## 1. Choosing where to host it

### Is there a Windows option in the GitHub Student Developer Pack?

**Yes — Microsoft Azure.** The pack includes an Azure for Students offer:
**$100 in Azure credit for 12 months**, no credit card required to
activate. Azure supports Windows Server VMs directly, unlike DigitalOcean.

**The catch:** Windows VMs on Azure carry a licensing surcharge on top of
the compute price. A size that's actually comfortable for the MT5
terminal + gateway (2 vCPU / 4 GB — `Standard_B2s`) runs roughly
**$60–70/month** for Windows in a typical region, once the free-tier B-series
discount doesn't apply. At that rate, $100 covers **a few weeks**, not 12
months, if the VM runs 24/7. It's genuinely useful for:

- The initial live-readiness test (Phase 9 go-live checklist) before
  committing to a paid VPS long-term.
- Short bursts — spin the VM up, validate, deallocate it (Azure doesn't
  bill compute for a *deallocated* VM, only storage) when not testing.

It is **not** the cost-effective choice for a bot that needs to stay
connected 24/7 for months. For that, a specialized Forex VPS is cheaper
and — more importantly — usually lets you pick a datacenter next to your
broker's servers, which lowers latency more than any generic cloud region
will.

### Cheaper, purpose-built alternatives

Specialized "Forex VPS" providers sell small Windows Server instances
pre-tuned for MT4/MT5, with the Windows license already included in the
price:

| Type | Typical price | Notes |
|---|---|---|
| Specialized Forex VPS (e.g. plans marketed for MT4/MT5) | **~$10–15/month** entry tier | Windows license included; datacenters chosen for broker proximity (NY4/LD4/Equinix-style locations); support used to MT5-specific quirks |
| Generic budget Windows VPS (Contabo, OVH, similar) | **~$7–15/month** | Cheaper raw compute, but you pick a generic datacenter region — ping your broker's server yourself before committing |
| Azure for Students (GitHub Pack) | $100 credit / 12 months, then pay-as-you-go | Best for short validation runs, not for sustained 24/7 live use — see licensing math above |
| AWS / GCP Windows instances | Comparable to Azure | No Windows-specific student credit in the GitHub pack for either; free tiers there are Linux-only |

**Recommendation:** validate on Azure's free credit first (it's already
"free" via the Student Pack), then move to a ~$10–15/month specialized
Forex VPS in your broker's region for the long-running live setup. Either
way, the steps below (from "Provisioning" onward) are the same once you
have RDP access to a Windows machine.

---

## 2. Sizing & region

- **Size:** 2 vCPU / 4 GB RAM minimum. The MT5 terminal is a full desktop
  GUI app plus the gateway's Python process plus Windows Server overhead —
  1 vCPU / 2 GB will be marginal.
- **OS:** Windows Server 2019/2022, or Windows 10/11 if that's what the
  provider offers — both work; the `MetaTrader5` package only needs a
  Windows Python, per `gateway/README.md`.
- **Region — this is the decision that actually matters for trading
  quality, more than price:** get the server name/address MT5 shows in its
  login dialog for your broker, and `ping` (or `tracert`) it from a couple
  of candidate regions/providers before renting anything. Pick the lowest
  round-trip time, not the cheapest listing.

---

## 3. Provisioning

### Route A — Azure (GitHub Student Pack credit)

1. Activate the Azure for Students offer from the GitHub Student Developer
   Pack (education.github.com/pack) — no credit card needed.
2. In the [Azure Portal](https://portal.azure.com), **Create a resource →
   Windows Server** (2022 Datacenter Azure Edition is a safe default).
3. Size: `Standard_B2s` (2 vCPU / 4 GB) to start.
4. **Networking → Inbound port rules:** only open **RDP (3389)**, and scope
   its source to **your own IP**, not `Any` — Azure's portal has a
   "My IP" preset for exactly this.
5. Create the VM and download the `.rdp` file it offers, or connect with
   any RDP client to the VM's public IP.
6. **When not actively testing, deallocate (stop) the VM** from the
   portal — Azure only bills storage while deallocated, not compute, which
   stretches the $100 credit considerably during the validation phase.

### Route B — Specialized Forex VPS / budget Windows VPS

1. Sign up, pick a plan in the datacenter closest (lowest ping) to your
   broker's trade servers, and pay.
2. The provider emails RDP credentials (IP, username, password) — usually
   ready within minutes.
3. Connect with an RDP client (Windows: built-in "Remote Desktop
   Connection"; macOS/Linux: Microsoft Remote Desktop / Remmina).

---

## 4. First login & baseline hardening

Once connected via RDP as Administrator:

1. **Change the Administrator password immediately** — providers often
   set a temporary one you didn't choose.
2. Run **Windows Update** and reboot if prompted.
3. **Restrict RDP** to only the IP(s) you'll actually connect from:
   - Azure: NSG rule's source, as above.
   - Any Windows box: Windows Defender Firewall with Advanced Security →
     Inbound Rules → "Remote Desktop" rules → Scope → restrict remote IP
     addresses to your own.
   Leaving RDP open to `0.0.0.0/0` on a box that will hold broker
   credentials is the single most common way these VPSs get compromised —
   don't skip this.

---

## 5. Install the MT5 terminal + gateway

Follow `gateway/README.md`'s Option B steps on this machine:

```powershell
# Windows Python 3.12, then:
pip install MetaTrader5 fastapi uvicorn pydantic
```

Install your broker's MT5 terminal (`mt5setup.exe`), then copy this repo's
`gateway/` folder to the VPS (e.g. `C:\trading-bot\gateway`, via RDP
clipboard file transfer, a shared drive, or `git clone`).

Log into the terminal with your (still **demo**, until Phase 9's go-live
criteria are met) account, and configure it per `gateway/README.md`'s
"Terminal configuration" section (algo trading enabled, DLL imports off,
etc.).

---

## 6. Auto-start after a reboot

A VPS reboots occasionally (provider maintenance, Windows Update). Two
things need to come back without you RDP-ing in by hand:

### 6.1 The gateway — as an NSSM service

```powershell
nssm install mt5-gateway "C:\Python312\python.exe" ^
  "C:\trading-bot\gateway\run_gateway.py"
nssm set mt5-gateway AppDirectory "C:\trading-bot\gateway"
nssm set mt5-gateway AppEnvironmentExtra GATEWAY_SHARED_SECRET=<the-same-secret-as-TB_GATEWAY_SHARED_SECRET-in-.env>
nssm start mt5-gateway
```

NSSM restarts it automatically if the process dies, and starts it at boot
since Windows services start before any user logs on.

### 6.2 The MT5 terminal — auto-logon + Task Scheduler

The terminal is a GUI app, so it needs a logged-on desktop session to run
in — that means enabling Windows auto-logon:

1. Run `netplwiz` (or edit
   `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon` —
   `AutoAdminLogon=1`, `DefaultUserName`, `DefaultPassword`) so Windows logs
   into a session automatically after a reboot, without anyone RDP-ing in.
2. **Task Scheduler → Create Task** (not "Basic Task", so you get the
   extra options):
   - Trigger: **At log on** (of the auto-logon user).
   - Action: start `terminal64.exe` from wherever MT5 installed it.
   - General tab: **do not** check "Run whether user is logged on or not"
     here — the terminal needs the actual interactive desktop session that
     auto-logon provides, not a hidden service session.
3. Reboot the VPS once to confirm: the desktop should auto-login, the
   terminal should launch and reconnect, and `mt5-gateway` should already
   be running as a service.

---

## 7. Reaching the gateway from the backend Droplet — SSH tunnel

`gateway/README.md` says to bind the gateway to `127.0.0.1` and reach it
over an SSH tunnel or WireGuard from the backend. Here's the SSH side,
since Windows doesn't ship an SSH server by default.

### 7.1 Enable OpenSSH Server on the VPS

PowerShell (as Administrator):

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

### 7.2 Authorize the Droplet's key

On the **DigitalOcean Droplet** (see `DEPLOY_DIGITALOCEAN.md` Part 6),
generate a dedicated keypair for this tunnel if you haven't already:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mt5_vps_tunnel -N ""
cat ~/.ssh/mt5_vps_tunnel.pub
```

On the **Windows VPS**, if the RDP account is an **administrator**, OpenSSH
uses a different file than the usual `~/.ssh/authorized_keys` — this trips
people up:

```
C:\ProgramData\ssh\administrators_authorized_keys
```

Paste the Droplet's public key into that file, then re-apply the required
ACL (OpenSSH refuses to use the file if permissions are too open):

```powershell
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /grant "Administrators:F" /grant "SYSTEM:F"
```

(If you instead created a **non-admin** Windows user for this, the normal
`C:\Users\<user>\.ssh\authorized_keys` works as expected.)

### 7.3 Firewall: restrict port 22 to the Droplet's IP only

Same principle as RDP — never leave SSH open to the world on a box that
talks to your broker:

- Azure: NSG inbound rule for port 22, source = the Droplet's public IP
  (a static IP — reserve a DigitalOcean "Reserved IP" for the Droplet so
  this rule doesn't break on a rebuild).
- Any Windows box: Windows Defender Firewall → Inbound Rules → the
  `OpenSSH SSH Server (sshd)` rule → Scope → restrict remote addresses to
  the Droplet's IP.

### 7.4 Open and persist the tunnel from the Droplet

```bash
ssh -N -L 8787:127.0.0.1:8787 -i ~/.ssh/mt5_vps_tunnel administrator@<vps-ip>
```

Keep it alive across reconnects/reboots with `autossh` + a systemd unit on
the Droplet (mirrors the gateway unit in `DEPLOY_DIGITALOCEAN.md` Part 5):

```ini
# /etc/systemd/system/mt5-tunnel.service
[Unit]
Description=SSH tunnel to the Windows MT5 gateway VPS
After=network.target

[Service]
User=deploy
ExecStart=/usr/bin/autossh -M 0 -N \
  -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" \
  -i /home/deploy/.ssh/mt5_vps_tunnel \
  -L 8787:127.0.0.1:8787 administrator@<vps-ip>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo apt install -y autossh
sudo systemctl enable --now mt5-tunnel
```

Set `TB_GATEWAY_URL=http://127.0.0.1:8787` (and the matching
`TB_GATEWAY_SHARED_SECRET`) in the backend's `.env` on the Droplet — the
backend then talks to the gateway exactly as if it were local.

---

## 8. Verifying end-to-end

From the Droplet, once the tunnel is up:

```bash
curl http://127.0.0.1:8787/health
```

`/health` doesn't require the `X-Gateway-Secret` header (see
`gateway/src/gateway/main.py`), so a `200` here confirms the tunnel and the
gateway process are both alive, independently of whether the shared secret
or MT5 login are configured correctly yet. Then check the app's MT5
Account panel / `make status` (from the backend host) to confirm
`terminal_connected` is `true`.

---

## 9. Checklist

- [ ] VPS sized ≥ 2 vCPU / 4 GB, region chosen by ping to the broker's
      server, not by price alone.
- [ ] Administrator password changed from the provider default.
- [ ] RDP (3389) restricted to your own IP.
- [ ] SSH (22) restricted to the Droplet's (static) IP only.
- [ ] Gateway bound to `127.0.0.1` — never exposed publicly.
- [ ] `mt5-gateway` NSSM service installed and set to auto-start.
- [ ] Windows auto-logon + Task Scheduler entry launches the terminal on
      reboot without manual RDP.
- [ ] Tunnel persisted via `autossh` + systemd on the Droplet side.
- [ ] `curl http://127.0.0.1:8787/health` succeeds from the Droplet.
- [ ] Still a **demo** account until Phase 9's go-live criteria are met
      (per `gateway/README.md` and the project's risk rules).
