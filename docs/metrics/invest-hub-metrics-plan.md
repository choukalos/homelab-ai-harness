# Investor Hub — Metrics Implementation Plan

> **Purpose:** Step-by-step instructions for instrumenting Investor Hub (React 19/Vite frontend + Express 5/TypeScript backend). This is the app-specific implementation of the universal observability strategy defined in `strategy.md`.

---

## Dependencies

### Backend (`server/`)

```bash
cd server
npm install prom-client
```

### Frontend (`client/`)

No new npm packages required. Plausible is loaded via a script tag (no build dependency).

---

## Phase 1 — Backend Metrics (Express)

### 1A. Create `server/src/middleware/metrics.ts`

```typescript
import { Registry, collectDefaultMetrics, Counter, Histogram } from 'prom-client';

// Each app gets its own registry with a prefix on default metrics
const register = new Registry();
collectDefaultMetrics({ register, prefix: 'investor_' });

// Custom: HTTP request duration histogram
export const httpRequestDuration = new Histogram({
  name: 'http_request_duration_seconds',
  help: 'HTTP request duration in seconds',
  register,
  buckets: [0.01, 0.05, 0.1, 0.5, 1, 3, 5, 10],
});

// Custom: HTTP request counter (by method, route, status)
export const httpRequestCount = new Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  register,
  labelNames: ['method', 'route', 'status'],
});

// Middleware: observe every request
export function metricsMiddleware(req, res, next) {
  const start = process.hrtime.bigint();
  res.on('finish', () => {
    const duration = Number(process.hrtime.bigint() - start) / 1e9;
    httpRequestDuration.observe(duration);
    httpRequestCount.inc({
      method: req.method,
      route: req.route?.path ?? req.path,
      status: String(res.statusCode),
    });
  });
  next();
}

// Endpoint: Prometheus scrapes GET /metrics
export function metricsHandler(_req, res) {
  res.setHeader('Content-Type', register.contentType);
  res.end(register.metrics());
}
```

### 1B. Wire into `server/src/app.ts`

Add imports and middleware to `server/src/app.ts`:

```typescript
// Add to existing imports
import { metricsMiddleware, metricsHandler } from './middleware/metrics';
```

Insert the middleware **after** existing middleware (`morgan`, `express.json`) and **before** all routes:

```typescript
// --- Metrics (before routes, so all requests are captured) ---
app.use(metricsMiddleware);
app.get('/metrics', metricsHandler);

// --- Health check ---
app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok' });
});

// --- API routes ---
app.use('/api/auth', authRoutes);
// ... rest of routes
```

### 1C. Custom Business Metrics (Optional, Phase 2)

After the basics are running, add custom counters for business logic. Examples:

```typescript
// In server/src/middleware/metrics.ts, add:

export const portfoliosCreated = new Counter({
  name: 'portfolios_created_total',
  help: 'Total portfolios created',
  register,
});

export const dailyUpdateDuration = new Histogram({
  name: 'daily_update_job_duration_seconds',
  help: 'Duration of the daily price update job',
  register,
  buckets: [1, 5, 10, 30, 60, 120, 300],
});
```

Then call them in the relevant controller/service:
```typescript
// In portfolio controller, after a successful create:
import { portfoliosCreated } from '../middleware/metrics';
// ...
portfoliosCreated.inc();

// In dailyUpdateJob.ts:
import { dailyUpdateDuration } from '../middleware/metrics';
// ...
dailyUpdateDuration.observe(durationSeconds);
```

---

## Phase 2 — Frontend Analytics (Plausible)

### 2A. Inject Plausible Script in `client/src/main.tsx`

Edit `client/src/main.tsx` to load Plausible in production only:

```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { AuthProvider } from './AuthContext';
import { BrowserRouter } from 'react-router-dom';

// Load Plausible analytics in production only
if (import.meta.env.PROD) {
  const script = document.createElement('script');
  script.defer = true;
  script.dataset.domain = import.meta.env.VITE_PLAUSIBLE_DOMAIN || 'investor-hub';
  script.src = `${import.meta.env.VITE_PLAUSIBLE_URL || 'http://localhost:8081'}/js/script.js`;
  document.head.appendChild(script);
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>
);
```

### 2B. Add Environment Variables

**`client/.env`** (for local development testing):
```
VITE_PLAUSIBLE_URL=http://localhost:8081
VITE_PLAUSIBLE_DOMAIN=investor-hub
```

**`client/.env.example`**:
```
VITE_PLAUSIBLE_URL=http://plausible:8081
VITE_PLAUSIBLE_DOMAIN=investor-hub
```

**Docker build** (for production builds in docker-compose):
```dockerfile
ARG VITE_PLAUSIBLE_URL
ENV VITE_PLAUSIBLE_URL=${VITE_PLAUSIBLE_URL}

ARG VITE_PLAUSIBLE_DOMAIN
ENV VITE_PLAUSIBLE_DOMAIN=${VITE_PLAUSIBLE_DOMAIN}
```

Update `client/Dockerfile` to accept these build args alongside the existing `VITE_API_BASE_URL`.

### 2C. Create Typed Event Tracking Helper

**New file: `client/src/lib/plausible.ts`**:

```typescript
// Typed event names for consistent tracking across the app
export type PlausibleEventName =
  | 'login'
  | 'logout'
  | 'create_portfolio'
  | 'delete_portfolio'
  | 'add_position'
  | 'edit_position'
  | 'delete_position'
  | 'view_dashboard'
  | 'view_portfolio'
  | 'view_watchlist'
  | 'view_analytics'
  | 'create_watchlist'
  | 'delete_watchlist'
  | 'symbol_search'
  | 'income_view';

declare global {
  interface Window {
    plausible?: (
      type: string,
      options?: { props?: Record<string, string> }
    ) => void;
  }
}

/**
 * Track a user event in Plausible.
 * Only fires in production (script is only loaded there).
 */
export function trackEvent(name: PlausibleEventName, props?: Record<string, string>): void {
  if (typeof window.plausible === 'function') {
    window.plausible(name, { props });
  }
}
```

### 2D. Add `trackEvent()` Calls to Key User Actions

Add tracking calls at the points where users complete meaningful actions. Here are the high-impact locations:

**Authentication** — in `client/src/AuthContext.tsx`:
```typescript
import { trackEvent } from './lib/plausible';

// Inside the login success handler:
trackEvent('login');

// Inside the logout handler:
trackEvent('logout');
```

**Dashboard** — in `client/src/pages/DashboardPage.tsx`:
```typescript
import { trackEvent } from '../lib/plausible';

// In the useEffect that loads the dashboard (fires on page view):
useEffect(() => {
  trackEvent('view_dashboard');
  // ... existing data loading logic
}, []);

// In the portfolio creation success callback:
trackEvent('create_portfolio', { name: portfolioName });

// In the portfolio delete confirmation handler:
trackEvent('delete_portfolio', { id: portfolioId });
```

**Portfolio Page** — in `client/src/pages/PortfolioPage.tsx`:
```typescript
// On page load:
trackEvent('view_portfolio', { id: portfolioId });

// After adding a position:
trackEvent('add_position', { ticker: symbol, shares: quantity });

// After editing a position:
trackEvent('edit_position', { id: positionId });

// After deleting a position:
trackEvent('delete_position', { id: positionId });
```

**Watchlist** — in `client/src/pages/WatchlistPage.tsx`:
```typescript
trackEvent('view_watchlist');
trackEvent('create_watchlist', { name: watchlistName });
trackEvent('delete_watchlist', { id: watchlistId });
```

**Analytics Page** — in `client/src/pages/AnalyticsPage.tsx` (if applicable):
```typescript
trackEvent('view_analytics');
```

**Symbol Search** — wherever symbol search happens:
```typescript
trackEvent('symbol_search', { query: searchTerm });
```

### 2E. Update Dockerfile for Build Args

**Edit `client/Dockerfile`** — add new build args:

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

ARG VITE_PLAUSIBLE_URL
ENV VITE_PLAUSIBLE_URL=${VITE_PLAUSIBLE_URL}

ARG VITE_PLAUSIBLE_DOMAIN
ENV VITE_PLAUSIBLE_DOMAIN=${VITE_PLAUSIBLE_DOMAIN}

# ... rest unchanged
```

---

## Phase 3 — Docker Compose Updates (App-Side)

### 3A. Update `docker-compose.yml` Client Service

Add build args so the client container knows where Plausible lives:

```yaml
  client:
    build:
      context: ./client
      dockerfile: Dockerfile
      args:
        VITE_API_BASE_URL: ${VITE_API_BASE_URL}
        VITE_PLAUSIBLE_URL: http://plausible:8081
        VITE_PLAUSIBLE_DOMAIN: investor-hub
```

### 3B. Add Monitoring Services

Add these services to the docker-compose (these are the same ones from `platform-metrics-plan.md`, included here for local dev):

```yaml
  # ─── Frontend Analytics ───
  plausible:
    image: ghcr.io/plausible/analytics:latest
    container_name: investor-plausible
    restart: unless-stopped
    ports:
      - "8081:8000"
    environment:
      DATABASE_TYPE: postgres
      DATABASE_URL: postgres://plausible:plausible@plausible-db:5432/plausible
      SECRET_KEY_BASE: ${PLAUSIBLE_SECRET_KEY:-dev-secret-not-for-prod}
      GOOGLE_APPLICATION_CREDENTIALS: ""
    depends_on:
      - plausible-db

  plausible-db:
    image: postgres:16-alpine
    container_name: investor-plausible-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: plausible
      POSTGRES_PASSWORD: plausible
      POSTGRES_DB: plausible
    volumes:
      - plausible_db_data:/var/lib/postgresql/data

  # ─── Metrics Collection ───
  prometheus:
    image: prom/prometheus:latest
    container_name: investor-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prom_data:/prometheus

  # ─── Metrics Visualization ───
  grafana:
    image: grafana/grafana:latest
    container_name: investor-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
    volumes:
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus

volumes:
  db_data:
  prom_data:
  grafana_data:
  plausible_db_data:
```

### 3C. Create `monitoring/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'investor-hub'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['server:4000']
        labels:
          app: 'investor-hub'
```

---

## Summary of File Changes

| File | Change |
|---|---|
| `server/package.json` | Add `prom-client` dependency |
| `server/src/middleware/metrics.ts` | **NEW** — Prometheus metrics middleware |
| `server/src/app.ts` | Add metrics middleware import + route |
| `client/src/main.tsx` | Add Plausible script injection (production-only) |
| `client/src/lib/plausible.ts` | **NEW** — Typed event tracking helper |
| `client/src/AuthContext.tsx` | Add `trackEvent('login')` / `trackEvent('logout')` |
| `client/src/pages/DashboardPage.tsx` | Add `trackEvent()` calls (view, create, delete) |
| `client/src/pages/PortfolioPage.tsx` | Add `trackEvent()` calls (view, add, edit, delete) |
| `client/src/pages/WatchlistPage.tsx` | Add `trackEvent()` calls (view, create, delete) |
| `client/Dockerfile` | Add `VITE_PLAUSIBLE_*` build args |
| `client/.env` | **NEW** — Local dev env vars for Plausible |
| `client/.env.example` | **NEW** — Template for Plausible env vars |
| `docker-compose.yml` | Add plausible, plausible-db, prometheus, grafana services |
| `monitoring/prometheus.yml` | **NEW** — Prometheus scrape config |
