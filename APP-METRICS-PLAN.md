# Platform Metrics — Production Server Setup

> **Purpose:** One-time production server setup for the shared monitoring infrastructure (Plausible, Victoria Metrics, Grafana). This stack runs ONCE in `compose.monitoring.yml` and supports all apps (Invest Hub, Ghost, future apps).
>
> **This plan is aligned with the actual homelab architecture:** separated compose files, Victoria Metrics (not Prometheus), bare-metal MySQL on Thor, Cloudflare Tunnel for ingress, and Caddy as internal reverse proxy.

---

## Current Monitoring Stack (Already Deployed)

`compose/compose.monitoring.yml` already runs:

| Service | Port | Public? | Purpose |
|---|---|---|---|
| **Node Exporter** | 9100 | No | Host-level metrics (CPU, memory, disk) |
| **cAdvisor** | 8081 | No | Container-level metrics |
| **Victoria Metrics** | 9090 / 9091 | No | Metrics collection (Prometheus-compatible) |
| **Grafana** | 3001 | No (SSH tunnel) | Dashboard visualization |

### What's Missing

| Service | Needed? | Notes |
|---|---|---|
| **Plausible** | ✅ Yes | Web analytics (page views, events) — not yet deployed |
| **MySQL Exporter** | ✅ Yes | Bare-metal MySQL on `thor.local:3306` — not yet deployed |

---

## Architecture Overview

```
Internet
  → Cloudflare Tunnel
  → Caddy (port 80, auto_https off)
  → Internal services on public-net / ai-net / monitoring-net

Monitoring stack: compose.monitoring.yml (monitoring-net)
  ├── node-exporter:9100
  ├── cadvisor:8080
  ├── victoria-metrics:8428 (scrape config from prometheus.yml)
  ├── grafana:3000 → port-mapped to 3001 (SSH tunnel only)
  ├── plausible:8000 → port-mapped to 8082
  │    ├── /js/*, /api/* → public via Caddy + Cloudflare Tunnel
  │    └── admin UI → LAN-only at http://192.168.4.54:8082
  ├── plausible-db (internal PostgreSQL)
  └── mysql-exporter:9104 → connects to thor.local:3306 (bare-metal)

Apps on public-net:
  ├── invest-hub-server:4000 (/metrics endpoint)
  ├── invest-hub-client:80 (Plausible JS snippet)
  └── ghost-blog:2368 (Plausible JS snippet)
```

### Plausible Access Model

```
Internet visitors:
  https://plausible.choukalos.com/js/script.js     → Caddy → plausible:8000    ✅ Public
  https://plausible.choukalos.com/api/event         → Caddy → plausible:8000    ✅ Public
  https://plausible.choukalos.com/* (admin/login)   → Caddy → 404               🔒 Blocked

LAN admin:
  http://192.168.4.54:8082/                         → plausible:8000            🔒 LAN-only
```

Plausible's `PLAUSIBLE_HOSTNAME` is set to `https://plausible.choukalos.com` so the script
always generates correct public URLs regardless of how you access the admin UI.

### Three Data Flows

| Flow | Direction | What it captures | Tool |
|---|---|---|---|
| **1. User Engagement** | Browser → Plausible | Page views, events, sessions, referrals | Plausible Analytics |
| **2. Backend Metrics** | App → Victoria Metrics | Request rate, latency, errors, custom counters | Prometheus-compatible `/metrics` |
| **3. Infrastructure** | Host/DB → Victoria Metrics | CPU, memory, disk, containers, DB connections | Node Exporter, cAdvisor, MySQL Exporter |

---

## Step 1: Add Plausible + MySQL Exporter to Monitoring Compose

Edit `compose/compose.monitoring.yml` to add these services:

```yaml
  # ─── Frontend Analytics ───
  # Admin UI: LAN-only at http://192.168.4.54:8082
  # Script & API: public via Caddy at https://plausible.choukalos.com
  plausible:
    image: ghcr.io/plausible/analytics:latest
    container_name: plausible
    restart: unless-stopped
    networks:
      - monitoring-net
      - public-net          # needed so Caddy can reach it from edge-net
    ports:
      - "8082:8000"         # 8081 is taken by cAdvisor; LAN admin at 192.168.4.54:8082
    environment:
      DATABASE_TYPE: postgres
      DATABASE_URL: postgres://plausible:${PLAUSIBLE_DB_PASS}@plausible-db:5432/plausible
      SECRET_KEY_BASE: ${PLAUSIBLE_SECRET_KEY}
      PLAUSIBLE_HOSTNAME: https://plausible.choukalos.com
      GOOGLE_APPLICATION_CREDENTIALS: ""
      # No SMTP configured — admin setup via docker exec, resets via LAN admin UI
    depends_on:
      - plausible-db

  plausible-db:
    image: postgres:16-alpine
    container_name: plausible-db
    restart: unless-stopped
    networks:
      - monitoring-net
    environment:
      POSTGRES_USER: plausible
      POSTGRES_PASSWORD: ${PLAUSIBLE_DB_PASS}
      POSTGRES_DB: plausible
    volumes:
      - /home/chuck/data/plausible-db:/var/lib/postgresql/data

  # ─── Bare-metal MySQL Exporter ───
  mysql-exporter:
    image: prom/mysqld-exporter:latest
    container_name: mysql-exporter
    restart: unless-stopped
    networks:
      - monitoring-net
    # MySQL is bare-metal on Thor, not in Docker
    environment:
      DATA_SOURCE_NAME: '${INVEST_DB_USER}:${INVEST_DB_PASS}@tcp(thor.local:3306)/'
    extra_hosts:
      - "thor.local:192.168.4.54"
```

> **Port choice rationale:** cAdvisor already uses host port 8081. Plausible gets 8082 to avoid conflicts.

---

## Step 2: Connect Monitoring Network to App Networks

Victoria Metrics needs to scrape `/metrics` endpoints on `invest-hub-server` (on `public-net`). Two options:

### Option A: Add `public-net` to monitoring services (Recommended)

In `compose/compose.monitoring.yml`, add `public-net` as an external network reference:

```yaml
networks:
  monitoring-net:
    driver: bridge
  public-net:
    external: true          # created by compose.core.yml / compose.ghost.yml
```

Then add `public-net` to the services that need to reach apps:

```yaml
  victoria-metrics:
    # ... existing config ...
    networks:
      - monitoring-net
      - public-net
```

This lets Victoria Metrics discover `invest-hub-server:4000` directly by container name.

### Option B: Use `extra_hosts` on Victoria Metrics

If you prefer to keep networks isolated, add host-level resolution:

```yaml
  victoria-metrics:
    # ... existing config ...
    extra_hosts:
      - "host.docker.internal:host-gateway"
      # Add app host entries if needed for cross-network scraping
```

Then reference targets by host IP in the scrape config. **Option A is cleaner.**

---

## Step 3: Update Victoria Metrics Scrape Config

Edit `prometheus/prometheus.yml` to add app scrape targets:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  # ─── Existing: Infrastructure ───
  - job_name: victoria-metrics
    static_configs:
    - targets:
      - localhost:8428

  - job_name: node-exporter-local
    static_configs:
    - targets:
      - node-exporter:9100
      labels:
        instance: thor

  - job_name: cadvisor-local
    static_configs:
    - targets:
      - cadvisor:8080
      labels:
        instance: thor

  - job_name: litellm
    metrics_path: /metrics/
    static_configs:
    - targets:
      - host.docker.internal:4000
      labels:
        instance: litellm

  - job_name: node-exporter-matrix
    static_configs:
    - targets:
      - matrix:9100
      labels:
        instance: matrix

  - job_name: dcgm-matrix
    static_configs:
    - targets:
      - matrix:9400
      labels:
        instance: matrix

  - job_name: node-exporter-athena
    static_configs:
    - targets:
      - athena:9100
      labels:
        instance: athena

  - job_name: cadvisor-athena
    static_configs:
    - targets:
      - athena:9080
      labels:
        instance: athena

  # ─── NEW: App Metrics (scraped once apps add /metrics endpoints) ───
  - job_name: invest-hub
    metrics_path: /metrics
    static_configs:
    - targets:
      - invest-hub-server:4000
      labels:
        app: invest-hub

  # ─── NEW: Bare-metal MySQL ───
  - job_name: mysql-exporter
    static_configs:
    - targets:
      - mysql-exporter:9104
      labels:
        instance: thor-mysql
```

> **Note:** The invest-hub and mysql jobs will show as "down" until the app `/metrics` endpoints are implemented and the exporter is deployed. They'll auto-activate once the services are running.

---

## Step 4: Caddy — Add Plausible Script & API Routes (Admin Blocked)

Edit `caddy/Caddyfile` to proxy **only** the analytics script and event API to Plausible. Everything else (admin UI, login, setup) returns 404 from the internet. Admin is accessed via LAN at `http://192.168.4.54:8082`.

Add this handle block to the `:80 { ... }` section:

```caddyfile
@plausible host plausible.choukalos.com
handle @plausible {
    # Allow analytics script loading
    @plausible-script path /js/* /api/event
    reverse_proxy @plausible-script http://plausible:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Port 443
    }

    # Block everything else (admin UI, login, setup) from internet
    respond "404 Not Found" 404
}
```

Then in **Cloudflare Zero Trust → Tunnels → Public Hostnames**, add:
- `plausible.choukalos.com` → Service: `http://caddy:80`

No Cloudflare Access policy needed — Caddy itself blocks admin routes.

> **Caddy note:** Your Caddy uses `auto_https off` — Cloudflare Tunnel handles all TLS. The `respond 404` catches any non-script paths, so the admin UI is unreachable from the internet. Access it from LAN at `http://192.168.4.54:8082` (no HTTPS — LAN is trusted).

---

## Step 5: Environment Variables

Add to `.env`:

```bash
# ─── Monitoring / Analytics ───
PLAUSIBLE_SECRET_KEY=<generate: openssl rand -hex 64>
GRAFANA_ADMIN_PASSWORD=<already-set-or-choose-one>

# Plausible public URL (used by app build args / env vars)
PLAUSIBLE_URL=https://plausible.choukalos.com
```

Generate the Plausible secret key:
```bash
openssl rand -hex 64
```

---

## Step 6: Deploy the Monitoring Additions

```bash
# From /home/chuck/homelab/
./homelab.sh up monitoring

# Or if homelab.sh doesn't have a monitoring target yet:
cd compose
docker compose -f compose.monitoring.yml up -d

# Verify
docker compose -f compose.monitoring.yml ps
```

Expected new containers: `plausible`, `plausible-db`, `mysql-exporter`

### Verification Checklist

| Check | How | Expected |
|---|---|---|
| Plausible script (public) | `curl -sI https://plausible.choukalos.com/js/script.js` | `200 OK` |
| Plausible admin (LAN) | `http://192.168.4.54:8082` from Thor/LAN browser | Plausible login/setup page |
| Plausible admin (internet) | `curl -sI https://plausible.choukalos.com/login` | `404 Not Found` ✅ |
| Plausible API (public) | `curl -sI https://plausible.choukalos.com/api/event` | `200 OK` or `400` (expected without valid body) |
| MySQL Exporter | `docker exec mysql-exporter curl -s http://localhost:9104/metrics \| head` | MySQL metrics output |
| Victoria Metrics sees MySQL | SSH into thor → `curl http://localhost:9090/api/v1/query?query=up` | `mysql-exporter` shows `up = 1` |
| Grafana | `ssh -L 3001:localhost:3001 thor` → `http://localhost:3001` | Grafana login |

### Post-Deploy: Plausible Setup (2 min)

1. From a LAN machine, go to `http://192.168.4.54:8082`
2. Create an admin account (no SMTP needed — setup is done via the LAN UI)
3. Add your sites:
   - `invest.choukalos.com`
   - `choukalos.com` (Ghost blog)
4. The Plausible script URL for your apps will be `https://plausible.choukalos.com/js/script.js`

### Post-Deploy: Grafana Datasource (Already Provisioned)

Your Grafana already has Victoria Metrics provisioned via `grafana/provisioning/datasources/datasources.yml`. After adding new scrape targets to `prometheus.yml`:

```bash
# Reload Victoria Metrics scrape config
curl -X POST http://localhost:9090/-/reload

# Or restart the container
docker compose -f compose/compose.monitoring.yml restart victoria-metrics
```

---

## Per-App Instrumentation

See `APP-METRICS-STRATEGY.md` for detailed code patterns. This section covers the compose-level changes.

### Invest Hub

**Client (React/Vite):** Add Plausible build arg and env var:

```yaml
  invest-hub-client:
    build:
      context: ../../workspace/code/invest-hub/client
      dockerfile: Dockerfile
      args:
        VITE_API_BASE_URL: /api
        VITE_PLAUSIBLE_URL: https://plausible.choukalos.com
        VITE_PLAUSIBLE_DOMAIN: invest.choukalos.com
    # ... rest unchanged
```

**Server (Node/Express):** Add `/metrics` endpoint (see strategy doc for code). The server is on `public-net` and Victoria Metrics will be able to reach it once both are on the same network.

```yaml
  invest-hub-server:
    # Add the /metrics endpoint in code (see APP-METRICS-STRATEGY.md)
    # No compose changes needed beyond the build step
```

### Ghost Blog

Ghost doesn't need a backend `/metrics` endpoint (it's Node-based but has no native Prometheus support). Frontend tracking via Code Injection is sufficient:

1. Ghost Admin → Settings → Code Injection
2. In "Site Header Code", add:
```html
<script
  defer
  data-domain="choukalos.com"
  src="https://plausible.choukalos.com/js/script.js"
></script>
```

No compose changes needed for Ghost.

---

## Network Diagram (Updated for Actual Setup)

```
                    Internet
                       │
                    Cloudflare DNS
                       │
                 Cloudflare Tunnel
                       │
                    Caddy :80
                  (edge-net)
                       │
        ┌──────────────┼──────────────┐
        │              │              │
   public-net      ai-net     monitoring-net
        │              │              │
   ┌────┴────┐   ┌─────┴─────┐   ┌───┴──────────────────────┐
   │         │   │           │   │                           │
  ghost    invest  litellm   │  victoria-metrics   grafana
  -blog    -hub/   -proxy    │   :8428          :3000
           server/   -open-  │                           │
           client/   webui   │      ┌─────────┐    ┌────┴────┐
           -runner │      │      │ plausible │    │ node-    │
                    │      │      │ :8000    │    │ exporter │
                    │      │      │plausible-│    │ :9100    │
                    │      │      │ db       │    ├──────────┤
                    │      │      ├──────────┤    │ cadvisor │
                    │      │      │mysql-exp │    │ :8080    │
                    │      │      │:9104     │    └──────────┘
                    │      │      └──────────┘
                    │      │
            (monitoring-net bridges to
             public-net for scraping)

    ┌── Plausible access paths ──────────────────────┐
    │ Internet → Cloudflare → Caddy → plausible:8000  │
    │   /js/*, /api/*      → proxied (analytics)       │
    │   everything else  → 404 (admin blocked)          │
    │                                                   │
    │ LAN → http://192.168.4.54:8082 → plausible:8000  │
    │   all paths → admin UI (LAN-only, no TLS)         │
    └───────────────────────────────────────────────────┘
```

---

## Adding Future Apps

When you add a new app, you only need to:

1. **Victoria Metrics:** Add a new `job_name` block to `prometheus/prometheus.yml`, then reload:
   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```

2. **Plausible:** Add the new site domain in the Plausible web UI, then add the script tag to your app.

3. **Grafana:** Import a community dashboard and filter by the new `app` label, or create new panels.

4. **Caddy:** Add a handle block for the new subdomain if it needs public access.

5. **Cloudflare Tunnel:** Add the new hostname in the Zero Trust dashboard.

No new containers. No new infrastructure. Just config changes.

---

## Maintenance

### Data Retention

- **Victoria Metrics:** Set via `--retentionPeriod=1y` in compose.monitoring.yml (1 year). Adjust as needed.
- **Plausible:** Unlimited by default. Use the Plausible admin UI to set retention policies.
- **Grafana:** Does not store data itself — it queries Victoria Metrics in real time.

### Backups

```bash
# Backup Victoria Metrics data
tar czf vm-backup.tar.gz -C /home/chuck/data/victoria-metrics .

# Backup Grafana data (dashboards + configs)
tar czf grafana-backup.tar.gz -C /home/chuck/data/grafana .

# Backup Plausible DB
docker exec plausible-db pg_dump -U plausible plausible > plausible-backup.sql

# Backup MySQL (bare-metal)
mysqldump -u investor -p investorhub > invest-hub-backup.sql
```

### Upgrades

```bash
# Update monitoring stack
cd /home/chuck/homelab/compose
docker compose -f compose.monitoring.yml pull
docker compose -f compose.monitoring.yml up -d

# Or via homelab.sh (if it has a monitoring target)
./homelab.sh restart monitoring
```

### Dashboard Status

| Phase | Status |
|---|---|
| **Phase 1: Infrastructure** | ✅ Done — Node Exporter + cAdvisor dashboards already loaded in Grafana |
| **Phase 2: App Health** | Pending — requires `/metrics` endpoint on invest-hub-server |
| **Phase 3: MySQL Health** | Pending — requires mysql-exporter deployed; Grafana community dashboard ID `11326` |

### Plausible Admin Password Recovery

No SMTP is configured, so password resets can't go through email. Reset via the Elixir remote shell:

```bash
# Step 1: Enter the Plausible remote shell
docker exec -it plausible /app/bin/plausible remote

# Step 2: Reset the password (replace with your actual email and new password)
Plausible.Repo.get_by(Plausible.Auth.User, email: "your@email.com") |> Plausible.Auth.User.set_password("new_password") |> Plausible.Repo.update()

# Step 3: If you've forgotten your email address, list all users first:
Plausible.Repo.all(Plausible.Auth.User)

# Step 4: Exit the shell
exit
```

> **Tip:** Save your Plausible admin credentials in a password manager. Without SMTP, this is the only recovery path.
