# Windows Subsystem for Linux (WSL) Deployment Guide

If you are running the Main Server (Kafka, ClickHouse, Grafana, Parser) or an Edge Server on a Windows machine, the recommended and most performant approach is to use **WSL2** alongside **Docker Desktop**.

This guide outlines how to set up the UTA Analytics pipeline within a WSL environment.

## 1. Prerequisites
1. **Enable WSL2**: Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
   *Restart your computer if prompted.*
2. **Install Ubuntu**: By default, the command above installs Ubuntu. If you want a specific version, search the Microsoft Store for "Ubuntu 22.04 LTS".
3. **Install Docker Desktop**: Download and install Docker Desktop for Windows.
   - During setup, ensure **"Use the WSL 2 based engine"** is checked.
   - Open Docker Desktop -> Settings -> Resources -> WSL Integration.
   - Toggle the switch on for your Ubuntu distribution.

## 2. Setting Up the Repository
> **CRITICAL**: For maximum performance, do NOT clone the repository into the Windows filesystem (e.g., `C:\Users\...\Desktop`). Always clone it inside the native Linux filesystem within WSL.

1. Open your WSL Ubuntu terminal.
2. Clone the repository into your Linux home directory:
   ```bash
   cd ~
   git clone <your-repo-url> uta-analytics
   cd uta-analytics
   ```

## 3. Configuring the Main Server
If this Windows machine is acting as the **Main Server**:
1. Open the `.env` file in the `uta-analytics` directory.
   ```bash
   nano .env
   ```
2. Update the `MAIN_SERVER_IP` to your Windows machine's physical IPv4 address (e.g., `192.168.1.100`) so that external Edge servers can connect to Kafka.
   - *Note: If you are only testing locally within WSL, you can leave it as `host.docker.internal` or `localhost`.*
3. Boot the stack:
   ```bash
   docker compose up -d --build
   ```
4. Access Grafana from your Windows browser at `http://localhost:3005`.

## 4. Configuring the Edge Agent (Optional)
If this Windows machine is acting as a UTA Edge node generating logs:
1. Ensure the Windows path where logs are generated is accessible to WSL. WSL automatically mounts Windows drives under `/mnt/` (e.g., `C:\UTA_Logs` is accessible at `/mnt/c/UTA_Logs`).
2. Open `uta-analytics/vector/docker-compose.yml`.
3. Update the volume mount to point to your Windows log directory:
   ```yaml
   volumes:
     - /mnt/c/UTA_Logs:/uta/UTA_FULL_Logs:ro
   ```
4. Navigate to the `vector` directory and boot the agent:
   ```bash
   cd vector
   docker compose up -d --build
   ```

## 5. File Watcher & Test Completion
The `watcher` service uses Python's `watchdog` to detect when a file is moved (indicating test completion). Note that `watchdog` relies on `inotify` filesystem events. 

> **Important WSL limitation**: File system events (`inotify`) do not reliably propagate across the boundary from Windows (`/mnt/c/...`) to Linux. If your Windows software generates logs in `C:\UTA_Logs`, the `watcher` daemon inside Docker/WSL might not instantly detect the file move. 
> 
> **Solution**: For production edge nodes running Windows, it is highly recommended to run Vector and the Watcher script natively on Windows rather than inside WSL, or configure the board testing software to write logs directly into the `\\wsl$\Ubuntu\home\username\logs` path.
