# Task 16 report — SEC-12 / P12-A: file bridge public face (mcp_filebridge)

**Date:** 2026-11-26 · **Branch:** `task/16` · **Repo:** choukalos/homelab-ai-harness
**Commits (on top of main @ 3fa9f0b):**

| Commit | Content |
|---|---|
| ff81f79 | `mcp: add mcp_filebridge` — app.py, Dockerfile, pyproject.toml, filebridge.yaml, tests/ (22 tests) |
| b12b17e | `compose: add mcp_filebridge service (ai-mcp)` |
| 7a75d84 | `caddy: P12-A file-bridge cutover` — 4 one-line upstream swaps (rollback anchor) |
| fb8c0df | `docs: P12-A ship-docs` |

**DEPLOYED 2026-11-26 17:15–17:25 UTC (thor)** — merged to main (`065baed`),
runbook executed end-to-end, all steps green. See "Deployed" below for
evidence + the one deviation (bind-mount inode pin required a caddy restart
instead of a pure graceful reload).

## What was built

`mcp/servers/filebridge/` — the homelab's single public file edge (P12-A):

- **GET /health** — status + pipeline reachability (no secrets).
- **GET /dl/{token}** — transparent streaming relay to Matrix `/dl/{token}`:
  httpx stream + `aiter_bytes` → StreamingResponse (never buffers); Range
  forwarded; status (incl. 404) + Content-Type/Length/Disposition/
  Content-Range/Accept-Ranges passed through; token validation stays on
  Matrix.
- **POST /upload** — streaming multipart relay to Matrix `/upload`;
  Content-Type (incl. boundary) forwarded; **X-Api-Key stripped on the
  upstream leg** (key gate is Caddy's); 500 MB cap enforced at the relay
  (Content-Length fast path → 413 before reading; chunked counted while
  streaming → 413 at cap; Matrix's own 413 passed through).
- **GET /media/files/{filepath:path}** — FileResponse (native Range) from
  MEDIA_ROOT only for allowlisted top-level subdirs
  (`filebridge.yaml`: generated, images, demos, presentations; default-deny),
  resolved-path containment check; non-allowlisted/traversal/missing/directory
  → **404** (never 403 — no subdir enumeration). **Lands finding 12.4.**
- One JSON log line per request (method, path, upstream, status, bytes_in,
  bytes_out, duration_ms, client_ip).
- `filebridge.yaml` carries the minimal per-subdir policy; schema shaped so
  P12-B grows it into the full work_areas/publish_targets registry.

Compose (`compose/compose.mcp.yml`): service `mcp_filebridge`, image
`ai-mcp-mcp_filebridge`, user 1000:1000, ai-net, **no host port**, healthcheck
on /health, minimal env (FILEBRIDGE_PORT, MEDIA_PIPELINE_URL, MEDIA_ROOT,
UPLOAD_MAX_MB=500, TZ), volume `/home/chuck/data/media` ro.

Caddy (`caddy/Caddyfile`): four one-line upstream swaps —
`siri_pipeline /dl/*` + `/upload`: `192.168.4.55:8189` → `mcp_filebridge:8000`
(strip_prefix + key gate unchanged); `@siri_media` (siri.choukalos.com
/media/files/*) and `@blog` (choukalos.com /media/files/*): `skill-runner:8091`
→ `mcp_filebridge:8000`.

## Environment constraint (read this first)

**This task container has no docker CLI, no docker socket, and no SSH
credentials to thor (192.168.4.54:22 refused — no key available).** LAN HTTP
to Matrix (192.168.4.55:8189) and skill-runner (192.168.4.54:8091) and the
public internet are reachable. Everything that could be verified
deterministically from here was verified; the thor-side apply (compose up,
caddy reload, public battery, kill switch) is a **pending deploy step** with
the exact runbook below. Nothing was simulated: every claim below carries
evidence, and the unverifiable items are listed in Could-not-verify.

## Per-acceptance-criterion evidence

### ✅ Tests: `pytest mcp/servers/filebridge/tests` green
22 passed (policy allowlist + traversal incl. `..%2F` variants, directory/
missing 404s, Range 206; upload cap with UPLOAD_MAX_MB=1 — Content-Length +
chunked, Matrix-never-sees-body; X-Api-Key stripping; Matrix 413 passthrough;
dl header/Range/status passthrough vs stub upstream; health up/down).
Run: `mcp/servers/filebridge/.venv/bin/pytest tests -q` → `22 passed`.

### ✅ Live smoke vs the REAL Matrix (bridge app run in this container,
MEDIA_PIPELINE_URL=http://192.168.4.55:8189) — deterministic substitute for
the ai-net smoke (same code path, same upstream; only the last LAN hop
differs):
- `GET /health` → 200, `pipeline_reachable: true`.
- **DL relay:** fresh `/dl_token` for
  `/home/chuck/data/comfyui/run/media_jobs/ca3996748162/concat.txt` →
  fetch via bridge **200, 540 B**, sha256 `5415e8a55dbf9d51df91e3c707e8ea80ecfc226b6632028d688a15386b576b8f`
  **identical** to the direct Matrix fetch of the same token.
  `Range: bytes=0-99` → **206**, `Content-Range: bytes 0-99/540`.
  Bad token → **404**.
- **Upload:** small multipart via bridge → **200**, landed at
  `media_jobs/uploads/20261126T043127_upload.txt`; re-minted a dl_token for
  that path and fetched it via the bridge → 200, content identical.
- **Cap:** bridge run with UPLOAD_MAX_MB=1; 2 MiB upload → **413 from the
  relay** (`{"error":"upload exceeds 1 MB relay cap"}`); bridge log line:
  `"status":413,"bytes_in":2097351,"bytes_out":0` — Matrix never saw the
  body. (Production cap is 500 MB; the 501 MB public test is in the runbook.)
- **/media/files policy:** allowlisted `generated/smoke.txt` → 200 (+Range
  206); `siri_outputs/smoke.txt` → 404; `../etc/passwd` and
  `generated/../../etc/passwd` → 404; directory path → 404.

### ✅ Caddyfile validity (deterministic)
`caddy v2.10.2` (downloaded binary, same major as thor's Caddy line)
`caddy validate --config caddy/Caddyfile --adapter caddyfile` →
**`Valid configuration`** (exit 0) with the four `mcp_filebridge:8000`
upstreams in place.

### ✅ No new host port (by construction)
The compose service defines no `ports:` (verified programmatically); Caddy
reaches the bridge on ai-net. `ss -tlnp` on thor therefore cannot change —
see Could-not-verify for the live confirmation.

### ✅ Preflight (as far as this vantage allows)
- Blog repo (choukalos.com Hugo) grep: **zero** `media/files/<subdir>`
  embeds — the blog uses the canonical `/files/` (public drop zone) only →
  **no allowlist additions** beyond the four.
- Repo-internal `media/files` references: generated(10), demos(10),
  presentations(3), images(3) (+ siri_outputs docs-only) → allowlist covers
  all consumers.
- Baseline probes (pre-cutover): public `/media/pipeline/jobs` 404, bad-token
  dl 404, `/media/files` dirs 404, `/siri/health` 401 (no key) / 200 with
  chuck key (regression check passed early), `/health` 200; LAN skill-runner
  `/health` 200, Matrix `/health` 200.
- `/home/chuck/data/media` top-level subdirs (from repo docs + PRD work-area
  table; the fs listing itself is in Could-not-verify): generated, images,
  demos, presentations, siri_outputs, research_reports, investment_briefs,
  homelab_reports, code_reviews, public, clips.

### ✅ Deployed on thor (2026-11-26 17:15–17:25 UTC — all steps green)

Runbook executed as written, with one deviation (noted):

1. **Build + start** — `up -d --build mcp_filebridge`: image built, container
   healthy; env gate `grep -ciE 'litellm|memory|master|api_key'` = **0**
   (env is exactly the five documented vars + base-image LANG/GPG_KEY);
   ai-net smoke `/health` 200, `pipeline_reachable: true`, allowlist
   `[demos, generated, images, presentations]`, cap 500 MB. `.env` backed up
   to `/home/chuck/data/backups/env-2026-11-26.bak`; `ss -tlnp` baseline
   captured.
2. **Cutover — DEVIATION**: `caddy validate` + `caddy reload` reported
   success but loaded the **pre-merge** Caddyfile: the bind mount
   (`/home/chuck/homelab/caddy/Caddyfile → /etc/caddy/Caddyfile`, ro) is
   pinned to the file's **inode** from container creation (14 h earlier), and
   the git merge replaced the file via rename (new inode). Detected via
   md5 mismatch (container `01471b2e…` = pre-merge `c0b0d85` version, zero
   `mcp_filebridge` refs) + a battery anomaly (`research_reports` 200 —
   skill-runner's unfiltered face). Fix: `docker restart caddy` (re-binds the
   mount; container md5 = host md5 `33e14cb8…`, 7 `mcp_filebridge` refs).
   Brief public-edge interruption (~4 s); no data impact.
3. **Public battery** (post-restart, all through CF → tunnel → Caddy →
   bridge; bridge log lines prove the relay):
   - DL: fresh token → **200, 371,308 B, sha256 `811bb118…` identical** to
     direct Matrix; `Range: bytes=0-99` → **206** + Content-Range passthrough;
     bad token **404**; `cf-cache-status: DYNAMIC`.
   - Upload: no key **401**, wrong key **401**, chuck key **200** (landed
     `uploads/20261126T172150_…`); re-minted token → fetched via public
     bridge, content identical. Bridge log: `POST /upload → upstream
     192.168.4.55:8189/upload, 200, bytes_in 233` (X-Api-Key stripped on the
     upstream leg).
   - Cap: 501 MB public upload → **413 in 0.15 s from the Cloudflare edge**
     (free-plan 100 MB payload cap — the body never reaches the relay);
     50 MB public upload → 200 (Caddy imposes no practical body limit).
     Bridge's own 500 MB cap proven via ai-net: 501 MB → **413 in 0.62 s**,
     log `{"status":413,"bytes_in":525336787,"bytes_out":0,"duration_ms":0}`
     — Matrix never saw the body. **Effective public upload cap: 100 MB
     (CF edge); bridge 500 MB is the backstop.**
   - `/media/files` (both hosts): allowlisted **200** (one real file each of
     generated/, images/, demos/, presentations/); siri_outputs **404**
     (both hosts); research_reports/public/homelab_reports/investment_briefs
     **404**; `../etc/passwd`, `generated/../../etc/passwd`, `..%2F` variants
     **404**; directory **404**.
   - `/media/pipeline/jobs` + `/dl_token` public → **404**.
4. **Kill switch** — `docker stop mcp_filebridge`: all four public routes
   **502** while Matrix `/health` + skill-runner `/health` stay **200**;
   `docker start` → 200s, container healthy.
5. **Regression** — siri `/api/health` + api `/health` **200** with chuck
   key; LAN `192.168.4.54:8091/media/files/<allowlisted>` **200** (skill-
   runner's LAN face untouched); blog portal `/` + `/files/` **200**.
6. **Port diff** — `ss -tlnp` before/after: **no diff** (no new host port).

**Rollback (still valid — one-line per route, or `git checkout 7a75d84~1 --
caddy/Caddyfile` + sync into the caddy container + reload/restart):**
dl/upload → `http://192.168.4.55:8189`; both /media/files →
`http://skill-runner:8091`. (Remember the inode pin: after any git
rename-replacement of `caddy/Caddyfile`, the running caddy container sees the
stale file until `docker restart caddy` — or verify with an md5 compare first.)

## Manual follow-up (recorded)

- **Matrix 8189 → LAN-only — ✅ DONE 2026-11-26 (validated from thor):**
  LAN `192.168.4.55:8189/health` → 200; external vantage points
  (check-host.net, US + IL) TCP `104.5.56.59:8189` → connection timeout
  (filtered); public download via the bridge → 200 + sha256 identical (full
  path CF → tunnel → Caddy → bridge → Matrix on the LAN); bridge `/health`
  `pipeline_reachable: true`. Full runbook: `docs/thor_manual_tasks.md`
  (Phase 17, table row 13).

## Unblocked

- **P12-B** (MCP tools Face 2 + registry): `filebridge.yaml` schema is
  shaped for `work_areas`/`publish_targets` sections.
- **P12-C** (publish engine): unblocked by P12-B.

## Could-not-verify (no thor docker/ssh from this container)

1. `docker compose up -d --build mcp_filebridge` on thor (build, container
   healthy, `docker inspect` env == 0 matches, healthcheck) — runbook step 1.
   (The env list is exactly the five documented vars; the grep-0 check is a
   deploy-time confirmation.)
2. Live `caddy validate` + `caddy reload` on thor — local caddy v2.10.2
   validate is green (same major); reload is runbook step 2.
3. Public battery over CF → tunnel → Caddy → bridge (dl/upload/files on both
   hosts, 413 at 501 MB, cf-cache-status DYNAMIC) — the identical logic was
   proven against the real Matrix from this vantage (evidence above); the
   public hop is untested until the reload lands.
4. Kill-switch test (docker stop/start mcp_filebridge) — runbook step 4.
5. `ss -tlnp` on thor before/after (no new host port) — by construction the
   service binds no host port; container-vantage port baseline recorded
   (54:22/8091/3000/9090, 55:8189 open).
6. Running-Caddyfile diff against the repo (no `docker exec caddy cat`);
   the repo Caddyfile is the source of truth and was validated.
7. `.env` backup on thor (file not visible from here) — runbook step 1.
8. Filesystem listing of `/home/chuck/data/media` on thor — enumerated from
   repo docs + PRD (see preflight).
