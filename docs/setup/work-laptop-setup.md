# Setting up UTA Log Analytics on a corporate Windows + WSL2 laptop

This guide walks a fresh corporate laptop from "nothing installed" to "lab grid is up". It assumes:

- Windows 10/11 with admin rights to install software
- A corporate proxy / SSL inspection firewall that breaks `pip`, `apt`, `git`, and `docker pull` with errors like `SSL: CERTIFICATE_VERIFY_FAILED` or `handshake failed`
- WSL2 (Ubuntu 22.04+) — install if not already present

---

## 0. The corporate firewall problem in one paragraph

Corporate networks intercept TLS by terminating your connection at a proxy that re-signs traffic with the company's own root CA. If your tools don't trust that CA they reject the connection. The fix is one of:

- **Trust the corporate CA** in every tool's CA bundle (correct, secure way)
- **Disable verification** for the affected tool (fast, less secure — only when option A blocks you)

Get the corporate root CA from IT — usually a `.crt` or `.cer` file like `CompanyRoot.crt`. Save it somewhere persistent in WSL: `~/certs/CompanyRoot.crt`. We'll wire it into pip, apt, curl, git, docker, and Python.

---

## 1. WSL2 + Ubuntu

In Windows PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Reboot if asked. Open the new "Ubuntu 22.04" entry from the Start menu, set a username/password.

Inside WSL Ubuntu:

```bash
sudo apt update     # this will probably fail with TLS errors. Fix in §2.
```

---

## 2. Trust the corporate CA inside WSL Ubuntu

Save the `.crt` from IT into `~/certs/CompanyRoot.crt`. Then:

```bash
# 1. System CA store (apt, curl, wget, git)
sudo cp ~/certs/CompanyRoot.crt /usr/local/share/ca-certificates/CompanyRoot.crt
sudo update-ca-certificates
# Output should say: 1 added, 0 removed.

# 2. Verify
curl -I https://pypi.org           # should NOT error
sudo apt update                    # should now work
```

If `update-ca-certificates` says "0 added", make sure your file ends in `.crt` (not `.cer`) and is PEM-encoded. To convert DER → PEM:
```bash
openssl x509 -inform der -in ~/certs/CompanyRoot.cer -out ~/certs/CompanyRoot.crt
```

If your firewall presents a chain (root + intermediate), concat them all into one file.

---

## 3. Install base tools

```bash
sudo apt install -y git python3 python3-pip python3-venv build-essential
```

Confirm versions:
```bash
git --version           # >= 2.34
python3 --version       # >= 3.10
docker --version        # installed via Docker Desktop, see §5
```

---

## 4. Make Python / pip trust the corporate CA

There are **three** places Python may look for certs. We set all three.

```bash
# Persistent for your shell — add these to ~/.bashrc
cat >> ~/.bashrc <<'EOF'

# Corporate TLS (UTA project)
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export PIP_CERT=/etc/ssl/certs/ca-certificates.crt
EOF
source ~/.bashrc
```

Test:
```bash
pip3 install --user requests
python3 -c "import requests; print(requests.get('https://pypi.org').status_code)"
# should print 200
```

If `pip` still fails, fall back to the per-host trust flag (less secure):
```bash
pip3 config set global.trusted-host "pypi.org files.pythonhosted.org pypi.python.org"
```

---

## 5. Docker Desktop

1. Download Docker Desktop from `https://www.docker.com/products/docker-desktop/` on Windows. If the download fails through the corporate network, ask IT for a mirror or use the offline installer.
2. Install. In **Settings → Resources → WSL integration** enable your Ubuntu distro.
3. In **Settings → Docker Engine**, you may need to add a registry mirror if `docker pull` fails:

```json
{
  "registry-mirrors": [],
  "dns": ["8.8.8.8", "1.1.1.1"]
}
```

4. **Trust the corporate CA in Docker Desktop too** — copy `CompanyRoot.crt` to:
   - Windows: `%USERPROFILE%\.docker\certs.d\<registry-hostname>\ca.crt`
   - Or, on macOS/Linux: `~/.docker/certs.d/<registry-hostname>/ca.crt`

   For Docker Hub the hostname is `registry-1.docker.io`. Restart Docker Desktop afterwards.

5. Configure proxy if your firewall requires one (Settings → Resources → Proxies). Same proxy goes in `~/.bashrc`:

```bash
cat >> ~/.bashrc <<'EOF'

# Corporate proxy
export HTTP_PROXY=http://proxy.corp.example.com:8080
export HTTPS_PROXY=http://proxy.corp.example.com:8080
export NO_PROXY=localhost,127.0.0.1,kafka,clickhouse,parser,grafana,host.docker.internal,.svc,.local
EOF
source ~/.bashrc
```

Verify Docker can pull:
```bash
docker pull hello-world && docker run --rm hello-world
```

---

## 6. Git through the firewall

```bash
# Trust the same corporate CA git uses
git config --global http.sslCAInfo /etc/ssl/certs/ca-certificates.crt

# (only if you really can't get the CA installed — bad, but unblocks)
# git config --global http.sslVerify false
```

If using HTTPS with GitHub PAT (corporate often blocks SSH):
```bash
git config --global credential.helper store
# First push will prompt for username + PAT. They're saved in ~/.git-credentials.
```

If your corp uses an SSH proxy, `~/.ssh/config`:
```
Host github.com
    Hostname ssh.github.com
    Port 443
    User git
```
(GitHub allows SSH on port 443 specifically for this case.)

---

## 7. Clone and bootstrap UTA

```bash
cd ~
git clone https://github.com/<your-user>/uta.git    # or your fork's URL
cd uta/uta-analytics
chmod +x scripts/wsl-bootstrap.sh
./scripts/wsl-bootstrap.sh
```

What it does:

1. Validates Docker is reachable
2. Copies `.env.example → .env`
3. Builds the parser image
4. Starts Kafka + ClickHouse + parser + Grafana
5. Creates the `raw-logs` topic
6. Applies the schema (`uta.test_sessions`, `uta.interlude_snapshots`, `uta.interlude_metrics`, `uta.log_events`, `uta.parse_errors`)
7. Prints the URLs

Open in your browser:

- **Lab Grid** → http://localhost:3005/d/uta-lab-grid-v1/
- **Board Detail** → http://localhost:3005/d/uta-board-detail-v1/
- **ClickHouse** → http://localhost:8123 (`default` / `password`)
- Login: `admin` / `admin`

---

## 8. Get demo data flowing

### Option A — direct seed (fastest, populates 18 boards × 5–8 snapshots each)
```bash
pip3 install --user clickhouse-connect
python3 scripts/demo_seed.py
```

### Option B — through the full pipeline (Kafka → parser → ClickHouse)
The host can't resolve `host.docker.internal` on most corporate setups, so run the producer **inside a container on the docker network**:

```bash
docker run --rm --network uta-analytics_uta-net \
  -v "$(pwd)":/work -w /work uta-analytics-parser \
  python scripts/demo_kafka_producer.py --bootstrap kafka:9092 \
  --blocks 5 --rate 600 --rack 9 --shelf 1 --slot 1
```

Tail the parser as it works:
```bash
docker compose logs -f parser
```

### Option C — point Vector at a real log directory (production-shaped)

Vector isn't in the compose by default. To add it, drop a `vector` service into `docker-compose.yml`, mount your log directory at `/uta/logs`, and configure Vector to tail `*.log` and ship each line as JSON to Kafka topic `raw-logs` with envelope `{log_filename, server_ip, line, line_number}`. The parser already handles that envelope.

---

## 9. Pushing back to GitHub from behind the firewall

Once `git config http.sslCAInfo` is set (§6), pushing should "just work":

```bash
cd ~/uta
git checkout -b interlude-pivot
git add -A
git commit -m "feat: interlude-only parser + lab grid"
git push -u origin interlude-pivot
```

If push hangs at TLS handshake:
```bash
GIT_TRACE=1 GIT_CURL_VERBOSE=1 git push 2>&1 | head -40
```
Look for `SSL_ERROR_SYSCALL` or `unable to get local issuer certificate` — those mean the corporate CA isn't being picked up. Either:

- Re-export `GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt` for that one push, or
- Use SSH on port 443 (see §6).

If pushing through `https.proxy`:
```bash
git config --global http.proxy "$HTTP_PROXY"
git config --global https.proxy "$HTTPS_PROXY"
```

---

## 10. Day-to-day commands

```bash
docker compose ps                                  # what's running
docker compose logs -f parser                      # tail parser
docker compose restart parser                      # after editing parser code
docker compose down                                # stop, keep data
docker compose down -v                             # stop, wipe volumes (forces re-init)

# Re-seed demo data (idempotent — TRUNCATEs first)
python3 scripts/demo_seed.py

# Run the unit tests (no docker required)
cd parser/src && python3 -m unittest test_parsers
```

---

## 11. Troubleshooting cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `pip install` → `SSL: CERTIFICATE_VERIFY_FAILED` | Corporate CA not in trust store | §2 + §4 |
| `apt update` → `Certificate verification failed` | Same | §2 |
| `docker pull` → `x509: certificate signed by unknown authority` | Docker Desktop doesn't trust corporate CA | Add CA to `~/.docker/certs.d/...`; restart Docker Desktop |
| `docker pull` hangs | Proxy not set in Docker Desktop | Settings → Resources → Proxies |
| `git push` → `unable to get local issuer certificate` | git not using system CA | `git config --global http.sslCAInfo /etc/ssl/certs/ca-certificates.crt` |
| `docker compose up` succeeds but parser exits with `KafkaError: UNKNOWN_TOPIC_OR_PART` | Race: parser started before topic was created | `docker compose restart parser` |
| Grafana panels show "No data" but ClickHouse has rows | Time window too narrow OR `time_series` typo (use `timeseries`) | Widen time range; verify panel JSON `format: timeseries` |
| Demo producer from Windows host hangs | Kafka advertises `host.docker.internal:9092`, not resolvable from Windows host | Run producer inside a container on `uta-analytics_uta-net` (Option B above) |
| Status panel shows "No data" | Stat panel `color.mode: thresholds` with string-mapped values | Use `color.mode: fixed` + value mappings |

---

## 12. What's actually running

```
┌─────────────────────────────────────────────────────────┐
│ uta-analytics_uta-net  (docker bridge network)          │
│                                                         │
│  ┌─────────┐    ┌──────────┐    ┌──────────┐           │
│  │ Kafka   │───▶│ Parser   │───▶│ClickHouse│◀── Grafana │
│  │ :9092   │    │          │    │  :8123   │            │
│  │ raw-logs│    │ block    │    │  :9000   │            │
│  └─────────┘    │ buffer + │    └──────────┘            │
│       ▲         │ writer   │                            │
│       │         └──────────┘                            │
│  Producers      (consumes raw-logs, emits               │
│  (Vector or     interlude_snapshots +                   │
│   demo script)  interlude_metrics +                     │
│                 log_events rows)                        │
└─────────────────────────────────────────────────────────┘
```

The schema and dashboards are described in `docs/poc/10-interlude-only-pivot.md`.
