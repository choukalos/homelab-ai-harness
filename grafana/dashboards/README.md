# Grafana Dashboards

File-based provisioned Grafana dashboards. Grafana auto-reloads this directory
every 30s (provisioning config: `../provisioning/dashboards/dashboards.yml`,
folder **Monitoring**).

- Grafana: `http://127.0.0.1:3001` (v13.0.2)
- Admin login: `admin` — **password is NOT `admin`** (verified 2026-09-16;
  `GF_SECURITY_ADMIN_PASSWORD` in `.env` only applies at first provisioning,
  the DB hash is the source of truth). Reset procedure: see
  [Admin password reset](#admin-password-reset) below.
- Datasource: Prometheus → VictoriaMetrics `http://127.0.0.1:9090`
- The directory is mounted **read-only** into the Grafana container
  (`/var/lib/grafana/dashboards`) — edit files here on the host, never in the
  container. Do NOT try to save dashboards via the Grafana UI/API for these
  files: the API returns 403 (file-provisioned dashboards are read-only).

## AI Work & Spend dashboard (`ai-work-spend.json`)

**Generated file — do not edit the JSON directly.** The source of truth is
`gen_ai_work_spend.py`. Workflow:

```bash
cd /home/chuck/homelab/grafana/dashboards
python3 gen_ai_work_spend.py        # rewrites ai-work-spend.json
# Grafana picks it up within ~30s (provisioning refresh)
```

Dashboard URL: `http://127.0.0.1:3001/d/ai-work-spend` (default range: last 30 days).

Cost model: LLM $ = `litellm_spend_metric_total`, Media $ = `media_cost_usd_total`,
Total work $ = LLM $ + Media $ (excluding storyboard stage to avoid
double-counting — storyboard LLM calls already appear in LiteLLM metrics).
See the generator docstring for details.

### Adding a new user color (USER_COLORS)

Each user's series is pinned to a fixed color via **field overrides** so the
same user is recognizable in every panel (spend, tokens, requests, media
stages, etc.). The color map lives in `gen_ai_work_spend.py`:

```python
USER_COLORS = {
    "chuck": "#73BF69",           # green
    "dylan": "#1F60FC",           # blue
    "memory-service": "#F2C94C",  # yellow
    "default_user_id": "#EA62AF", # pink (master-key traffic)
    "None": "#666666",            # gray (unattributed traffic)
}
```

**To add a new user:**

1. Find the user's exact label value (this is what appears in legends):
   ```bash
   curl -s -G http://127.0.0.1:9090/api/v1/series \
     --data-urlencode 'match[]={__name__="litellm_spend_metric_total"}' \
   | python3 -c "import json,sys; print(sorted({l['metric']['user'] for l in json.load(sys.stdin)['data']}))"
   ```
   (or check the `$user` variable dropdown in the dashboard — it is populated
   from `label_values(litellm_spend_metric_total, user)`).
2. Add an entry to `USER_COLORS` in `gen_ai_work_spend.py`. Pick a hue that is
   clearly distinct from the existing ones (green/blue/yellow/pink/gray are
   taken) — the goal is instant human recognition, so avoid similar hues.
   Note the key must match the label value **exactly** (case-sensitive;
   `None` is the literal string for unattributed traffic).
3. Regenerate + wait ~30s:
   ```bash
   python3 gen_ai_work_spend.py
   ```
4. Verify the override actually rendered (Grafana silently drops malformed
   overrides — see gotchas below). Quick check via the dashboard API:
   ```bash
   curl -s -u admin:admin http://127.0.0.1:3001/api/dashboards/uid/ai-work-spend \
     | python3 -c "import json,sys; d=json.load(sys.stdin)['dashboard']; \
       p=[p for p in d['panels'] if p['id']==14][0]; \
       print(d['version'], [o['matcher']['options'] for o in p['fieldConfig']['overrides']])"
   ```
   The new user's regex should appear, and the version number should have
   incremented. Then eyeball the panel in a browser (or headless screenshot) —
   the JSON being correct is NOT sufficient; Grafana has silently ignored
   overrides with subtle format errors (see below).

`user_overrides()` generates one `byRegexp` override per user that matches the
user's bare name and compound legend names (`chuck / image`, `chuck / in`,
`chuck / tts`, ...) — so a user keeps one color across all legend formats.
Panels with `by_user=True` in the generator (panels 14, 24, 25, 31, 32, 60,
61, 62) get these overrides. If you add a new per-user panel, pass
`by_user=True` to `ts()`/`bar()`.

### Grafana 13 field-override gotchas (learned the hard way, 2026-09-16)

Grafana **silently ignores** overrides that are malformed — no warning in the
UI, no API error. The correct format (verified against the Grafana 13.0.2
rendering bundle) is:

```json
"fieldConfig": {
  "defaults": { ... },
  "overrides": [
    {
      "matcher": { "id": "byRegexp", "options": "/^chuck( \\/ .+)?$/" },
      "properties": [
        { "id": "color", "value": { "mode": "fixed", "fixedColor": "#73BF69" } }
      ]
    }
  ]
}
```

Three mistakes that each caused "all series render the same color":

1. **Overrides at the panel root** (`panel.overrides`) instead of
   `panel.fieldConfig.overrides` — completely ignored.
2. **`matcher` as a flat string** (`"matcher": "byRegexp", "options": ...`)
   instead of the object form `{"id": "byRegexp", "options": ...}` — the
   renderer reads `matcher.id`/`matcher.options`, so a string matcher makes
   the registry lookup fail and the override is skipped.
3. **`value.color`** instead of **`value.fixedColor`** — the v13 color
   property value is `{mode: "fixed", fixedColor: "#hex"}`; the legacy `color`
   key is read as undefined and the series falls back to the palette.

Also:

- **Do not set an explicit `"color": {"mode": "palette"}` in
  `fieldConfig.defaults`** on timeseries/barchart panels. In 13.0.2 this made
  every series resolve to palette index 0 (all green). Omit the `color` key
  entirely and the default palette assigns distinct colors per series. (Stat
  panels using `color: {mode: "thresholds"}` are fine.)
- **byRegexp options**: use the documented `/pattern/flags` form. The UI parser
  uses the pattern verbatim when it starts with `/`; plain strings get wrapped
  in `^...$` (double-anchoring is harmless but the `/.../` form is
  unambiguous).
- Legacy dashboards may show `"params"` in matchers (pre-v10 key); v13 writes
  and reads `options`.
- The `$user` variable dropdown and the `user=~"$user"` filters pick up new
  users automatically (label_values-driven) — no change needed there.

### Verification recipe (end-to-end)

The JSON/API can look correct while the rendering is wrong (see gotchas).
To verify a dashboard change end-to-end, render it headlessly and read the
legend swatch colors from the DOM (each legend item has a
`[data-testid="series-icon"]` element whose inline `style="background: rgb(...)"`
is the rendered series color). Working probe script (runs in the `crawl4ai`
container, which has Playwright + Chromium):

```bash
cat > /home/chuck/data/crawl4ai/legend_probe.py <<'EOF'
#!/usr/bin/env python3
import time
from playwright.sync_api import sync_playwright
BASE = "http://172.17.0.1:3001"  # Grafana as seen from the container
CHROME = "/home/appuser/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=CHROME, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1720, "height": 1000})
    pg.goto(f"{BASE}/login", wait_until="networkidle", timeout=30000)
    pg.fill("input[name=user]", "admin"); pg.fill("input[name=password]", "admin")
    pg.click("button[type=submit]"); time.sleep(4)
    pg.goto(f"{BASE}/d/ai-work-spend?from=now-30d&to=now&orgId=1",
            wait_until="networkidle", timeout=30000)
    time.sleep(15)
    rows = pg.evaluate("""() => {
      const out = [];
      document.querySelectorAll('[data-testid="series-icon"]').forEach(el => {
        const wrap = el.closest('[class*="LegendItemWrapper"]');
        const name = wrap ? (wrap.getAttribute('data-testid') || '')
                          .replace('data-testid VizLegend series ', '') : '?';
        out.push(name.slice(0, 25) + ' => ' + (el.style.background || ''));
      });
      return out;
    }""")
    print("\n".join(rows[:30]))
    b.close()
EOF
docker exec crawl4ai python3 /app/data/legend_probe.py
```

(`crawl4ai` bind mount: host `/home/chuck/data/crawl4ai` → container
`/app/data`. Write screenshots to container `/tmp`, then `docker cp` out.)

### Dashboard layout (6 rows)

| Row | y | Panels |
|---|---|---|
| LLM (LiteLLM) | 1 | stats 10–13, spend by user (14), vLLM tokens (15) |
| Media pipeline | 15 | stats 20–23, cost by user/stage (24), work units (25) |
| Total work $ | 29 | stat 30, barchart by user (31), 5m rate (32) |
| GPU | 38 | stats 40–42, power (43), util (44) |
| Media pipeline jobs | 55 | stats 50–51, queue depth (52), jobs by status (53) |
| **Token & Spend by user** | 72 | barchart tokens in/out (60), barchart spend (61), requests 5m (62) |
| **Models & performance** | 81 | stats: failed requests (70), avg latency (71), TTFT (72); barcharts: requests by model (73), tokens by model in/out (74) |

Row 7 was migrated from the retired **LLM & GPU Monitor** dashboard
(`llm-gpu-monitor.json`, deleted 2026-09-16, backup at
`llm-gpu-monitor.json.bak`) — it was the only dashboard with the model
breakdown and latency/TTFT/failure visibility. Everything else in that
dashboard was superseded: per-user spend/tokens/requests by this dashboard,
GPU temp/VRAM by the DCGM dashboard, and its key-budget row was dead (no
budgets configured; `litellm_api_key_max_budget_metric` no longer emits).
Restore from the `.bak` if needed (just rename back to `.json`).

## Other dashboards

`cadvisor.json`, `dcgm.json`, `node-exporter-full.json`, `prometheus.json` —
imported community/vendor dashboards, edited in place (no generator).

(The `LLM & GPU Monitor` dashboard was retired 2026-09-16 — see the note above
Row 7.)

### Homelab Overview (`homelab-overview.json`, uid `homelab-overview-dashboard`)

Edited in place (no generator). Cleanup pass 2026-09-16 via `ho_cleanup.py`
(one-off transform, kept for reference):

- **Servers row**: added per-host **Disk Usage %** (id 40) and **Disk
  Available** (id 41) stats, styled like the CPU/Memory stats (background
  color + sparkline). Top row is now 5 stats (w=5,5,5,5,4). Disk queries use
  `node_filesystem_{size,avail}_bytes` with
  `fstype!~"tmpfs|overlay|squashfs|cifs|rootfs|iso9660|vfat", device!~"loop.*"`
  to count only real local disks (avoids double-counting rootfs/tmpfs/cifs and
  NAS loop mounts). All four hosts (athena/lego/matrix/thor) report filesystem
  metrics (matrix's collector was enabled 2026-09-16).
  - **Both disk panels are `instant` queries** — they always show the current
    value. (A 30-day range query with Grafana's auto step drops hosts whose
    data is younger than the step, so a freshly-fixed host like matrix would
    be missing for a while.)
  - **Disk Available (id 41) is colored by USAGE, not free-bytes**: green when
    usage < 80%, red when usage >= 80%. Done with per-host
    `fieldConfig.overrides` (`byRegexp` on the instance name) where each host's
    threshold = **20% of its total capacity** (the boundary where usage hits
    80%): free above the threshold → green, below → red. Current thresholds
    (bytes, as of 2026-09-16): athena `5757618408653`, lego
    `8542049218355`, matrix `359486608179`, thor `47848403763`. **If a host's
    disk capacity changes**, recompute that host's override as
    `0.2 × sum(node_filesystem_size_bytes{<filters>, instance="<host>"})`.
    The base default is a single green step (safe fallback for any new host
    that has no override yet). The **Disk Usage %** card (id 40) uses the
    standard thresholds (yellow 80% / red 90%).
  - **Disk Usage % thresholds**: yellow 80%, red 90% (on usage %).
  - **Disk Available color is driven by usage, not free-bytes.** It uses
    per-host `fieldConfig.overrides` (byRegexp on the instance name) where each
    host's threshold = **20% of that host's total capacity** (the boundary
    where usage hits 80%): free above it → green, below → red. As of 2026-09-16:
    athena 5757618408653 B, lego 8542049218355 B, matrix 359486608179 B,
    thor 47848403763 B. **If a host's disk capacity changes, recompute that
    host's override as `0.2 × node_filesystem_size_bytes` total.** The base
    default is a single green step (safe fallback for any new host).
- **LLM Metrics row → "AI Usage"**: the detailed by-model panels (requests/
  tokens/latency by model, token breakdown, cached tokens per-user) were
  replaced with overview-level panels that mirror AI Work & Spend: **Total
  $ Spend (range)** (42, currencyUSD), **Total Tokens (range)** (43, in+out),
  **Avg Latency (range)** (44, s; yellow 15s / red 30s), **Failed Requests
  (range)** (45), and **AI requests by user over time (5m)** (46, full-width
  timeseries, `sum by (user) (increase(litellm_proxy_total_requests_metric_total[5m]))`).
  By-model detail lives in AI Work & Spend Row 7. This dashboard has no
  `$user` template variable, so the queries don't filter on it.
- **API Keys row**: dropped the two dead budget panels (Keys w/ Budget, Budget
  Exhausted) — `litellm_api_key_max_budget_metric` no longer emits and
  `litellm_remaining_api_key_budget_metric` is all +Inf (no budgets
  configured). Row is now Active Keys / Total Spend (30d) / Top Spend Key.
- **Layout reflow**: fixed an overlap bug where the stray "Cached Tokens
  (per-user)" panel sat on top of the full-width Container Overview table.
  Rows now: Servers y=0, AI Usage y=13, Services y=27, API Keys y=40, GPU
  Metrics y=53.

Rollback: `cp homelab-overview.json.bak2 homelab-overview.json` (pre-cleanup
original, 34 panels). `homelab-overview.json.bak` is an older (Jul 12)
backup. Grafana auto-provisions within ~30s; verified live at version 28.

## Anonymous access, home dashboard & stars

Grafana runs with **anonymous Viewer access** enabled
(`GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer` in
`../compose/compose.monitoring.yml`). Anyone on the LAN (or through a tunnel)
can browse dashboards without logging in; sign-up is disabled
(`GF_USERS_ALLOW_SIGN_UP=false`).

### Home dashboard (all users, incl. anonymous)

`GF_USERS_HOME_PAGE=/d/homelab-overview-dashboard` makes `/` render the
**Homelab Overview** dashboard for any user without a personal home-dashboard
preference — which includes anonymous users (they can't set preferences).
Verified headless 2026-09-16: anonymous `GET /` → title
"Homelab Overview - Monitoring - Dashboards - Grafana".

- To change the landing dashboard, edit that env var in
  `compose/compose.monitoring.yml` (value must be a frontend route, e.g.
  `/d/<uid>`), then `docker compose -f compose.monitoring.yml up -d grafana`.
- Authenticated users can still override it per-user via
  Profile → Preferences → Home dashboard.

### Starred dashboards for anonymous users

"AI Work & Spend" (`ai-work-spend`) and "Homelab Overview"
(`homelab-overview-dashboard`) are starred under **user_id 0** (anonymous),
inserted directly into the DB on 2026-09-16. Effect: the sidebar **Starred**
view (`/dashboards?starred` — note: `/dashboards/starred` 404s on v13) and
the home page's Dashboards section show exactly these two for anonymous
users.

Verify (no auth needed):

```bash
curl -s 'http://127.0.0.1:3001/api/search?starred=true' \
  | python3 -c "import json,sys; print([x['title'] for x in json.load(sys.stdin)])"
# → ['AI Work & Spend', 'Homelab Overview']
```

**Managing anonymous stars requires direct DB access** — the star API
(`POST/DELETE /api/user/stars/dashboard/uid/:uid`) returns 401 for anonymous
users, and when called as admin it stars for the admin user (user_id 1), not
for anonymous. To add/remove an anonymous star:

```bash
docker stop grafana
docker cp grafana:/var/lib/grafana/grafana.db /tmp/g.db
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect('/tmp/g.db')
# add a star (look up the numeric dashboard_id from /api/search first):
c.execute("INSERT INTO star (user_id, dashboard_id, dashboard_uid, org_id, updated)"
          " VALUES (0, <DASHBOARD_ID>, '<DASHBOARD_UID>', 1, datetime('now'))")
# remove a star:
# c.execute("DELETE FROM star WHERE user_id=0 AND dashboard_uid='<UID>'")
c.commit()
EOF
docker cp /tmp/g.db grafana:/var/lib/grafana/grafana.db
docker exec --user root grafana chown 472:root /var/lib/grafana/grafana.db
docker exec --user root grafana chmod 640 /var/lib/grafana/grafana.db
docker start grafana
```

(Back up first: `docker cp grafana:/var/lib/grafana/grafana.db
grafana:/var/lib/grafana/grafana.db.bak-<ts>` — the 2026-09-16 star insert
left `grafana.db.bak-20260916-202528` in the data dir.)

### Admin password reset

The admin user (`admin`, id 1, is_admin) was provisioned 2026-06-21; its
password hash in the DB is the source of truth and does **not** match the
`GRAFANA_ADMIN_PASSWORD` value in `.env` (verified 2026-09-16 — `admin:admin`
and other common values fail). Grafana v13 hashes passwords with
PBKDF2-SHA256 (10,000 iterations, 50-byte key) over `password` + `salt`.
If the password is lost, reset it via the DB (same stop/cp/restore dance as
above):

```bash
python3 - <<'EOF'
import sqlite3, hashlib
NEW = 'choose-a-strong-password'
salt = 'admin'
h = hashlib.pbkdf2_hmac('sha256', NEW.encode(), salt.encode(), 10000, 50).hex()
c = sqlite3.connect('/tmp/g.db')
c.execute("UPDATE user SET password=?, salt=? WHERE login='admin'", (h, salt))
c.commit()
EOF
```
## Access: anonymous users, home dashboard, and stars

Grafana is LAN-only, but **anonymous access is enabled** — anyone on the LAN
can view dashboards without logging in. Config in
`compose/compose.monitoring.yml` (env vars):

- `GF_AUTH_ANONYMOUS_ENABLED=true`
- `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer` (read-only; no alerting/datasource writes)
- `GF_USERS_ALLOW_SIGN_UP=false` (no self-service accounts)

### Home dashboard (`/` → Homelab Overview)

`GF_USERS_HOME_PAGE=/d/homelab-overview-dashboard` makes `/` render the
**Homelab Overview** dashboard for every user without a personal
home-dashboard preference (Profile → Preferences → Home dashboard) —
including anonymous users. Added 2026-09-16; apply with:

```bash
cd /home/chuck/homelab/compose
docker compose -f compose.monitoring.yml up -d grafana
```

Verified headlessly (Playwright in the `crawl4ai` container, anonymous):
`/` → title `Homelab Overview - Monitoring - Dashboards - Grafana`, still
signed out.

### Starred dashboards for anonymous users

The sidebar **Starred** view (`/dashboards?starred` — note the query-param
route; `/dashboards/starred` is a 404 in v13) lists dashboards starred by the
current user. The two front-page dashboards are starred for the **anonymous
user (`user_id = 0`)** so they show up in the Starred view and in the home
dashboard's Dashboards section for every unauthenticated visitor:

- **AI Work & Spend** (`ai-work-spend`)
- **Homelab Overview** (`homelab-overview-dashboard`)

Check current state (no auth needed):

```bash
curl -s 'http://127.0.0.1:3001/api/search?starred=true' \
  | python3 -c "import json,sys; print([x['title'] for x in json.load(sys.stdin)])"
```

**Managing anonymous stars:** the star API
(`POST/DELETE /api/user/stars/dashboard/uid/:uid`) requires a signed-in user
and always writes the star for *that* user — anonymous gets 401, and there is
no API to star on behalf of user 0. So anonymous stars are managed directly
in the SQLite DB (back it up first):

```bash
cp /home/chuck/data/grafana/grafana.db /home/chuck/data/grafana/grafana.db.bak-$(date +%Y%m%d-%H%M%S)
docker cp grafana:/var/lib/grafana/grafana.db /tmp/g.db
python3 - <<'PYEOF'
import sqlite3
c = sqlite3.connect('/tmp/g.db')
print(c.execute('SELECT user_id, dashboard_uid FROM star').fetchall())  # inspect
# dashboard_id is the numeric id from /api/search (e.g. 1360021519392768)
# c.execute("INSERT INTO star (user_id, dashboard_id, dashboard_uid, org_id, updated) VALUES (0, <id>, '<uid>', 1, datetime('now'))")
# c.execute("DELETE FROM star WHERE user_id = 0 AND dashboard_uid = '<uid>'")
c.commit()
PYEOF
docker cp /tmp/g.db grafana:/var/lib/grafana/grafana.db
docker exec --user root grafana chown 472:root /var/lib/grafana/grafana.db
docker exec --user root grafana chmod 640 /var/lib/grafana/grafana.db
docker restart grafana
rm -f /tmp/g.db
```

The 2026-09-16 star insert left a backup at
`/home/chuck/data/grafana/grafana.db.bak-20260916-202528`.

### Admin password reset

The admin user (`admin`, id 1) exists, but its password is **not** the value
in `.env` — `GF_SECURITY_ADMIN_PASSWORD` is only applied at first
provisioning (2026-06-21); the hash in the DB is the source of truth. As of
2026-09-16 `admin:admin` fails. If the password is lost:

```bash
docker stop grafana
docker cp grafana:/var/lib/grafana/grafana.db /tmp/g.db
python3 - <<'PYEOF'
import sqlite3, hashlib
NEW = 'choose-a-strong-password'
# Grafana v13 hash: PBKDF2-SHA256, 10000 iterations, 50-byte key, hex
h = hashlib.pbkdf2_hmac('sha256', NEW.encode(), b'admin', 10000, 50).hex()
c = sqlite3.connect('/tmp/g.db')
c.execute("UPDATE user SET password = ?, salt = 'admin' WHERE login = 'admin'", (h,))
c.commit()
PYEOF
docker cp /tmp/g.db grafana:/var/lib/grafana/grafana.db
docker exec --user root grafana chown 472:root /var/lib/grafana/grafana.db
docker exec --user root grafana chmod 640 /var/lib/grafana/grafana.db
docker start grafana
rm -f /tmp/g.db
```

(Older Grafana used a double-SHA256 scheme; v13 uses PBKDF2 — verify against
`pkg/util/encoding.go` if you ever port this to another version.)
