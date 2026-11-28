# Plausible — ops reference (self-hosted analytics)

> Durable ops doc. Retired from `todo_plausible.md` 2026-11-28 (the todo's
> P1–P5 plan was DONE 2026-11-27; this keeps the decisions, architecture,
> site registry, and diagnosis knowledge). WS1 of `todo_agent_skills.md`.

**Status: LIVE 2026-11-27** — first user created, 3 sites created, snippet
wired + deployed on all 3 live sites, end-to-end ingest verified, data-hub
feed + Grafana Product KPIs + the `plausible-kpi` KPI report skill (BA-1)
live. The final KPI *set* refines with BA-1 as the org runs.

## Decisions

- **Self-hosted** Plausible Community Edition **v3.2.2** (the tracker is
  integrated into the main container — no separate tracker service in v3)
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

## Architecture (as deployed)

- `plausible` — `ghcr.io/plausible/community-edition:v3.2.2`,
  `192.168.4.54:8082→8000` (LAN-only bind),
  `BASE_URL=http://192.168.4.54:8082` (LAN address **by design** — see
  Diagnosis 2; drives `secure_cookie` + `check_origin`),
  `DISABLE_REGISTRATION=true`, on `monitoring-net` + `public-net`
- `plausible-db` — postgres:16-alpine (healthcheck `pg_isready`)
- `plausible-events-db` — clickhouse 24.12-alpine (low-resource overrides,
  ipv4-only, backups config)
- `ai-redis` — shared redis
- Caddy (`:80`, public via Cloudflare): `host plausible.choukalos.com` →
  `/js/*` and `/api/event` → `http://plausible:8000` (with
  `X-Forwarded-Proto https`); everything else → 404

## Site registry (P2, 2026-11-27)

| Site | domain | site_id | timezone |
|---|---|---|---|
| Homelab Blog | `choukalos.com` | 1 | America/Chicago |
| Invest Hub | `invest.choukalos.com` | 3 | America/Chicago |
| Bluebovine (CF Pages) | `bluebovinegroup.com` | 4 | America/Chicago |

**Snippet** (per site) — the **generic `/js/script.js` + `data-domain`**
(the personalized `pa-<id>.js` / `script.plausible.js` forms 404 on this
instance; `script.js` is the correct tracker path):

```html
<script defer data-domain="<site>" src="https://plausible.choukalos.com/js/script.js"></script>
```

Deployed live: Homelab Blog `layouts/_default/baseof.html` (Hugo, commit
d325a6d); Invest Hub `client/index.html` (replaced the stale `pa-…js` 404
snippet, commit b75034e); Bluebovine `src/layouts/BaseLayout.astro`
(`is:inline` so Astro passes it through, commit a5e4fd1).

Notes: the `/api/v1/sites` site-creation API is Enterprise-only (sites were
created via the web UI); admin credentials in gitignored `.env`
(`PLAUSIBLE_ADMIN_EMAIL` / `PLAUSIBLE_ADMIN_PASSWORD`); `DISABLE_REGISTRATION=true`
— the first user is the only one creatable via the form.

## P5 — data-hub feed + Grafana + KPI skill (2026-11-27)

- **Feed** (path A — the plan's intended flow; uses data-hub's v2
  generic-datasets framework, see `docs/data-hub-ingest.md`):
  - `scripts/plausible-export.sh` — daily aggregates (pageviews, unique
    visitors, custom events) per site → `plausible-daily-YYYY-MM-DD.csv`
    into the data-hub inbox
  - `scripts/plausible-register-dataset.sh` — registers the `plausible`
    dataset (target `hub.ds_plausible`, key `(date, site_id)`, explicit
    schema; idempotent upserts)
  - `scripts/systemd/plausible-export-daily.{service,timer}` +
    `scripts/plausible-install-timer.sh` — daily 02:00 UTC export
- **Grafana Product KPIs dashboard** (`grafana/dashboards/product-kpis.json`,
  uid `product-kpis-dashboard`) on the read-only **MySQL** datasource
  (`dh_reports` on `hub.*`; `grafana/provisioning/datasources/mysql.yml`).
  Panels: 7-day stats, 30-day pageview trend, per-site breakdown.
- **KPI report skill** (`agents-skills/plausible-kpi/`, registered + enabled
  in the LiteLLM Skill Hub) — the BA-1 `kpi-reporting` step. Deterministic
  script queries Plausible ClickHouse for a lookback window and writes a
  Markdown KPI report (overview, per-site, daily trend, top pages/countries,
  custom events). `--days` / `--sites` / `--top` / `--out` flags.

## Ingest verification (P4, 2026-11-27)

- Tracker script `https://plausible.choukalos.com/js/script.js` → 200
- Test event per site (`POST /api/event`, `Content-Type: text/plain`, JSON
  `{d,u,n,p}`) → 202 for all 3 domains
- Events persist in ClickHouse **`plausible.events_v2`** (not the legacy
  `events` table) — the `snippet_wiring_test` event visible for site_ids 1/3/4
- Snippet confirmed in served page source on all 3 live sites

## Diagnosis + gotchas (for the record)

**First-user bootstrap (2026-11-22):** until the first account exists,
Plausible v3 redirects *everything* — including ingest and the tracker
script — to `/register`. "Can't access on LAN" was the registration page
(working as designed); the "ingest broken" symptom was real and had the same
cause.

**Registration hang (2026-11-27):** `BASE_URL=https://…` while the admin UI is
only reachable over plain HTTP LAN broke the LiveView WebSocket join:
(1) `secure_cookie` (from the https scheme) set the `_plausible_key` session
cookie `Secure` — browsers drop Secure cookies over HTTP, so the WS
connection arrived with no session cookie → LiveView answers `"stale"` → the
form hangs; (2) `check_origin` rejected the LAN `Origin:
http://192.168.4.54:8082` (403 on the WS handshake). **Fix (one env
change):** `BASE_URL=http://192.168.4.54:8082`. The public tracker is
unaffected — `script.plausible.js` derives its event endpoint from the
script's `src` attribute, not `BASE_URL`. (Image bumped v3.2.0 → v3.2.2
while in there.)

**LiveView debugging gotchas:** the register form is a LiveView (plain
`POST /register` 404s by design); the WS URL needs `?vsn=2.0.0` +
`?_csrf_token=<meta tag>`; the join payload's `url` key is **top-level**
(not inside `params`); Plug.Crypto 1.2.5 tokens are JWT-style (HMAC over
`protected.payload`), which trips naive HMAC verification.
