# Todo — Plausible: get analytics working (workstream 1)

- date: 2026-11-22
- status: open — **current blocker: first-user bootstrap (ingest broken until a
  user exists)**
- target: chuck + pi
- source: WS1 (engagement/usage instrumentation) of the agent-skills plan
  (`todo_agent_skills.md`). Chuck's call 2026-11-22: Plausible "is in itself its
  own plan to get working correctly that all this work depends on" — this is that
  plan.

## Why this is its own plan

Plausible is a **hard dependency for the measurement half**: skills Phase 3 (BA),
PM analytics (PM-6), strategist impact review (MKT-1), and the whole feedback
loop (gap G13). If ingest is broken, no data accumulates — and the historical
engagement/usage data that should exist by the time the BA skills are built
won't. So Plausible gets working correctly first, and the data clock starts.

## Decisions

- **Self-hosted** Plausible Community Edition **v3.2.0** (the tracker is
  integrated into the main container — there is no separate tracker service in
  v3)
- **Host: thor** (`compose/compose.monitoring.yml`) — same host as invest-hub;
  the snippet is served from the homelab, no third-party dependency
- **Public surface**: `https://plausible.choukalos.com` via Caddy — **only**
  `/js/*` (tracker script) and `/api/event` (ingest). The admin UI is
  deliberately blocked from the internet (Caddy responds 404 to everything
  else) — by design, not a bug
- **Admin UI**: LAN-only at `http://192.168.4.54:8082`
- **DNS**: Cloudflare-proxied (orange cloud)
- **Data**: `/home/chuck/data/plausible-db` (postgres 16),
  `/home/chuck/data/plausible-events-db` (clickhouse 24.12)

## Diagnosis (2026-11-22)

**Symptoms reported:** (1) unable to access the website on the homelab LAN,
(2) public ingest point uncertain.

**Findings:**

- App is healthy: up 35h, no errors in logs, cache warmers running
- LAN direct (`192.168.4.54:8082`) responds — but **every route 302-redirects
  to `/register`**
- Public: `/js/script.plausible.js` → 302 `/register` (should be 200 + script);
  `/api/event` → 302 `/register` (should be 204); `/` → 404 (by design — admin
  UI blocked)
- **Root cause: no user account has been created.** Plausible v3 runs a
  first-user bootstrap: until the first account exists, the app redirects
  *everything* — including ingest and the tracker script — to `/register`.
- So: the "can't access on LAN" symptom **is** the registration page (the
  first-time-setup entry point, working as designed); the "ingest broken"
  symptom is **real** and has the same cause.

## Plan

### P1 — Create the first user (chuck) ← current blocker

- `http://192.168.4.54:8082/register` — create the account (email + password)
- Verify: `/` serves the login page (no more `/register` redirect);
  `/api/event` returns 204; `/js/script.plausible.js` returns 200
- Note: `DISABLE_REGISTRATION=true` — the first user is the only one creatable
  via the form; credentials are the admin UI login

### P2 — Create the 3 sites (chuck, in the admin UI)

- `choukalos.com` (Homelab Blog)
- `invest.choukalos.com` (Invest Hub)
- Bluebovine — canonical domain from the Astro `site` field (confirm at
  execution; the site is on Cloudflare Pages, not thor Caddy)
- Note the site IDs/domains for the snippet step

### P3 — Add the snippet to the 3 sites (per-site deploy)

- Snippet (per site):
  `<script defer data-domain="<site>" src="https://plausible.choukalos.com/js/script.plausible.js"></script>`
- Homelab Blog: Hugo head (config or layout partial) → `deploy.sh`
- Invest Hub: app head → push (deploy gate: "push to production" only)
- Bluebovine: Astro head → CF Pages auto-deploy on push to main

### P4 — End-to-end verification

- Send a test event:
  `curl "https://plausible.choukalos.com/api/event?u=<url>&c=<siteid>"` → 204
- Visit each live site; confirm sessions appear in the Plausible dashboard
- Confirm the snippet loads in page source (200, not 302) on all 3 sites

### P5 — WS1 deep (later; skills Phase 3 prereq)

- Feed Plausible into data-hub (API with per-site token, or scheduled export —
  decide at P5 start)
- report-hub/Grafana dashboards (product KPIs)
- KPI definitions with BA-1 (skills Phase 3)

## Architecture (as deployed)

- `plausible` — `ghcr.io/plausible/community-edition:v3.2.0`,
  `192.168.4.54:8082→8000` (LAN-only bind), `BASE_URL=https://plausible.choukalos.com`,
  `DISABLE_REGISTRATION=true`, on `monitoring-net` + `public-net`
- `plausible-db` — postgres:16-alpine (healthcheck `pg_isready`)
- `plausible-events-db` — clickhouse 24.12-alpine (low-resource overrides,
  ipv4-only, backups config)
- `ai-redis` — shared redis
- Caddy (`:80`, public via Cloudflare): `host plausible.choukalos.com` →
  `/js/*` and `/api/event` → `http://plausible:8000` (with
  `X-Forwarded-Proto https`); everything else → 404

## Open questions

1. First-user email — chuck's? (it becomes the admin UI login)
2. Bluebovine's canonical domain (confirm from the Astro config)
3. P5 feed design: Plausible API (per-site, token) vs. scheduled export —
   decide when P5 starts

## Definition of done

- First user created; admin UI accessible on LAN (login works)
- 3 sites exist in Plausible
- Snippet deployed on all 3 live sites (verified in page source)
- Test event + real visits visible in the dashboard (ingest verified
  end-to-end)
- P5 tracked as a separate task (WS1 deep)
