# Platform Metrics — Production Server Setup

> **Purpose:** One-time production server setup for the shared monitoring infrastructure (Plausible, Prometheus, Grafana). This stack runs ONCE and supports all apps (Investor Hub, Ghost, future PHP apps, mobile backends).

---

## What Gets Deployed

| Service | Port | Public? | Purpose |
|---|---|---|---|
| **Plausible** | 8081 | Yes → `plausible.yoursite.com` | Web analytics dashboard (page views, events) |
| **Plausible DB** (PostgreSQL) | — (internal only) | No | Database for Plausible |
| **Prometheus** | 9090 | No (internal only) | Metrics collection engine |
| **Grafana** | 3000 | Yes → `grafana.yoursite.com` | Dashboard visualization |
| **Node Exporter** | 9100 | No (internal only) | Host-level metrics (CPU, memory, disk) |
| **MySQL Exporter** | 9104 | No (internal only) | Database-level metrics |

Only Plausible (8081) and Grafana (3000) need to be publicly accessible via reverse proxy. Prometheus, Node Exporter, and MySQL Exporter stay on the internal Docker network.

---

## Step 1: Create Monitoring Config

On your production server, create the monitoring config directory:

```bash
# From your project root or a shared config directory
mkdir -p /opt/monitoring/config
```

Create `config/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Investor Hub backend
  - job_name: 'investor-hub'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['investor-server:4000']
        labels:
          app: 'investor-hub'

  # Node Exporter (host metrics)
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
        labels:
          instance: 'prod-server'

  # MySQL Exporter (database metrics)
  - job_name: 'mysql-exporter'
    static_configs:
      - targets: ['mysql-exporter:9104']
        labels:
          instance: 'investor-db'
    params:
      auth_module:
        - 'mysql_auth'
```

Create `config/mysql-auth.yml` (for MySQL Exporter):

```yaml
- targets:
    - 'investor-db:3306'
  labels:
    instance: 'investor-db'
  basic_auth:
    username: '${MYSQL_USER}'
    password: '${MYSQL_PASSWORD}'
```

> **Note:** The `MYSQL_USER` and `MYSQL_PASSWORD` should match your existing Investor Hub database credentials. Use envsubst or a secrets manager for the actual values at runtime.

---

## Step 2: Docker Compose (Production)

Create or modify your production `docker-compose.yml` to include the monitoring services. If you already have Investor Hub running, add these services alongside the existing ones:

```yaml
version: "3.9"

services:

  # ─── EXISTING: Investor Hub services ───
  db:
    image: mysql:8.0
    container_name: investor-db
    restart: unless-stopped
    command: --default-authentication-plugin=mysql_native_password
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-investor_hub}
      MYSQL_USER: ${MYSQL_USER}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    volumes:
      - db_data:/var/lib/mysql

  server:
    build:
      context: ./server
      dockerfile: Dockerfile
    container_name: investor-server
    restart: unless-stopped
    environment:
      NODE_ENV: production
      PORT: 4000
      DATABASE_URL: mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@db:3306/${MYSQL_DATABASE:-investor_hub}
      JWT_SECRET: ${JWT_SECRET}
      CORS_ORIGINS: ${CORS_ORIGINS}
    depends_on:
      - db

  client:
    build:
      context: ./client
      dockerfile: Dockerfile
      args:
        VITE_API_BASE_URL: ${VITE_API_BASE_URL}
        VITE_PLAUSIBLE_URL: https://plausible.${DOMAIN}
        VITE_PLAUSIBLE_DOMAIN: investor.${DOMAIN}
    container_name: investor-client
    restart: unless-stopped
    depends_on:
      - server

  # ─── NEW: Frontend Analytics ───
  plausible:
    image: ghcr.io/plausible/analytics:latest
    container_name: plausible
    restart: unless-stopped
    ports:
      - "8081:8000"
    environment:
      DATABASE_TYPE: postgres
      DATABASE_URL: postgres://plausible:plausible@plausible-db:5432/plausible
      SECRET_KEY_BASE: ${PLAUSIBLE_SECRET_KEY}
      GOOGLE_APPLICATION_CREDENTIALS: ""
      # Optional: set a SMTP if you want Plausible to send emails (admin invites, etc.)
      # SMTP_HOSTADDR: ${SMTP_HOSTADDR}
      # SMTP_PORT: ${SMTP_PORT}
      # SMTP_USER: ${SMTP_USER}
      # SMTP_PASS: ${SMTP_PASS}
      # SMTP_SECURITY: starttls
    depends_on:
      - plausible-db

  plausible-db:
    image: postgres:16-alpine
    container_name: plausible-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: plausible
      POSTGRES_PASSWORD: plausible
      POSTGRES_DB: plausible
    volumes:
      - plausible_db_data:/var/lib/postgresql/data

  # ─── NEW: Metrics Collection ───
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=90d'
      - '--web.enable-lifecycle'
    volumes:
      - /opt/monitoring/config/prometheus.yml:/etc/prometheus/prometheus.yml
      - /opt/monitoring/config/mysql-auth.yml:/etc/prometheus/mysql.yml
      - prom_data:/prometheus
    # Do NOT expose port 9090 publicly
    # Prometheus is internal-only; Grafana reads from it

  # ─── NEW: Metrics Visualization ───
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
      GF_SERVER_ROOT_URL: https://grafana.${DOMAIN}
      GF_SERVER_DOMAIN: grafana.${DOMAIN}
      GF_SERVER_HTTP_PORT: 3000
      # Auto-add Prometheus as a datasource on startup
      GF_INSTALL_PLUGINS: grafana-clock-panel,grafana-simple-json-datasource
    volumes:
      - grafana_data:/var/lib/grafana
      - /opt/monitoring/config/grafana-datasources.yml:/etc/grafana/provisioning/datasources/datasource.yml
    depends_on:
      - prometheus

  # ─── NEW: Infrastructure Exporters ───
  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    command:
      - '--path.rootfs=/host'
    volumes:
      - /:/host:ro,rslave
    # Do NOT expose port 9100 publicly

  mysql-exporter:
    image: prom/mysqld-exporter:latest
    container_name: mysql-exporter
    restart: unless-stopped
    environment:
      DATA_SOURCE_NAME: '${MYSQL_USER}:${MYSQL_PASSWORD}@tcp(db:3306)/'
    depends_on:
      - db
    # Do NOT expose port 9104 publicly

volumes:
  db_data:
  plausible_db_data:
  prom_data:
  grafana_data:
```

---

## Step 3: Grafana Datasource Provisioning

Create `config/grafana-datasources.yml` so Prometheus is auto-added as a Grafana datasource:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
```

Grafana will automatically connect to Prometheus on startup. No manual configuration needed.

---

## Step 4: Environment Variables

Create or update your `.env` file on the production server:

```bash
# ─── Existing Investor Hub vars ───
MYSQL_ROOT_PASSWORD=<your-root-password>
MYSQL_USER=<your-db-user>
MYSQL_PASSWORD=<your-db-password>
MYSQL_DATABASE=investor_hub
JWT_SECRET=<your-jwt-secret>
CORS_ORIGINS=https://investor.yoursite.com
VITE_API_BASE_URL=https://api.yoursite.com

# ─── NEW: Monitoring vars ───
DOMAIN=yourdomain.com
PLAUSIBLE_SECRET_KEY=<generate: openssl rand -hex 32>
GRAFANA_PASSWORD=<choose-a-strong-password>
VITE_PLAUSIBLE_URL=https://plausible.yoursite.com
VITE_PLAUSIBLE_DOMAIN=investor.yoursite.com
```

Generate the Plausible secret key:
```bash
openssl rand -hex 32
```

---

## Step 5: Reverse Proxy / HTTPS

You need a reverse proxy to put Plausible and Grafana behind HTTPS on subdomains. Options:

### Option A: Caddy (Recommended — simplest HTTPS)

Install Caddy and create a `Caddyfile`:

```caddyfile
# Plausible Analytics
plausible.yourdomain.com {
    reverse_proxy plausible:8000
}

# Grafana
grafana.yourdomain.com {
    reverse_proxy grafana:3000
}

# Existing: Investor Hub (if not already proxied)
investor.yourdomain.com {
    reverse_proxy investor-client:80
}

api.yourdomain.com {
    reverse_proxy investor-server:4000
}
```

Caddy automatically handles HTTPS certificates via Let's Encrypt.

### Option B: Nginx

```nginx
server {
    listen 443 ssl;
    server_name plausible.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://plausible:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443 ssl;
    server_name grafana.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://grafana:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Option B (alternative): Docker with Nginx container

If you prefer everything in Docker, add an nginx container as your reverse proxy with your cert files mounted as volumes.

---

## Step 6: Deploy and Verify

```bash
# From your project root (with docker-compose.yml and .env)
docker compose up -d

# Check all containers are running
docker compose ps

# Expected running services:
# db, server, client, plausible, plausible-db,
# prometheus, grafana, node-exporter, mysql-exporter
```

### Verification Checklist

| Check | URL | Expected |
|---|---|---|
| Plausible UI | `https://plausible.yourdomain.com` | Plausible login/setup page |
| Grafana UI | `https://grafana.yourdomain.com` | Grafana login (use GRAFANA_PASSWORD) |
| Prometheus (internal only) | `http://localhost:9090` (SSH tunnel) | Prometheus status page |
| Investor Hub /metrics | `http://server:4000/metrics` (SSH tunnel or internal) | Text metrics output |
| Node Exporter | `http://node-exporter:9100/metrics` | Host metrics |
| MySQL Exporter | `http://mysql-exporter:9104/metrics` | MySQL metrics |

### Post-Deploy: Grafana Setup (5 min)

1. Log into Grafana at `https://grafana.yourdomain.com`
2. Go to **Connections → Data Sources** — verify Prometheus is connected
3. Go to **Dashboards → Import**
4. Import dashboard ID **1860** (Node Exporter Full) — gives you host metrics
5. Import dashboard ID **13959** (MySQL Overview) — gives you DB metrics
6. Create a new dashboard for Investor Hub HTTP metrics:
   - Panel 1: `rate(http_requests_total{app="investor-hub"}[5m])` (request rate)
   - Panel 2: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{app="investor-hub"}[5m]))` (p95 latency)
   - Panel 3: `sum(rate(http_requests_total{app="investor-hub", status=~"5.."}[5m]))` (error rate)

### Post-Deploy: Plausible Setup (2 min)

1. Go to `https://plausible.yourdomain.com`
2. Create an admin account
3. Add your site: `investor.yourdomain.com`
4. Verify the Plausible script is being loaded by your Investor Hub frontend

---

## Adding Future Apps

When you add a new app (PHP, Python, etc.), you only need to:

1. **Prometheus:** Add a new `job_name` block to `/opt/monitoring/config/prometheus.yml`, then reload:
   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```

2. **Plausible:** Add the new site domain in the Plausible web UI, then add the script tag to your app.

3. **Grafana:** Import a community dashboard and filter by the new `app` label, or create new panels.

No new containers. No new infrastructure. Just config changes.

---

## Maintenance

### Data Retention

- **Prometheus:** Set via `--storage.tsdb.retention.time=90d` in the compose file (90 days by default). Adjust as needed.
- **Plausible:** Unlimited by default. Use the Plausible admin UI to set retention policies.
- **Grafana:** Does not store data itself — it queries Prometheus in real time.

### Backups

```bash
# Backup Prometheus data
tar czf prom-data-backup.tar.gz -C /path/to/prom_data .

# Backup Grafana data (dashboards + configs)
tar czf grafana-backup.tar.gz -C /path/to/grafana_data .

# Backup Plausible DB
docker exec plausible-db pg_dump -U plausible plausible > plausible-backup.sql
```

Add these to a cron job if desired.

### Upgrades

```bash
# Update all images
docker compose pull
docker compose up -d

# Or upgrade one service at a time
docker compose pull prometheus
docker compose up -d prometheus
```
