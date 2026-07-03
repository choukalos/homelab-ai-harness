# Universal Observability Strategy

> **Purpose:** This document defines the observability architecture for all self-hosted applications. Read this in any new session when instrumenting a new app. It covers the shared infrastructure, per-app instrumentation patterns, and cross-technology conventions.

---

## Architecture Overview

All apps share a single monitoring infrastructure running on the production server. Individual apps send data to it — they never run their own monitoring stack.

```
┌─────────────────────────────────────────────────────────────────┐
│                    MONITORING INFRASTRUCTURE                     │
│                  (runs ONCE, shared by ALL apps)                 │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │  Plausible    │    │  Prometheus   │    │     Grafana      │   │
│  │  (user events)│    │  (metrics     │    │  (visualization) │   │
│  │  + PostgreSQL │    │   collection) │    │                  │   │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘   │
│         │                   │                      │             │
│         │          ┌────────┴────────┐             │             │
│         │          │  Node Exporter   │             │             │
│         │          │  (host metrics)  │             │             │
│         │          └──────────────────┘             │             │
│         │                                          Grafana       │
│         │                                          reads from    │
│         │                                          Prometheus    │
└─────────┼──────────────────────────────────────────┼──────────────┘
          │                                          │
     ┌────┴────┐                              ┌──────┴───────┐
     │         │                              │              │
  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐             ┌───▼────┐   ┌───▼──┐
  │React │  │PHP  │  │Ghost │  ...        │ MySQL  │   │Node  │
  │App   │  │App  │  │Blog  │             │Export. │   │Export│
  └──┬───┘  └──┬──┘  └──┬──┘              └───────┘   └──────┘
     │         │        │
  JS Snippet  SDK/     JS Snippet
  (Plausible)  /metrics (Plausible)
               endpoint
```

### Three Data Flows

| Flow | Direction | What it captures | Tool |
|---|---|---|---|
| **1. User Engagement** | Browser → Plausible | Page views, events, sessions, referrals, return visitors | Plausible Analytics (self-hosted) |
| **2. Backend Metrics** | App server → Prometheus | Request rate, latency, errors, custom counters | Language-specific Prometheus client |
| **3. Infrastructure** | Host/DB → Prometheus | CPU, memory, disk, DB connections, network | Node Exporter, MySQL Exporter |

All visualization happens in Grafana, which reads from Prometheus and can also read from Plausible's API.

---

## Platform Infrastructure (Shared)

These services run once and serve all apps. See `platform-metrics-plan.md` for setup instructions.

| Service | Image | Port | Purpose |
|---|---|---|---|
| **Plausible** | `ghcr.io/plausible/analytics` | 8081 | Privacy-first web analytics (GA replacement) |
| **Plausible DB** | `postgres:16-alpine` | 5432 (internal) | Plausible's database |
| **Prometheus** | `prom/prometheus` | 9090 | Metrics collection (scrapes app `/metrics` endpoints + exporters) |
| **Grafana** | `grafana/grafana` | 3000 | Dashboard visualization for all metrics |
| **Node Exporter** | `prom/node-exporter` | 9100 | Host-level metrics (CPU, RAM, disk, network) |
| **MySQL Exporter** | `prom/mysqld-exporter` | 9104 | Database-level metrics (connections, queries, slow queries) |

All are added to the production `docker-compose.yml` alongside the app services.

### Network Topology

```
Internet
  │
  ├─── app.yoursite.com:443  →  nginx  →  Client (React/PHP/etc.)
  ├─── plausible.yoursite.com:443  →  Plausible (analytics web UI)
  └─── grafana.yoursite.com:443  →  Grafana (dashboard UI)

Internal (Docker network)
  ├─── App → Plausible:8081 (JS script loads from here)
  ├─── Prometheus:9090 → App:/metrics (scrapes backend)
  ├─── Prometheus:9090 → Node Exporter:9100 (scrapes host)
  ├─── Prometheus:9090 → MySQL Exporter:9104 (scrapes DB)
  └─── Grafana:3000 → Prometheus:9090 (reads all metrics)
```

---

## Per-App Instrumentation Patterns

Each app adds two things: **frontend tracking** and **backend metrics**. The pattern is the same regardless of technology.

---

### Frontend: Plausible Analytics Script

Every web-facing app includes the Plausible script tag. It is **always** guarded to production-only.

#### JavaScript / React / Vite

```html
<script
  defer
  data-domain="<APP_DOMAIN>"
  src="<PLAUSIBLE_URL>/js/script.js"
></script>
```

In Vite/React, inject dynamically in `main.tsx`:
```typescript
if (import.meta.env.PROD) {
  const script = document.createElement('script');
  script.defer = true;
  script.dataset.domain = 'your-app-domain';
  script.src = `${import.meta.env.VITE_PLAUSIBLE_URL}/js/script.js`;
  document.head.appendChild(script);
}
```

Custom events (track user actions like "create_portfolio"):
```typescript
// Create a typed helper in your app
export function trackEvent(name: string, props?: Record<string, string>) {
  if (typeof window.plausible === 'function') {
    window.plausible(name, { props });
  }
}

// Usage anywhere in your app
trackEvent('create_portfolio', { name: portfolioName });
```

#### PHP (blade templates, WordPress, etc.)

Add to your base template's `<head>`:
```html
<!-- Only in production -->
<?php if ($_ENV['APP_ENV'] === 'production'): ?>
<script
  defer
  data-domain="your-app-domain"
  src="http://plausible:8081/js/script.js"
></script>
<?php endif; ?>
```

#### Ghost (blog)

Ghost has a built-in Code Injection feature:
1. Admin → Settings → Code Injection
2. In "Site Header Code", paste the Plausible script tag
3. That's it — Ghost already has its own dashboard for basic stats, but Plausible gives you richer event tracking

#### Mobile Apps (iOS / Android / React Native / Flutter)

No SDK needed. Use Plausible's HTTP API:
```
POST <PLAUSIBLE_URL>/api/event
Content-Type: application/json

{
  "domain": "mobile-app",
  "name": "screen_view",
  "url": "/portfolio-detail",
  "props": { "screen": "PortfolioDetail" }
}
```

Send this from any platform via standard HTTP (URLSession, OkHttp, fetch, Dio, etc.).

---

### Backend: Prometheus /metrics Endpoint

Every backend service exposes a `/metrics` endpoint that Prometheus scrapes. Each language has a first-party library.

#### Node.js (Express) — `prom-client`

```bash
npm install prom-client
```

```typescript
import { Registry, collectDefaultMetrics, Counter, Histogram } from 'prom-client';

const register = new Registry();
collectDefaultMetrics({ register, prefix: '<APP_PREFIX>_' });

const requestDuration = new Histogram({
  name: 'http_request_duration_seconds',
  help: 'HTTP request duration in seconds',
  register,
  buckets: [0.01, 0.05, 0.1, 0.5, 1, 3, 5, 10],
});

const requestCount = new Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  register,
  labelNames: ['method', 'route', 'status'],
});

// Middleware — add BEFORE all routes
export function metricsMiddleware(req, res, next) {
  const start = process.hrtime.bigint();
  res.on('finish', () => {
    const duration = Number(process.hrtime.bigint() - start) / 1e9;
    requestDuration.observe(duration);
    requestCount.inc({
      method: req.method,
      route: req.route?.path ?? req.path,
      status: String(res.statusCode),
    });
  });
  next();
}

// Endpoint — expose for Prometheus scraping
export function metricsHandler(_req, res) {
  res.setHeader('Content-Type', register.contentType);
  res.end(register.metrics());
}
```

Wired into Express:
```typescript
import { metricsMiddleware, metricsHandler } from './middleware/metrics';
app.use(metricsMiddleware);
app.get('/metrics', metricsHandler);
```

#### PHP — `promphp/prometheus_client_php`

```bash
composer require promphp/prometheus_client_php
```

```php
<?php
require 'vendor/autoload.php';
use PromPHP\Prometheus\MetricsRenderTextPlain;
use PromPHP\Prometheus\CollectorRegistry;
use PromPHP\Prometheus\Metrics\Counter;
use PromPHP\Prometheus\Metrics\Histogram;

$registry = new CollectorRegistry();

$requestDuration = new Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'route', 'status'],
    $registry
);

$requestCount = new Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'route', 'status'],
    $registry
);

// At the END of each request (or in a middleware/exit handler):
$requestDuration->observe($duration, [$method, $route, $status]);
$requestCount->inc([$method, $route, $status]);

// On the /metrics route:
if ($_SERVER['REQUEST_URI'] === '/metrics') {
    header('Content-Type: text/plain');
    echo (new MetricsRenderTextPlain())->render(
        $registry->getMetricFamilyNames()
    );
    exit;
}
```

#### Python — `prometheus_client`

```bash
pip install prometheus_client
```

```python
from prometheus_client import Counter, Histogram, generate_latest, start_http_server
from flask import request

request_count = Counter('http_requests_total', 'Total HTTP requests',
                        ['method', 'route', 'status'])
request_duration = Histogram('http_request_duration_seconds',
                             'HTTP request duration',
                             ['method', 'route', 'status'])

@app.after_request
def metrics(response):
    request_count.labels(request.method, request.path, response.status_code).inc()
    request_duration.labels(request.method, request.path, response.status_code).observe(duration)
    return response

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
```

---

### Prometheus Configuration

Each app adds a scrape target to the shared `prometheus.yml`:

```yaml
# In the shared monitoring/prometheus.yml

scrape_configs:

  - job_name: 'investor-hub'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['server:4000']
        labels:
          app: 'investor-hub'

  - job_name: 'my-php-app'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['php-app:8080']
        labels:
          app: 'my-php-app'

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'mysql-exporter'
    static_configs:
      - targets: ['mysql-exporter:9104']
```

The `app` label lets you filter across all services in Grafana dashboards.

---

## Conventions

### Naming

- **Prometheus metric prefixes:** Use `<app-name>_` prefix (e.g., `investor_http_request_duration_seconds`). Node.js `collectDefaultMetrics` supports `prefix` option.
- **Plausible `data-domain`:** Use the app's public domain (e.g., `investor.yoursite.com`, `blog.yoursite.com`). For internal tools, use the service name.
- **Prometheus job labels:** Always include an `app` label so Grafana dashboards can filter by application.

### Security

- `/metrics` endpoints should **never** be exposed publicly. They live on the Docker internal network.
- Grafana should be behind a reverse proxy with authentication (basic auth or Grafana's own auth).
- Plausible does not set cookies and does not track PII by default, but still consider your privacy policy.

### What to Track

**Frontend events** — track meaningful user actions, not every click:
- Authentication: `login`, `logout`
- Core workflows: `create_X`, `edit_X`, `delete_X`, `view_X`
- Feature usage: `use_feature_name`
- Errors: `error_displayed` (when a user-facing error occurs)

**Backend metrics** — the middleware handles the basics. Add custom counters for business logic:
- `investor_portfolio_created_total`
- `investor_daily_update_job_duration_seconds`
- `investor_failed_api_calls_total`

**Infrastructure** — Node Exporter + MySQL Exporter give you:
- CPU, memory, disk I/O, network
- MySQL connections, queries/s, slow queries, InnoDB buffer pool

### Production-Only

All instrumentation must be guarded to production:
- **Frontend:** `if (import.meta.env.PROD)` or equivalent env check
- **Backend:** `if (process.env.NODE_ENV === 'production')`
- **PHP:** `if ($_ENV['APP_ENV'] === 'production')`

---

## Grafana Dashboard Strategy

### Per-App Dashboards

After adding a new app's metrics, import a community dashboard as a starting point, then customize:

| App Type | Grafana Dashboard ID | Description |
|---|---|---|
| Node.js / Express | 1860 | Node.js Process Metrics |
| Generic HTTP | 3662 | HTTP Request Metrics |
| MySQL | 13959 | MySQL Overview |
| Node Exporter | 1860 | Node Exporter Full |

Import: Grafana → Dashboards → Import → paste the dashboard ID.

### Cross-App Dashboard

Create a "Fleet Overview" dashboard with:
- Request rate per app (group by `app` label)
- Error rate per app
- Host-level CPU/memory (from Node Exporter)
- DB connection count

### Plausible Dashboard

Plausible has its own web UI at `plausible.yoursite.com` — no Grafana needed for this. It provides:
- Page views, unique visitors, bounce rate
- Event tracking with custom event names
- Referral sources, browsers, operating systems
- Real-time visits

For combined views, Plausible's data can be imported into Grafana via their PostgreSQL backend, but the native UI is usually sufficient.

---

## Adding a New App (Checklist)

1. **Frontend:** Add Plausible script tag with correct `data-domain` (production-only)
2. **Frontend:** Create typed event tracking helper; add `trackEvent()` calls to key user actions
3. **Backend:** Add language-specific Prometheus client library
4. **Backend:** Create metrics middleware + `/metrics` endpoint (production-only)
5. **Prometheus:** Add `job_name` block to `prometheus.yml` with correct target and `app` label
6. **Grafana:** Import community dashboard, filter by new `app` label
7. **Docker:** Ensure the app container is on the same Docker network as Prometheus

---

## Related Documents

- `platform-metrics-plan.md` — How to set up the shared monitoring infrastructure on the production server
- `<app>/metrics-plan.md` — App-specific implementation details (e.g., `invest-hub-metrics-plan.md`)
