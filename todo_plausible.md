# Todo — Plausible: get analytics working (workstream 1)

- date: 2026-11-22
- status: **P1–P5 DONE 2026-11-27** —
  first user created, 3 sites created, snippet wired + deployed on all 3 live
  sites, end-to-end ingest verified. P5: Plausible → data-hub feed (daily
  scheduled export, path A) + Grafana Product KPIs dashboard + the `plausible-kpi`
  KPI report skill (BA-1 `kpi-reporting`) are all live. Only the final KPI
  *set* is still refined with BA-1 (skills Phase 3).
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

## Diagnosis 2 — registration hang (2026-11-27)

**Symptom:** `/register` loads in a browser but the LiveView form never
activates — no errors, just a frozen page; first-user creation impossible.

**Root cause:** `BASE_URL=https://plausible.choukalos.com` while the admin UI
is only reachable over plain HTTP on the LAN. Plausible derives two things
from `BASE_URL`, and both broke the LiveView WebSocket join:

1. `secure_cookie` (from the https scheme) — the `_plausible_key` session
   cookie was set `Secure`; browsers drop Secure cookies over HTTP, so the WS
   connection arrived with no session cookie → `connect_info[:session] = nil`
   → LiveView answers `"stale"` → the form hangs.
2. `check_origin` on the LiveView socket (from the endpoint host) — the LAN
   browser sends `Origin: http://192.168.4.54:8082`, which the server
   rejected (403 on the WS handshake) because it only accepted
   `https://plausible.choukalos.com`.

**Fix (one env change):** `BASE_URL=http://192.168.4.54:8082`
(`compose/compose.monitoring.yml`). The public tracker is unaffected —
`script.plausible.js` derives its event endpoint from the script's `src`
attribute, not `BASE_URL`.

Also bumped the image `v3.2.0 → v3.2.2` (patch release, already pulled and
verified running) while in there.

**Verified end-to-end (2026-11-27):** cookie no longer `Secure`; WS handshake
101 with the LAN Origin; LiveView `phx_join` on the register form returns
`status: ok` with the rendered form (replayed the exact browser join payload
— top-level `url`, `?vsn=2.0.0&_csrf_token=...` query, session cookie).

**Gotchas found while tracing (for the record):**

- The register form is a LiveView, not a plain POST form — `POST /register`
  404s by design.
- The WS URL needs `?vsn=2.0.0` (server otherwise uses the V1 map serializer)
  and `?_csrf_token=<meta tag>` (session is only honored with a valid CSRF
  token in the query).
- The join payload's `url` key is **top-level** (not inside `params`); without
  it the server mounts with `:not_mounted_at_router` params and the register
  view's `assign_new(:invitation, ...)` crashes.
- Plug.Crypto 1.2.5 tokens are JWT-style (HMAC over `protected.payload`),
  which trips up naive HMAC verification when debugging tokens.

## Plan

### P1 — Create the first user (chuck) ✅ DONE 2026-11-27

- Created via `http://192.168.4.54:8082/register` (email + password).
  Credentials stored in gitignored `.env` as `PLAUSIBLE_ADMIN_EMAIL` /
  `PLAUSIBLE_ADMIN_PASSWORD` (never in chat/logs).
- Verified: `users` table has the admin (id=1); `/` serves the login page
  (no more `/register` redirect).
- Note: `DISABLE_REGISTRATION=true` — the first user is the only one creatable
  via the form; credentials are the admin UI login.

### P2 — Create the 3 sites ✅ DONE 2026-11-27

- `choukalos.com` (Homelab Blog) — **site_id 1**
- `invest.choukalos.com` (Invest Hub) — **site_id 3**
- `bluebovinegroup.com` (Bluebovine, CF Pages) — **site_id 4**
- All 3 timezones set to `America/Chicago`.
- Note: the `/api/v1/sites` site-creation API is Enterprise-only; sites were
  created via the web UI (login → `POST /sites` with CSRF).

### P3 — Add the snippet to the 3 sites ✅ DONE 2026-11-27

- Snippet (per site) — **generic `/js/script.js` + `data-domain`** (the
  personalized `pa-<id>.js` / `script.plausible.js` forms 404 on this
  instance; `script.js` is the correct tracker path):
  `<script defer data-domain="<site>" src="https://plausible.choukalos.com/js/script.js"></script>`
- Homelab Blog: `layouts/_default/baseof.html` head → built with Hugo
  v0.170.1 (installed to /tmp on thor) → `deploy.sh` → `deploy` branch →
  git-sync. **Live** (commit d325a6d).
- Invest Hub: `client/index.html` — replaced the stale `pa-35qyOpiCssHupkqZTwTlz.js`
  (404) with the generic snippet → push to main → GitHub Actions Docker
  deploy. **Live** (commit b75034e).
- Bluebovine: `src/layouts/BaseLayout.astro` head (`is:inline` so Astro passes
  it through) → push to main → CF Pages auto-deploy. **Live** (commit a5e4fd1).

### P4 — End-to-end verification ✅ DONE 2026-11-27

- Tracker script: `https://plausible.choukalos.com/js/script.js` → 200.
- Test event per site (`POST /api/event`, `Content-Type: text/plain`, JSON
  `{d,u,n,p}`) → **202** for all 3 domains.
- Events persisted in ClickHouse `plausible.events_v2` (site_ids 1, 3, 4 all
  show the `snippet_wiring_test` event).
- Snippet confirmed in served page source on all 3 live sites (choukalos.com,
  invest.choukalos.com, bluebovinegroup.com).
- Note: events land in `events_v2` (not the legacy `events` table).

### P5 — WS1 deep (feed + dashboard + KPI report skill — DONE 2026-11-27)

- ✅ **Feed Plausible into data-hub** (path A — the plan's intended flow).
  Uses data-hub's existing **v2 generic-datasets** framework (the robust,
  reusable ingest path for any project/report — see `docs/data-hub-ingest.md`):
  - `scripts/plausible-export.sh` — daily aggregates (pageviews, unique
    visitors, custom events) per site → `plausible-daily-YYYY-MM-DD.csv` into
    the data-hub inbox.
  - `scripts/plausible-register-dataset.sh` — registers the `plausible`
    dataset (target `hub.ds_plausible`, key `(date, site_id)`, explicit
    schema; idempotent upserts verified: re-run = `new=0, upd=N`).
  - `scripts/systemd/plausible-export-daily.{service,timer}` +
    `scripts/plausible-install-timer.sh` — daily 02:00 UTC export.
- ✅ **Grafana Product KPIs dashboard** (`grafana/dashboards/product-kpis.json`,
  uid `product-kpis-dashboard`) on a new read-only **MySQL** datasource
  (`dh_reports` on `hub.*`; `grafana/provisioning/datasources/mysql.yml`).
  Panels: 7-day stats (pageviews / unique visitors / custom events), 30-day
  pageview trend, per-site breakdown. (report-hub can also read `hub.*` via
  `dh_reports`; its UX organization is a separate follow-up.)
- ✅ **KPI report skill** (`agents-skills/plausible-kpi/`, registered + enabled
  in the LiteLLM Skill Hub) — the BA-1 `kpi-reporting` step. A deterministic
  script (`tools/plausible_kpi_report.py`) queries Plausible ClickHouse for a
  lookback window and writes a Markdown KPI report (overview, per-site
  breakdown, daily trend, top pages, top countries, custom events). Runs on
  thor via `docker exec`; `--days` / `--sites` / `--top` / `--out` flags.
  The final KPI *set* is still refined with BA-1, but the report artifact
  step is built and live — P5 is complete.

## Architecture (as deployed)

- `plausible` — `ghcr.io/plausible/community-edition:v3.2.2`,
  `192.168.4.54:8082→8000` (LAN-only bind),
  `BASE_URL=http://192.168.4.54:8082` (LAN address by design — see
  Diagnosis 2; drives `secure_cookie` + `check_origin`),
  `DISABLE_REGISTRATION=true`, on `monitoring-net` + `public-net`
- `plausible-db` — postgres:16-alpine (healthcheck `pg_isready`)
- `plausible-events-db` — clickhouse 24.12-alpine (low-resource overrides,
  ipv4-only, backups config)
- `ai-redis` — shared redis
- Caddy (`:80`, public via Cloudflare): `host plausible.choukalos.com` →
  `/js/*` and `/api/event` → `http://plausible:8000` (with
  `X-Forwarded-Proto https`); everything else → 404

## Open questions

1. ~~First-user email~~ — chuck's (`choukalos@yahoo.com`), created 2026-11-27.
2. ~~Bluebovine's canonical domain~~ — `bluebovinegroup.com` (site_id 4).
3. P5 feed design: Plausible API (per-site, token) vs. scheduled export —
   decide when P5 starts.

## Definition of done ✅ MET 2026-11-27

- First user created; admin UI accessible on LAN (login works)
- 3 sites exist in Plausible (ids 1, 3, 4)
- Snippet deployed on all 3 live sites (verified in page source)
- Test event + real visits visible in the dashboard (ingest verified
  end-to-end)
- P5 tracked as a separate task (WS1 deep)
