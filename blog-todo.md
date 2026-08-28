# Blog Project — Todo & Plan (revised against discovered Thor state)

> Status: **PLANNING** — Part B of `homelab-blog/PLAN.md` (drafted on the laptop)
> revised here against the actual Thor architecture (S0 discovery done 2026-08-28).
> Open questions in §4 need owner sign-off before implementation.
>
> Goal: replace Ghost at `https://choukalos.com` with the Hugo homelab portal
> (arcade, thoughts, lab, public file drop), serving files from the media
> library (siri-generated + a curated `public/` drop zone). Ghost is pulled out
> entirely — no content migration (owner decision).

---

## 1. S0 — Discovered state (Thor, 2026-08-28)

### Edge / routing (the real topology)

- **Cloudflare tunnel** (`cloudflared`, token-based remote config) → **Caddy `:80`**
  (`auto_https off` — TLS terminates at Cloudflare). Tunnel config lives in the
  Cloudflare dashboard, not on Thor. **No tunnel changes needed for cutover** —
  only the Caddy route changes.
- Caddy container: `caddy:2` (unpinned 2.x), on `ai-net` + `edge-net` + `public-net`.
  Caddyfile: `caddy/Caddyfile` (mounted **ro** from the homelab repo — edits are
  git-committed; Caddy auto-reloads on change).
- Current `choukalos.com` route: `handle @ghost → reverse_proxy http://ghost-blog:2368`
  (Host/X-Forwarded-* headers set; `www.choukalos.com` 301 → apex).
- **`siri.choukalos.com/media/files/*` → `skill-runner:8091`** — already public,
  unauthenticated, serves the **entire** `/home/chuck/data/media/` tree
  (verified: banana test video served 200). This is the existing "siri files" surface.
- Other routes (untouched by this project): `invest.*`, `api.*`, `siri.*` (API-key
  auth), `llm.*` (LiteLLM), `plausible.*` (restricted: `/js/*` + `/api/event` only).

### Ghost (what gets removed)

- `ghost-blog` container (`ghost:5-alpine`), `public-net` only, port 2368 internal
  (not host-exposed). Config: `compose/compose.ghost.yml`.
- Data: `/home/chuck/data/ghost/` — **4 MB** (content lives in MySQL, not files).
- DB: MySQL `ghost` database on the host MySQL (via `host.docker.internal`),
  creds `GHOST_DB_USER/PASS` in `.env`.
- Theme: `journal` (with the old arcade files `page-arcade.hbs`, `js/games.json`,
  `ghost-theme-assets/` — all superseded by the Hugo repo's `static/arcade/`).
- Removal scope (owner: "just pull it out"): container, compose file, DB, data
  dir, `GHOST_DB_*` env vars, laptop `deploy-arcade.sh` scp flow.

### Skill runner (the publishing surface)

- `skill-runner` on `ai-net` + `public-net`, port 8091.
- **`/home/chuck/data/media` is already mounted RW** into skill-runner →
  a `publish_file` skill needs **no compose changes** (just the target dir + skill code).
- Media tree (113 MB, `chuck:chuck 775`): `charts/ clips/ csv/ demos/ generated/
  homelab_reports/ images/ investment_briefs/ presentations/ research/
  research_reports/ siri_outputs/`.
- Media URLs: `https://siri.choukalos.com/media/files/<relpath>` (public).

### Blog repo (Part A status, from GitHub)

- `github.com/choukalos/homelab-blog` — 5 commits on `main`; **`deploy` branch
  does not exist yet** (first `deploy.sh` run creates it — laptop task, gate for S3).
- Hugo v0.165.0 (laptop-pinned binary), `baseURL = https://choukalos.com/`,
  RSS enabled, robots.txt, "zero trackers" in the description (no Plausible).
- Arcade: 7 games + screenshots in `static/arcade/`, data-driven index
  (`data/arcade/games.json`). Homepage modules: SYSTEM STATUS (fetches
  `status/status.json`, placeholder-safe), ARCADE, LATEST DROP (→ `/files/`),
  RECENT THOUGHTS.
- Hugo 0.165 gotchas documented in `IMPLEMENTATION_NOTES.md` (section layout,
  `.Site.Data`, `locale` key).

### Conventions (Thor)

- Data root: `/home/chuck/data/` (NOT `/homelab/data/` — the PLAN.md draft paths
  are wrong; all Part B paths below use the real root).
- Owner: `chuck:chuck` (1000:1000), dirs 775.
- Compose projects per domain in `compose/`; Caddyfile in-repo (ro mount).
- Networks: `public-net` (edge-facing), `ai-net` (AI stack), `edge-net` (tunnel).

---

## 2. Proposed architecture (decisions locked 2026-08-28)

```
Internet → Cloudflare (TLS) → tunnel → Caddy :80 (thor)
                                        │
  choukalos.com ────────────────────────┤
    ├── /media/files/* → reverse_proxy skill-runner:8091 (Caddy-level, same as siri)
    └── (everything else) → reverse_proxy http://portal:8080
                                              │
  portal container (dedicated, public-facing) ─┤
    ├── /            → static Hugo site (git-sync `current`, ro)
    ├── /arcade/*    → static (games + shots, part of the site)
    ├── /files/*     → themed browse + files from /home/chuck/data/media/public (ro)
    ├── /status/*    → static runtime dir (ro; publisher deferred)
    └── (RSS, 404, robots) → static
```

**Locked decisions (owner, 2026-08-28):**

1. **Dedicated `portal` container** (owner choice — public site, isolation first).
   Caddy keeps routing (consistent with every other route); the portal serves
   static site + `/files/` + `/status/`. No new Caddy origin logic beyond the
   handle swap. See §2.1 for the container design.
2. **Themed `/files/` browse** (not plain Caddy browse) — spec in §2.2.
3. **Same-origin artifacts**: `choukalos.com/media/files/*` → skill-runner
   (Caddy-level handle, mirrors the siri route). Posts embed generated
   charts/demos/videos same-origin.
4. **Active content ALLOWED in the drop zone** (owner choice — clickable demos,
   SVGs). Security analysis + guardrails in §2.3.
5. **No staging subdomain** — direct cutover on `choukalos.com` with documented
   one-line rollback.
6. **Ghost removed immediately after cutover validation** (no retention window —
   owner no longer wants it): stop, remove container, drop DB, delete data +
   env vars + compose file, in one pass.
7. **Zero trackers for now** — analytics revisited later (owner wants it
   eventually; Plausible infra already exists).
8. **Status panel deferred** — direction: service up/down tiles (llm, siri,
   invest) + fun stats (arcade plays, posts/visits last month). Schema contract
   stays stable so it can land anytime. Arcade-play counting stubbed in §5.
9. **`publish_file` scope: `public/` only** — publishing to the blog as an
   *agent capability* is a future workstream; plan stub in §5.
10. **Caddy image pin: skipped** (owner — ignore for now).

### 2.1 Portal container design

- **Tech: small Python stdlib HTTP service** (zero pip dependencies).
  Rationale: themed browse rules out nginx/caddy plain `browse`; stdlib-only
  keeps the supply chain/attack surface minimal (matches the isolation goal);
  low-traffic personal site → no need for nginx's throughput. Image:
  `python:3.12-slim`, non-root user, `read_only` rootfs.
- **Hardening**: internal port 8080 only (no host exposure), `public-net`,
  all three mounts `ro`, no secrets/env, no DB, no auth state, no Docker
  socket. The container holds **nothing sensitive** — if it's compromised,
  there's nothing to steal (see §2.3).
- **Mounts (ro)**: `/home/chuck/data/portal/git/current` → `/site` ·
  `/home/chuck/data/media/public` → `/files` · `/home/chuck/data/portal/runtime`
  → `/status`
- **Path safety**: all file serving resolves `realpath` and rejects anything
  outside the mounted root (traversal-proof by construction, tested in B6).
- **git-sync** (separate small container): pinned image, `--repo=https://
  github.com/choukalos/homelab-blog --branch=deploy --link=current --period=30s`,
  uid/gid 1000, volume `/home/chuck/data/portal/git:/git`, `public-net`,
  `read_only` rootfs, `restart: unless-stopped`.

### 2.2 Themed `/files/` browse spec (v1)

- Portal visual language (cyberpunk/brick: same CSS tokens as the site)
- Breadcrumb nav; directories listed first, then files
- Per entry: name, size (human), mtime (relative); download link per file
- **PUBLIC DROP banner** at the top ("community/AI-published files — not part
  of the site")
- No JS required (progressive enhancement at most); inline SVG icons only
- No filesystem/path leakage (never show host paths, only `/files/...` URLs)
- Active content (`.html/.js/.svg/...`) served **inline** (owner decision §2.3)

### 2.3 Active-content security analysis (drop zone serves `.html/.js/.svg`)

**Threat model first — who can write to the drop zone?**
- You (host access) and AI skills via skill-runner (X-API-Key auth, LAN).
- **There is no public upload endpoint.** Anonymous visitors cannot write.
  This is the single biggest mitigating factor.

**Impact if a malicious page runs JS on the `choukalos.com` origin:**
- The origin is **cookie-less and API-less**: no login, no same-origin API
  (Siri/invest APIs live on other subdomains with X-API-Key), no sensitive
  localStorage (arcade high scores at most). XSS on this origin has
  **low impact** — there's nothing same-origin to steal.
- `X-Content-Type-Options: nosniff` (already global in Caddy) blocks MIME
  confusion; `X-Frame-Options: DENY` (global) blocks framing/clickjacking.
- Residual risk: a *voluntarily dropped* third-party demo with sketchy JS
  running on your domain, or phishing that borrows your domain's trust.
  Accepted as operator risk (you choose what lands in `public/`).

**Guardrails (all in v1):**
1. Dedicated container with **no secrets, no cookies, no auth state** —
   compromise yields nothing.
2. Global `nosniff` + `X-Frame-Options: DENY` (already present).
3. Themed browse carries the **PUBLIC DROP banner**.
4. **Policy: keep `choukalos.com` cookie-less and API-less.** If a login or
   same-origin API is ever added to the apex domain, revisit this decision
   (then: strict CSP on `/files/*` or a separate origin for the drop zone).
5. `publish_file` size cap + sane types (B5); no symlinks, no special files.
6. B6 test matrix covers the negative cases (traversal, symlink escape,
   private siblings unreachable).

**Verdict:** allowing active content is acceptable given (a) no anonymous
write path, (b) nothing sensitive on the origin, (c) the guardrails above.
Documented so the revisit trigger (#4) is explicit.

---

## 3. Phased plan (revised Part B)

### B0. Prerequisites (laptop — owner) — **DONE (verified 2026-08-28)**
- [x] Git identity: `choukalos` (owner confirmed)
- [x] `./deploy.sh` run → `deploy` branch exists on GitHub (verified from Thor:
      `ee9e58f deploy: portal build from main@faa8243` — full Hugo build present:
      `index.html`, `arcade/`, `404.html`, `robots.txt`, `sitemap.xml`, `index.xml`)
- [ ] (Optional) Tag `v0.1` on `main` (Part A complete)
- [x] Staging hostname: **not needed** (owner — direct cutover)

**Gate: PASSED** — `git ls-remote https://github.com/choukalos/homelab-blog deploy` works from Thor.

### B1. Filesystem + boundaries — **DONE (2026-08-28)**
- [x] `mkdir -p /home/chuck/data/portal/{git,runtime}` (chuck:chuck 755)
- [x] `mkdir -p /home/chuck/data/media/public/{ai,files,images,audio,video}` (755)
- [x] No-symlinks policy for the drop zone (enforced by publisher + verified in B6)
- [x] Record ownership/permissions (recorded here + in this file's §2.1)

### B2. git-sync + portal containers — **DONE (2026-08-28)**
- [x] `compose/compose.portal.yml`: **two services**
  - `git-sync` (pinned `registry.k8s.io/git-sync/git-sync:v4.5.1`):
    `--repo=https://github.com/choukalos/homelab-blog --branch=deploy
    --link=current --period=30s`, uid/gid 1000, volume
    `/home/chuck/data/portal/git:/git`, `public-net`, `restart: unless-stopped`,
    `read_only` rootfs — synced `ee9e58f` on first run
  - `portal` (`python:3.12-slim`): stdlib server from
    `portal/server.py` (ro mount), internal port 8080, `public-net`,
    `read_only` rootfs, non-root user (1000), ro mounts per §2.1,
    `restart: unless-stopped`, healthcheck — running
- [x] `portal/server.py`: static file server + themed `/files/` browse (§2.2)
      + `/status/` static; realpath containment; correct MIME types; no JS;
      Range support; 503 syncing page; site 404 passthrough
- [x] Verify portal locally (via LAN before cutover): site, arcade,
      browse, files, 404, headers — all green (in-container + from
      public-net via skill-runner)
- [ ] (Owner, optional) Push a test revision from laptop → live within ~30s
      (git-sync syncs the deploy branch correctly; live-push timing untested)

### B3. Caddy origin (pre-cutover, additive) — **DONE (2026-08-28)**
- [x] Caddyfile `choukalos.com` handle: added `handle /media/files/*` →
      `reverse_proxy http://skill-runner:8091` (mirrors the siri route);
      everything else still → `ghost-blog:2368` until cutover
- [x] `caddy validate` passed; owner restarted caddy
- [x] Verified live: `https://choukalos.com/media/files/generated/pipeline/smoke_test/mp_e507faf26da2_00001.mp4`
      → 200 video/mp4 (894,277 B); site still served by Ghost

### B4. Cutover — **DONE (2026-08-28, external validation all green)**
- [x] Document rollback (one-line: point the handle back at `ghost-blog:2368`)
- [x] Swap the `@ghost` → `@blog` handle to the portal: `handle /media/files/*` →
      skill-runner, rest → `reverse_proxy http://portal:8080`
- [x] Owner restarted caddy
- [x] External validation (over HTTPS, from Thor): **ALL GREEN**
      - `/` — 200, `CHOUKALOS // HOMELAB`, all 4 modules (SYSTEM STATUS /
        ARCADE / LATEST DROP / RECENT THOUGHTS), 0 ghost markers
      - `/arcade/` + all 7 games (asteroids, depth-charge, elite, galaga,
        lunar-lander, missile-command, tetris) 200 + screenshots 200
      - `/thoughts/`, `/lab/`, RSS (`index.xml`), `sitemap.xml`, `robots.txt` 200
      - 404 page: `SIGNAL LOST` with correct 404 status
      - `/files/` themed browse + nested dirs; published artifacts:
        `/files/images/banana_keyframe.png` 200 (1,303,006 B),
        `/files/video/banana_vs_darth_broccoli.mp4` 200 (894,277 B)
      - `/media/files/generated/pipeline/smoke_test/...mp4` 200 video/mp4
        (same-origin artifact)
      - `/status/status.json` 404 (publisher deferred — placeholder safe)
      - `www.choukalos.com` 301 → apex
      - headers: `x-content-type-options: nosniff`, `x-frame-options: DENY`,
        referrer-policy on all new routes (duplicated by Caddy+portal —
        harmless, idempotent)
- [x] Results recorded here (blog repo `IMPLEMENTATION_NOTES.md` — owner,
      laptop side, optional)
- [x] **Validation passed → B7 (Ghost removal, immediate per owner)**

### B5. `publish_file` skill — **DONE (2026-08-28)**
- [x] `skills/publish_file/{skill.py, skill.yml, README.md}`
- [x] Inputs: `source_path`, `destination_name?`, `subdirectory` (default `ai`),
      `overwrite` (default false)
- [x] Validation: reject absolute-outside-root, `..` traversal, null bytes,
      symlinks, special files, path separators in names; source roots limited
      to `/home/chuck/data/media/` + `/home/chuck/workspace/`; target always
      under `public/` (12-case negative battery green)
- [x] Atomic write (temp + rename), world-readable non-executable modes,
      collision-safe (fail on collision unless overwrite); **size cap**
      500MB default, env `PUBLISH_FILE_MAX_BYTES`
- [x] Returns `{path, url, size_bytes, sha256}` (+ destination_name, subdirectory);
      integration test: banana keyframe + video published to the drop zone
- [x] Direct `POST /skills/publish_file` (no intent wiring — skill is
      dynamically discovered, verified live via the runner API: job
      `c2731d198962` completed in ~170ms)

### B6. Security + functional test matrix — **DONE (2026-08-28)**
- [x] Traversal: `../`, absolute paths, dotfiles, bad names (unit battery,
      12/12 rejected); external: raw traversal 404, encoded traversal 400
      (rejected at Caddy), no leakage
- [x] Symlink file: publish rejected (unit); manual symlink can't escape
      the public root (portal realpath containment — verified: external
      traversal to private siblings 404)
- [x] Active types: published test `.html` served inline 200 `text/html`
      with `<script>` intact + nosniff (published via the live skill-runner
      API, then cleaned up)
- [x] Private siblings: `/generated/...`, `/siri_outputs/`,
      `/files/ai/../../siri_outputs/` all 404 (only `/files/` +
      `/media/files/*` routes exist on `choukalos.com`)
- [x] Container least-priv: git-sync + portal `read_only` rootfs, ro mounts,
      non-root (uid 1000); no Docker socket mounted anywhere in the chain
- [x] No internal hostnames/IPs/versions in public responses (scanned
      homepage, arcade, browse: 0 refs to 192.168.4.x / container names)
- [x] Mobile viewport (viewport meta present), keyboard nav (skip-link
      present), reduced-motion (CSS media query in theme), missing status
      JSON (404 → placeholder, verified)

### B7. Ghost removal — **DONE (2026-08-28)**
- [x] In one pass: `docker compose -f compose.ghost.yml down` (container
      removed), `DROP DATABASE ghost`, `rm -rf /home/chuck/data/ghost`,
      removed `compose/compose.ghost.yml` + `GHOST_DB_*` env vars from `.env`
- [x] Verify: no ghost refs remain in active code/docs (remaining refs are
      historical: `docs/state/` frozen Phase 0 snapshots, `thor_validation_log.md`
      2026-07-03, old planning docs, `blog-todo.md` itself); blog serving
      (re-verified post-removal); MySQL healthy (homelab + investorhub DBs
      intact)
- [x] Update homelab docs: `thor_ai_inventory.md` (Ghost → Hugo Portal),
      `thor_channels_architecture.md`, `thor_public_access_model.md`,
      `thor_mcp_architecture.md`, `thor_manual_tasks.md`, root `README.md`,
      `caddy/Caddyfile` (rollback note removed)
- [x] `homelab.sh`: `ghost`/`ghost-only` stacks renamed to `blog`/
      `blog-only` (command + all call sites: compose_files, run_blog_stack,
      run_public_stack, all/all-n8n up/down/restart/rebuild/pull/logs/ps/config);
      `BLOG=compose/compose.portal.yml`; tested (`ps blog-only` green)
- [ ] (Owner, laptop) delete `deploy-arcade.sh` scp flow
- [ ] (Owner, optional) drop the `ghost` MySQL user (needs root; `ai` user
      lacks the privilege — harmless residual: USAGE only, no DB attached)

### Future workstreams (planned, not scheduled)
- **Status publisher** (PLAN S4): script/container writing sanitized
  `status.json` to `/home/chuck/data/portal/runtime/` every 30–60s.
  Direction (owner): service up/down tiles (llm, siri, invest) + fun stats
  (arcade plays, posts, visits last month). Candidate sources:
  `mcp_homelab_status` (Docker + VictoriaMetrics), VM queries, container
  `/health` endpoints. "Visits" needs analytics (Plausible API — ties to the
  analytics workstream). Arcade plays: small counter endpoint in the portal
  container (e.g. `POST /arcade/ping` → atomic increment in runtime dir).
  Schema fixed by the frontend contract (friendly names, coarse states,
  `updated_at`, `portal_revision`).
- **Analytics** (owner wants it later): Plausible infra already exists
  (`plausible` container + `plausible.choukalos.com` with restricted routes).
  Add the snippet to the Hugo template + decide which subdomains to track.
  Blog stays zero-tracker until this lands.

---

## 4. Decisions log + remaining questions

### Resolved (owner, 2026-08-28)

| # | Decision |
|---|---|
| Q1 | **Dedicated `portal` container** (isolation for the public site) — Caddy keeps routing, portal serves site + `/files/` + `/status/` |
| Q2 | **Themed `/files/` browse** in v1 (spec §2.2) |
| Q3 | **Same-origin artifacts**: `choukalos.com/media/files/*` → skill-runner |
| Q4 | **Active content allowed inline** (demos, SVGs) — analysis + guardrails §2.3 |
| Q5 | **No staging subdomain** — direct cutover with documented rollback |
| Q6 | **Ghost removed immediately** after cutover validation (no retention) |
| Q7 | **Zero trackers for now**; analytics later (Plausible infra exists) |
| Q8 | **Status panel deferred**; direction = service up/down + fun stats |
| Q9 | **Data location**: `/home/chuck/data/portal/{git,runtime}` (real Thor convention) |
| Q10 | **Caddy pin: skipped** for now |
| Q11 | **`publish_file` → `public/` only** (agent publishing to the blog: dropped — way later, not stubbed) |
| Q12 | **siri media surface unchanged** (entire tree public at `siri.choukalos.com/media/files/*` — out of scope; flagging in case owner wants to tighten separately) |

### Remaining (small, confirm before build)

| # | Question | Resolution |
|---|---|---|
| **R1** | Portal internals: **Python stdlib** HTTP server (zero pip deps, `python:3.12-slim`, non-root, ro rootfs) | **Accepted** |
| **R2** | `publish_file` size cap | **500MB default, env-configurable** |
| **R3** | Ghost removal = immediately after external validation passes | **Confirmed** (B7) |
| **R4** | Agent publishing to the blog | **Dropped — way later, not even stubbed** (owner) |
| **R5** | Themed browse: build to §2.2 spec | **Accepted** |
| **R6** | Drop-zone subdirs `ai/ files/ images/ audio/ video/` | **Keep** |

**Plan frozen 2026-08-28 — implementation approved. Constraint: owner restarts Caddy (never the agent).**

---

## 5. Rollback & failure modes

- **Cutover rollback**: revert the Caddy handle to `reverse_proxy http://ghost-blog:2368`.
  **Note**: per owner decision, Ghost is removed right after validation — the
  rollback is only meaningful *during* the cutover window (before B7 runs).
  Caddy auto-reloads; no tunnel changes ever.
- **Bad deploy**: `git revert` on `main` + `deploy.sh` (or point git-sync at a
  previous deploy revision). Atomic `current` symlink → no partial states.
- **git-sync outage**: keeps serving the last good `current`; recovers on restart.
- **Portal outage**: Caddy returns 502; `restart: unless-stopped` + Docker
  restart policy recover it; static site unaffected (no state in the container).
- **Drop-zone abuse**: publisher validation (B5) + §2.3 guardrails + B6 matrix;
  worst case = a sketchy page running on a cookie-less origin with nothing to steal.

## 6. Explicitly NOT in scope

- Ghost content migration (start fresh — owner decision)
- Status publisher implementation (deferred; placeholder contract stays)
- New arcade games (data-driven `games.json` makes this a 1-file + 1-JSON-entry task later)
- Changes to the siri/invest/llm/plausible routes
- Cloudflare tunnel config (unchanged; staging hostname not needed — owner)