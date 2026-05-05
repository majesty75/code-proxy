# Air-gapped deployment to Windows 10 / 11 + WSL2

This guide moves a working UTA Analytics stack from a connected developer machine onto a fully air-gapped Windows server (no internet, no corporate proxy, no Microsoft Store reachable). It covers both **Windows 10** and **Windows 11** targets.

The strategy is the same for both:

1. On a **connected staging machine**, build everything once and assemble an offline bundle.
2. Copy the bundle to the target by USB / approved file transfer.
3. On the **air-gapped target**, install WSL from local files, import the prebuilt distro, load Docker images from tarballs, and start the stack.

Nothing on the target should ever try to reach the internet. The stack already follows this rule (see [commit 5572fac](../../uta-analytics/grafana/Dockerfile) — the ClickHouse plugin is baked into the Grafana image instead of pulled at startup). Apply the same thinking to anything you add later.

---

## 0. Confirm what the target actually is

Before you assemble a bundle, get this from the target machine (or its admin):

```powershell
# Run on the target if you can reach it once for inspection, or ask IT
[System.Environment]::OSVersion.Version
winver                                # build number, e.g. 19045 (Win10 22H2) or 22631 (Win11 23H2)
systeminfo | findstr /C:"OS Name" /C:"OS Version" /C:"System Type"
```

Decision table:

| Target | WSL install path |
|---|---|
| Windows 11 (any build) | **Path A** — standalone WSL MSI |
| Windows 10 22H2 (build 19045+) | Path A or **Path B** (either works; B is more conservative) |
| Windows 10 older than 22H2 | **Path B** — in-box WSL feature + kernel MSI |
| Windows Server 2019 / 2022 | Path B with server-specific notes (see §6) |

Also confirm:

- Admin rights on the target (you need them to enable Windows features).
- Hyper-V / virtualization is enabled in BIOS. On a physical server this is usually fine; on a VM the hypervisor admin must enable nested virtualization.
- Disk space: budget **~30 GB** for WSL distro + Docker images + ClickHouse data growth.

---

## 1. Assemble the offline bundle (on the connected machine)

Do all of this on the working developer machine where the stack already runs.

### 1.1 Export the WSL distro

```powershell
wsl --shutdown
wsl --list --verbose                   # find your distro name, e.g. Ubuntu-22.04
wsl --export Ubuntu-22.04 C:\airgap\uta-distro.tar
```

This captures the **entire** Linux filesystem: installed packages, your cloned repo, configs, ssh keys (be careful — see §7), everything. On the target you import this back as-is, no reinstall needed.

Set your default user **before** exporting, or you'll land as root on the target:

```bash
# inside WSL, before exporting
echo -e "[user]\ndefault=youruser" | sudo tee /etc/wsl.conf
```

### 1.2 Save Docker images

The stack uses these images (check `uta-analytics/docker-compose.yml` for the current list):

```powershell
mkdir C:\airgap\images
docker save apache/kafka:latest                  -o C:\airgap\images\kafka.tar
docker save clickhouse/clickhouse-server:latest  -o C:\airgap\images\clickhouse.tar
# Locally built images — make sure you've run `docker compose build` recently
docker save uta-analytics-parser:latest          -o C:\airgap\images\parser.tar
docker save uta-analytics-grafana:latest         -o C:\airgap\images\grafana.tar
docker save uta-analytics-watcher:latest         -o C:\airgap\images\watcher.tar
docker save timberio/vector:latest               -o C:\airgap\images\vector.tar
```

Run `docker images` first to confirm the exact tags — substitute whatever you see. Anything missing here will fail on the target with `Error response from daemon: pull access denied`.

### 1.3 Download the WSL installers

Grab these from a connected machine, drop them in the bundle:

| File | Source | Used by |
|---|---|---|
| `wsl.X.X.X.X.x64.msi` | https://github.com/microsoft/WSL/releases (latest stable) | Path A (Win11, Win10 22H2) |
| `wsl_update_x64.msi` | https://aka.ms/wsl2kernelmsi | Path B (older Win10) |

Grab **both** — they're small (~15 MB combined) and you may not know the exact target build until you're in front of it.

### 1.4 Project files

```powershell
# From the repo root on the connected machine
git archive --format=zip -o C:\airgap\uta-analytics-source.zip HEAD
```

The repo is also inside the WSL distro tar, so this is belt-and-braces for if you need to rebuild from source on the target. Skip if disk is tight.

### 1.5 Final bundle layout

```
C:\airgap\
├── uta-distro.tar              # ~5–15 GB, the WSL filesystem
├── images\
│   ├── kafka.tar
│   ├── clickhouse.tar
│   ├── parser.tar
│   ├── grafana.tar
│   ├── watcher.tar
│   └── vector.tar
├── installers\
│   ├── wsl.X.X.X.X.x64.msi     # Path A
│   └── wsl_update_x64.msi      # Path B
├── uta-analytics-source.zip    # optional
└── README-airgap.txt           # short note: target build, date, who built it
```

Burn / copy to whatever transfer media your environment allows.

---

## 2. Path A — Windows 11 or Windows 10 22H2+

On the air-gapped target, copy the bundle to e.g. `C:\airgap\` and run PowerShell **as Administrator**.

### 2.1 Enable Virtual Machine Platform

WSL2 needs this. It's an in-box feature — no download required:

```powershell
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
# Reboot
Restart-Computer
```

### 2.2 Install WSL from the MSI

```powershell
msiexec /i C:\airgap\installers\wsl.X.X.X.X.x64.msi /quiet
```

Verify:

```powershell
wsl --version
```

You should see WSL version, kernel version, and "WSLg" lines. If `wsl --version` errors, the MSI didn't install — check the build number again (the MSI requires Win10 22H2 or newer, or any Win11).

### 2.3 Set WSL2 default and import the distro

```powershell
wsl --set-default-version 2
mkdir C:\WSL\Ubuntu-22.04
wsl --import Ubuntu-22.04 C:\WSL\Ubuntu-22.04 C:\airgap\uta-distro.tar
wsl --set-default Ubuntu-22.04
wsl                                    # drops you into the imported distro
```

If you didn't set `/etc/wsl.conf` before exporting, fix the default user now:

```powershell
# in PowerShell, NOT inside WSL
ubuntu2204 config --default-user youruser
# If `ubuntu2204` is not on PATH (common with --import), edit /etc/wsl.conf inside WSL:
wsl -u root
echo -e "[user]\ndefault=youruser" >> /etc/wsl.conf
exit
wsl --terminate Ubuntu-22.04
```

Skip to **§4 Load Docker images and start the stack**.

---

## 3. Path B — Windows 10 (in-box WSL)

Use this when the target is Windows 10 older than 22H2, or when you want the most conservative install path.

### 3.1 Enable WSL and Virtual Machine Platform

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Restart-Computer
```

Both features ship with Windows 10 — no download needed for these specifically.

### 3.2 Install the WSL2 kernel update

The in-box WSL is WSL1 by default. To get WSL2 you need the kernel package:

```powershell
msiexec /i C:\airgap\installers\wsl_update_x64.msi /quiet
wsl --set-default-version 2
```

### 3.3 Import the distro

```powershell
mkdir C:\WSL\Ubuntu-22.04
wsl --import Ubuntu-22.04 C:\WSL\Ubuntu-22.04 C:\airgap\uta-distro.tar
wsl --set-default Ubuntu-22.04
wsl
```

Same default-user fix as §2.3 if needed.

**Limitations vs. Path A** — none of these usually matter for a server stack, but worth knowing:

- No systemd by default (older WSL doesn't honor `[boot] systemd=true`). Docker Engine inside WSL still runs fine via `service docker start`.
- No mirrored networking mode — WSL gets a NAT'd IP, not the host's. If external machines need to reach Kafka on the WSL host, you must `netsh interface portproxy` from the Windows host (see §5).
- No `wsl --update` (it tries to reach Microsoft). Stay on whatever kernel you installed; upgrade later by carrying in a newer `wsl_update_x64.msi`.

---

## 4. Load Docker images and start the stack

Inside the imported WSL distro:

```bash
# Confirm Docker is installed inside the distro (it should be — it came with the export)
docker --version

# If Docker daemon isn't running:
sudo service docker start
# Optional: auto-start on WSL launch (Path A with systemd: `sudo systemctl enable docker`;
# Path B without systemd: add `sudo service docker start` to your shell profile)
```

Copy image tars from Windows into WSL and load them:

```bash
mkdir -p ~/airgap-images
cp /mnt/c/airgap/images/*.tar ~/airgap-images/
cd ~/airgap-images
for f in *.tar; do echo "Loading $f"; docker load -i "$f"; done
docker images        # confirm everything is present with the expected tags
```

Bring the stack up from inside the distro (the repo is already there from the export):

```bash
cd ~/uta-analytics      # or wherever you cloned it before exporting
docker compose up -d
docker compose ps       # everything should be healthy within ~60s
```

Open Grafana from the Windows browser at `http://localhost:3005`.

---

## 5. Exposing the stack to other machines on the network

Edge nodes that ship logs to Kafka need to reach the WSL host. WSL2's NAT means `localhost:9092` works from the Windows host, but **not** from other machines on the LAN.

On the Windows host (admin PowerShell):

```powershell
# Find the WSL distro's IP
wsl hostname -I

# Forward Windows port → WSL port (repeat for each port you expose)
netsh interface portproxy add v4tov4 listenport=9092 listenaddress=0.0.0.0 `
  connectport=9092 connectaddress=<wsl-ip>
netsh interface portproxy add v4tov4 listenport=3005 listenaddress=0.0.0.0 `
  connectport=3005 connectaddress=<wsl-ip>

# Open the Windows firewall
New-NetFirewallRule -DisplayName "UTA Kafka"   -Direction Inbound -LocalPort 9092 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "UTA Grafana" -Direction Inbound -LocalPort 3005 -Protocol TCP -Action Allow
```

The WSL IP changes on every reboot. Either script the portproxy refresh on Windows boot, or use mirrored networking (Path A only — set `networkingMode=mirrored` in `%UserProfile%\.wslconfig`).

Also update `MAIN_SERVER_IP` in `uta-analytics/.env` to the **Windows host's** physical IPv4, not the WSL IP — that's what edge agents will connect to.

---

## 6. Windows Server notes

If "Windows 10" turns out to be Windows Server 2019 or 2022, the install paths differ:

- **Server 2022**: WSL2 is supported. Use Path B and additionally enable Hyper-V:
  ```powershell
  Install-WindowsFeature -Name Hyper-V, Hyper-V-PowerShell -IncludeManagementTools
  Restart-Computer
  ```
  Then proceed with the kernel MSI and import.

- **Server 2019**: WSL2 needs build 17763.1234+ and a manual Linux kernel install. Doable but fiddly — confirm the build number before committing to this OS. If you have a choice, deploy on Server 2022 or Win11 instead.

- **Server Core**: no GUI, no Docker Desktop. Run Docker Engine inside WSL directly (which is what we already do — Docker Desktop is not in our stack).

---

## 7. Things to verify before you ship the bundle

Run all of these on the connected staging machine and confirm green:

1. **No outbound network at runtime.** Add a temporary Windows Firewall rule blocking outbound on the WSL vEthernet adapter, then `docker compose down && docker compose up -d`. If anything fails, it's reaching out — fix the bake-it-in pattern before exporting.
2. **Image tags match what compose expects.** `docker compose config | grep image:` and confirm every line has a corresponding `.tar` in `images/`.
3. **No secrets you don't want shipped.** The exported tar includes everything in the WSL filesystem — `~/.ssh/`, `~/.aws/`, shell history, `.env` files with passwords. Audit before exporting:
   ```bash
   ls ~/.ssh ~/.aws 2>/dev/null
   grep -ri 'password\|secret\|token' ~/uta-analytics/.env
   history | tail -50
   ```
   Move or scrub anything that shouldn't leave your workstation.
4. **The bundle README** records target build number, bundle date, image tag list, and a sha256 of the distro tar. If the deployment fails three months later, you'll want this.

---

## 8. Updating an air-gapped deployment later

Same workflow in reverse:

1. On the connected machine, pull/build the new code, rebuild images, re-export the affected pieces.
2. Carry over **only the deltas** — usually just the rebuilt image tarballs and a `git diff` patch for configs. A full re-import is rarely needed.
3. On the target:
   ```bash
   docker load -i /mnt/c/airgap/images/parser-new.tar
   cd ~/uta-analytics && git apply /mnt/c/airgap/configs.patch
   docker compose up -d parser     # restart only what changed
   ```

Avoid `wsl --import` over a running deployment — it will overwrite the entire distro and lose any data not in named Docker volumes. ClickHouse data lives in the `ch-data` volume which survives container restart but **not** distro re-import. Back it up first:

```bash
docker run --rm -v uta-analytics_ch-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/ch-data-$(date +%F).tgz -C /data .
```
