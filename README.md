# PulseMon — Cross-Platform PC & Database Monitoring Tool

A lightweight, real-time monitoring tool built with Python, FastAPI, `psutil`, and WebSockets that works across **Linux**, **macOS**, and **Windows**.

![PulseMon Dashboard](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-blue)
![Python](https://img.shields.io/badge/Python-3.9%2B-brightgreen)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20%26%20WebSockets-teal)

---

## Features

- **System Metrics (Real-Time)**:
  - **CPU**: Overall utilization %, per-core breakdown, load averages (1m, 5m, 15m).
  - **RAM & Swap**: Total, used, available, percentage, and active swap metrics.
  - **Disk Storage**: Automatic mount point discovery across `/`, `/home`, `C:\`, `D:\`, with used/free storage bars.
  - **Disk Throughput**: Live read/write rate in KB/s or MB/s.
  - **Host Overview**: Hostname, OS distribution, kernel release, architecture, and uptime.
- **Database Metrics**:
  - **PostgreSQL**: Ping latency, active/total connections, database size, and version.
  - **MySQL / MariaDB**: Ping latency, `Threads_connected`, `Threads_running`, database size, and uptime.
  - **Resilience**: If a database is offline or unreachable, the tool continues monitoring system metrics without crashing, displaying clear diagnostic error messages.
- **Real-Time Web Dashboard**:
  - Auto-reconnecting WebSocket stream pushing updates every 2 seconds.
  - Responsive dark-mode dashboard with smooth live Chart.js graphs.
  - Alert banner when CPU, RAM, or Disk crosses configured thresholds (default: 90% CPU/RAM, 85% Disk).

---

## Quickstart

### 1. Prerequisites
- Python 3.9 or higher (tested with Python 3.9 – 3.14 on macOS, Linux, and Windows).

### 2. Setup Virtual Environment & Install Dependencies

```bash
# Clone or navigate to the project directory
cd "Monitoring Tool"

# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
# On macOS / Linux:
source .venv/bin/activate

# On Windows (Command Prompt / PowerShell):
# .venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Running the Application

#### A. Native Desktop Application (Default)
When launched without arguments, PulseMon opens directly as a **native desktop window application** (with no browser tabs, no terminal popups, and no localhost URL exposed):
```bash
python run.py
```

#### B. Headless Server Mode (Terminal / Background)
If you want to run it strictly as a web server on a fixed port:
```bash
python run.py --cli --port 8000
```

#### C. Database Diagnostics Mode
Test database connectivity without starting the monitoring engine:
```bash
python run.py --test-db all
```

---

## Standalone Desktop Packaging (.exe, .app, .AppImage)

PulseMon can be compiled into a single-file, zero-dependency native desktop application that end-users can run with a single click.

### Building Locally

```bash
# On Windows:
scripts\build_windows.bat
# Produces: dist\PulseMon.exe

# On macOS / Linux:
python3 scripts/build_executable.py
# Produces: dist/PulseMon.app (macOS) or dist/PulseMon (Linux)
```

### Automated Multi-Platform Releases (GitHub Actions)
The repository includes a ready-to-use GitHub Actions workflow (`.github/workflows/build-desktop-app.yml`). Whenever you push code or create a release tag:
1. **Windows Runner**: Compiles `PulseMon-Windows-x64.exe`
2. **macOS Runner**: Compiles `PulseMon-macOS.zip` (containing `PulseMon.app`)
3. **Linux Runner**: Compiles `PulseMon-Linux-x86_64`

Users can simply download the appropriate executable for their OS and double-click to launch!

---

## Database Connection Diagnostics & Troubleshooting

### Solving MySQL Error 1045 (`Access denied for user 'root'@'localhost'`)

If MySQL fails with `(1045, "Access denied...")`, it means the server is running, but the password or user grant does not match.

#### Option A: Supply Your Password in `config.yaml` or via Environment Variable
Update `config.yaml`:
```yaml
databases:
  mysql:
    host: "127.0.0.1"        # Always prefer 127.0.0.1 over localhost to force TCP
    user: "root"
    password: "YOUR_REAL_PASSWORD"
```
Or pass it via environment variable without modifying the file:
```bash
export MYSQL_PASSWORD="YOUR_REAL_PASSWORD"
python run.py --test-db mysql
```

#### Option B: Create a Dedicated Monitoring User (Recommended)
Instead of using `root`, create a read-only `pulsemon` user in MySQL:
```sql
CREATE USER 'pulsemon'@'127.0.0.1' IDENTIFIED BY 'PulseMonPass123!';
GRANT PROCESS, REPLICATION CLIENT ON *.* TO 'pulsemon'@'127.0.0.1';
GRANT SELECT ON information_schema.* TO 'pulsemon'@'127.0.0.1';
FLUSH PRIVILEGES;
```
Then in `config.yaml`:
```yaml
databases:
  mysql:
    host: "127.0.0.1"
    user: "pulsemon"
    password: "PulseMonPass123!"
```

---

## Environment Variable Overrides

Any setting in `config.yaml` can be overridden by environment variables:

| Variable | Description |
| :--- | :--- |
| `MYSQL_HOST` / `POSTGRES_HOST` | Database host (default: `127.0.0.1`) |
| `MYSQL_PORT` / `POSTGRES_PORT` | Port (default: `3306` / `5432`) |
| `MYSQL_USER` / `POSTGRES_USER` | Username |
| `MYSQL_PASSWORD` / `POSTGRES_PASSWORD` | Password |
| `MYSQL_DATABASE` / `POSTGRES_DATABASE` | Database name |
| `MONITOR_PORT` / `MONITOR_HOST` | Web server port/host (default: `8000` / `127.0.0.1`) |


---

## Configuration (`config.yaml`)

You can customize port numbers, polling intervals, database connection credentials, and alert thresholds in `config.yaml`:

```yaml
server:
  host: "127.0.0.1"
  port: 8000
  poll_interval: 2.0        # Seconds between metric samples
  history_buffer_size: 1800 # In-memory samples kept (~1 hour)

databases:
  postgresql:
    enabled: true           # Set to false to disable PostgreSQL
    name: "Primary PostgreSQL"
    host: "localhost"
    port: 5432
    user: "postgres"
    password: "your_password"
    database: "postgres"
    timeout: 3.0

  mysql:
    enabled: true           # Set to false to disable MySQL
    name: "Primary MySQL"
    host: "localhost"
    port: 3306
    user: "root"
    password: "your_password"
    database: "mysql"
    timeout: 3.0

alerts:
  cpu_threshold_percent: 90.0
  ram_threshold_percent: 90.0
  disk_threshold_percent: 85.0
```

---

## REST API Endpoints

PulseMon provides REST endpoints for automated scraping, external dashboards, or health probes:

- `GET /api/system/info`: Static hardware and OS specifications.
- `GET /api/metrics/current`: Most recent snapshot of CPU, RAM, Disks, and Databases.
- `GET /api/metrics/history?limit=100`: Last `N` historical metric samples.
- `GET /api/alerts`: Active warning and danger alerts.
- `WS /ws/live`: Real-time WebSocket connection for live streaming.

---

## Running as a Background Daemon / Service

### Linux (`systemd`)
Create `/etc/systemd/system/pulsemon.service`:
```ini
[Unit]
Description=PulseMon System and Database Monitoring Agent
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Monitoring Tool
ExecStart=/path/to/Monitoring Tool/.venv/bin/python run.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pulsemon
```

### macOS (`launchd`)
Create `~/Library/LaunchAgents/com.pulsemon.agent.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.pulsemon.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/Monitoring Tool/.venv/bin/python</string>
        <string>/path/to/Monitoring Tool/run.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```
Load the agent:
```bash
launchctl load ~/Library/LaunchAgents/com.pulsemon.agent.plist
```

### Windows (Task Scheduler or NSSM)
Use [NSSM (Non-Sucking Service Manager)](https://nssm.cc/):
```cmd
nssm install PulseMon "C:\path\to\Monitoring Tool\.venv\Scripts\python.exe" "C:\path\to\Monitoring Tool\run.py"
nssm start PulseMon
```

