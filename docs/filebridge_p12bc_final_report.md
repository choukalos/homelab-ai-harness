# P12-B + P12-C final report — pi-long-task run `10f37f65`

**Date:** 2026-11-26 · **Repo:** `/home/chuck/homelab`, `main` @ `79c39d5`
(clean at start) · **Commits:** none (commits disabled for this run — all
changes are in the working tree for user review/commit/deploy).
**Design doc:** `docs/filebridge_p12bc.md` (complete, incl. security
properties) · **Deploy runbook:** `docs/filebridge_p12bc_deploy.md`
(NOT executed — pending user timing) · **NAS cleanup report:**
`docs/nas_cleanup_2026-11-26.md`.

## 1. What changed

### New files (10)

| File | Lines | Content |
|---|---|---|
| `mcp/servers/filebridge/registry.py` | 226 | registry load + lint (fail-fast boot + standalone `python app.py lint` CLI) |
| `mcp/servers/filebridge/tokens.py` | 88 | 1b path-bound, TTL'd signed-token store (in-process; token IS the credential) |
| `mcp/servers/filebridge/fileops.py` | 217 | `file_pull`/`file_push` semantics, D13 guards, one-line JSON audit |
| `mcp/servers/filebridge/mcp_face.py` | 304 | FastMCP streamable-HTTP face at `POST /mcp` (stateless) + 5 tools |
| `mcp/servers/filebridge/publish_engine.py` | 336 | extracted publish engine (parameterized by registry target config) + `PublishTarget` protocol + `LocalFSTarget` (bluebovine interface-only, D14) |
| `mcp/servers/filebridge/tests/test_registry.py` | 189 | registry load/lint, every lint rule, CLI both ways, shipped-registry green |
| `mcp/servers/filebridge/tests/test_tokens.py` | 96 | mint/serve byte-identical + Range, bad token 404, expiry (fake clock), path-binding, route precedence, TTL clamp |
| `mcp/servers/filebridge/tests/test_file_pull.py` | 197 | `file_pull` all 4 source types (stubbed upstreams), default-deny, collision suffix, atomic, cap |
| `mcp/servers/filebridge/tests/test_file_push.py` | 208 | `file_push` work area / matrix_pipeline / client (mints token) / publish target; D13 rejection for all callers |
| `mcp/servers/filebridge/tests/test_publish.py` | 387 | engine parameterization (blog + nas), ported skill cases, source validation, `file_publish` tool, `POST /publish`, adapter protocol check |

### Modified files (12)

| File | Change |
|---|---|
| `mcp/servers/filebridge/app.py` | registry boot-lint fail-fast; `GET /media/files/dl/{token}` route registered BEFORE the `/media/files` catch-all (404-not-403); `POST /publish` (ai-net only); MCP face mounted last; app lifespan starts the MCP session manager; `python app.py lint` CLI |
| `mcp/servers/filebridge/filebridge.yaml` | full registry: `work_areas` (5: media_staging, pipeline_fetch, siri_outputs `remote_write:false`, nas_media_store `automount+shared_output`, matrix_pipeline `api:`) + `publish_targets` (blog + nas; bluebovine reserved) |
| `mcp/servers/filebridge/Dockerfile` | COPY the 5 new modules |
| `mcp/servers/filebridge/pyproject.toml` | `mcp>=1.10,<2` dep; pytest session loop scope |
| `mcp/servers/filebridge/tests/conftest.py` | stub upstream `/files` + `/raw` routes, `full_stub` + `mcp_session` fixtures, MCP JSON-RPC helpers |
| `compose/compose.mcp.yml` | `mcp_filebridge` volumes: 3 work-area mounts (siri_outputs ro, workspace/media rw, lego-media-store rw) + 2 publish-engine mounts (data/media/public rw, workspace ro); user 1000:1000 + env gate 0 + no ports preserved |
| `litellm/config.yml` | `mcp_filebridge` `mcp_servers` entry (15th server; `transport: http`, `url: http://mcp_filebridge:8000/mcp`, `extra_headers: [Authorization]`, `timeout: 7200`) — **config only, not applied** (applied at the runbook's litellm restart) |
| `skills/publish_file/skill.py` | now a THIN WRAPPER: POSTs to `http://mcp_filebridge:8000/publish` (ai-net; `PUBLISH_FILE_BRIDGE_URL` override), verbatim pass-through, NO fallback; skill.yml contract unchanged |
| `skills/publish_file/test_skill.py` | updated to the wrapper contract (request shape, pass-through, rejection surfacing, bridge-down error, enum drift, thinness) |
| `agents-skills/publish-file/SKILL.md` | architecture note: engine now lives in the bridge; skill is a wrapper |
| `security_todo.md` | Phase 12: P12-B + P12-C lines marked IMPLEMENTED 2026-11-26 — PENDING DEPLOY with evidence pointers; "bridge registry lint green (P12-B)" checklist item resolved |
| `docs/thor_manual_tasks.md` | *(pre-existing working-tree change from an earlier run step — Phase 17 mechanism note; NOT part of this task set, untouched by it)* |

### Out-of-band (not repo files)

- `/mnt/lego-media-store/published/` created (chuck:chuck 755, writable) —
  the P12-C `nas` publish root (decision 4-published). See the NAS
  cleanup report below.
- Side test image `mcp_filebridge_p12bc_test:latest` kept on thor
  (distinct tag; the live `ai-mcp-mcp_filebridge` image was NOT touched).
- `tmp/e2e_filebridge_test.py` — reusable 43-check E2E battery script
  (gitignored scratch).

## 2. Test evidence

Commands run on thor 2026-11-26 (re-verified for this report).

### 2.1 Unit suites

```
$ PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 -m pytest mcp/servers/filebridge/tests/ -q
107 passed in 46.08s
    (existing 22 P12-A tests — test_policy / test_dl_relay / test_upload —
     all green; + 59 P12-B: registry/lint, tokens, file_pull/file_push,
     MCP tools/list + tools/call, route precedence, D13; + 26 P12-C:
     engine, file_publish, POST /publish, adapter)

$ PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 skills/publish_file/test_skill.py
PASS: 32  FAIL: 0        (wrapper contract)
```

### 2.2 Registry lint (standalone CLI, shipped registry)

```
$ PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 mcp/servers/filebridge/app.py lint
registry lint: OK (5 work areas, 2 publish targets)     (exit 0)
```
Broken registries fail fast with exit 1 + per-rule errors (tested:
`tests/test_registry.py` — missing sections, bad flags, overlapping
areas, missing paths, D13 consistency, `size_cap_mb` ≤ 0, …). Boot with
a broken registry raises `SystemExit` (fail-fast, tested).

### 2.3 Side test container E2E (TODO 6 — `mcp_filebridge_test`)

Built the P12-B/C image, ran it on ai-net port 8001 (same env + mounts,
**no published host ports**, user 1000:1000), env gate 0:

```
$ docker inspect mcp_filebridge_test --format '{{json .Config.Env}}' | grep -ciE 'litellm|memory|master|api_key'
0
$ docker port mcp_filebridge_test
(empty — no published ports)
```

E2E battery (`tmp/e2e_filebridge_test.py`, 43 checks): **43 passed,
0 failed** — MCP `initialize`/`tools/list`/`tools/call` (all 5 tools
incl. D13 + default-deny negatives + DNS-rebinding refusal),
`POST /publish` (blog/nas/duplicate/overwrite/400s), 1b token route
(mint → fetch 200 + sha256 + Range 206; bad token 404; TTL bounds;
D13), `/media/files` policy (allowlisted 200; siri_outputs /
non-allowlisted / traversal / directory 404), `/health` +
`pipeline_reachable`. The battery found and fixed one real bug
(double module import under script-mode boot — `mcp_face._app()` now
resolves the running app instance). Container torn down afterwards
(`docker rm -f mcp_filebridge_test`); all `e2e_fb_*` host artifacts
deleted.

Unit suites inside scratch containers (host paths mounted for the
real-registry lint test): filebridge 107 passed, publish_file 8 passed.

### 2.4 Public E2E battery

NOT run — requires the live cutover, which is deferred to the deploy
runbook (`docs/filebridge_p12bc_deploy.md` §4: token route via Caddy
mint → fetch 200 + sha256, bad token 404, TTL; full P12-A regression
battery; kill switch; ss port diff). The identical logic was proven
against the real Matrix from the side container (TODO 6).

### 2.5 Secret scan (hard rule)

```
$ { git diff; git diff --cached; } | grep -E 'sk-[A-Za-z0-9]{8,}'
(no matches)
$ git status --porcelain | awk '{print $2}' | xargs grep -lE 'sk-[A-Za-z0-9]{8,}' 2>/dev/null
(nothing — all 22 changed/new files clean)
```

## 3. NAS cleanup report (decision 4-published)

Full report: **`docs/nas_cleanup_2026-11-26.md`** (inventory table +
classification + deletion attempt + flagged items + `published/`
verification). Summary:

| Action | Items | Outcome |
|---|---|---|
| Inventoried `/mnt/lego-media-store` | 36 items (2 top-level) | full table in the report §2 |
| Left (board-tracked) | `potato-wars-v2/**` (34 items, 100M) | untouched, verified intact post-cleanup |
| Left (flagged) | `@Recently-Snapshot/` + `desktop.ini` (102 B, Windows system, read-only) | deletion blocked (CIFS read-only attribute; thor uid 1000 cannot remove); no data value; auto-recreated by Windows; optional manual cleanup from NAS admin UI |
| Deleted | — | none (no other transient artifacts existed) |
| Created | `published/` | chuck:chuck 755, write+delete round-trip verified — the P12-C `nas` publish root |

## 4. Deploy runbook location

**`docs/filebridge_p12bc_deploy.md`** — task-16 style, exact
copy-pasteable steps:

- Step 0: baselines + rollback anchors (.env backup, `ss` baseline,
  image tag, access-group snapshot)
- Step 1: build + recreate live `mcp_filebridge` (env gate 0, user
  1000:1000, no ports, health, in-container lint, MCP face smoke)
- Step 2: litellm-proxy restart (**user timing — severs active proxy
  sessions**)
- Step 3: `family-mcp-full` access-group update (exact
  `PUT /v1/access_group/{id}` command — fetch-union-PUT, idempotent;
  verified against installed litellm v1.104.0 source; NOT executed)
- Step 4: public E2E battery (1b token route via Caddy: mint → fetch
  200 + sha256 + Range 206 + cf-cache-status DYNAMIC, bad token 404,
  TTL bounds, second host; P12-A regression battery: dl relay sha256,
  Range 206, upload 401/401/200 + round-trip, `/media/files` policy
  both hosts, pipeline admin 404s; MCP via litellm public; publish-file
  skill wrapper; kill switch; ss port diff)
- Rollback anchors: A old-image rebuild from git `79c39d5` + recreate
  (+ fast tag variant), B litellm config revert, C access-group revert
  from the step-0 snapshot, D token route is additive — **no Caddy
  rollback needed**, E wrapper revert (hot)
- Post-deploy: suggested commit messages (`<area> + imperative
  subject`), `security_todo.md` Phase 12 flip to LIVE, kanban Ideas
  29/30 close, artifact cleanup

## 5. Open items

1. **Deploy itself** — runbook not executed (no live cutover in this
   run). Pending user timing; the litellm restart severs active proxy
   sessions.
2. **Real TTL expiry** — min TTL is 1 h, so public E2E cannot wait out
   an expiry; bounds + `expires_at` verified, expiry purge covered by
   unit tests (fake clock). Any bridge restart revokes all outstanding
   1b tokens (in-process store — by design; re-mintable in one tool
   call).
3. **Dockerfile `HEALTHCHECK`** hardcodes port 8000 — side test
   containers need a `--health-cmd` override; production unaffected.
4. **`@Recently-Snapshot` (102 B)** on the NAS could not be removed from
   thor (CIFS read-only) — optional manual cleanup from the NAS admin
   UI / Windows client.
5. **Two extra compose mounts** beyond the task-enumerated three
   (`data/media/public` rw + `workspace` ro) — required for P12-C blog
   publishing + boot lint (source_roots must exist in-container);
   flagged for user review (TODO 5).
6. **bluebovine publish target** — adapter interface only (D14); no
   implementation (documented contract in `publish_engine.py`).
7. **Matrix-side battery artifact** — one tiny test file under
   `media_jobs/uploads/` from the TODO 6 `/upload` relay check (14-day
   auto-retention).
8. **Kanban** — Ideas 29 (P12-B) / 30 (P12-C) remain open in project 12
   until the deploy lands (runbook post-deploy step 3).

## 6. Verification status of the hard rules

| Rule | Status |
|---|---|
| Env gate 0 for the bridge | ✅ verified on the side test container (`docker inspect … | grep -ciE 'litellm|memory|master|api_key'` = 0) and by construction on the live compose service (env list unchanged) |
| No new host ports | ✅ side test container publishes none; live service defines no `ports:` (runbook K2 re-checks `ss` diff) |
| No secrets in committed-destined files | ✅ `sk-` scan of the full diff + all new files: 0 matches |
| Existing 22 filebridge tests + publish_file tests green | ✅ 107 passed (incl. the 22) + 32/32 wrapper contract |
| No live cutover / no commits / no branch switch | ✅ working tree only; live `mcp_filebridge`, Caddy, litellm-proxy, skill-runner all untouched |
| One-line JSON bridge logs, default-deny, 404-not-403 | ✅ implemented + tested (audit() in fileops.py; `_RequestLog` in app.py; policy tests) |
