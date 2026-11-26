# mcp_filebridge P12-B + P12-C — design & 1b confirmation

**Date:** 2026-11-26 (pi-long-task run `10f37f65`; repo base `79c39d5`)
**Status:** COMPLETE — all sections filled: §1 (1b confirmation,
TODO 1), §2/§3/§4/§6 (P12-B, TODO 3), §5 (P12-C, TODO 4), §7 (security
properties, TODO 7), §8 (test & deploy plan, TODO 6/7).
**Design source of truth:** `security_todo.md` Phase 12 (registry YAML,
phasing, security properties). **Deploy runbook:**
`docs/filebridge_p12bc_deploy.md` (TODO 7, NOT executed — pending user
timing). **Final report:** `docs/filebridge_p12bc_final_report.md`.

**User-approved decisions (2026-11-26):**

- **1b** — the bridge mints a path-bound, TTL'd signed token per thor
  work-area file, served at `GET /media/files/dl/{token}`. Caddy already
  routes `/media/files/*` to the bridge — no Caddyfile change.
- **2a** — `file_pull(source=URL)` = parity with `media_download`
  (arbitrary URLs; the one-line JSON audit log is the trail).
- **3a** — MCP-face auth trusts the litellm key gate (access groups decide
  which keys see the tools); registry policies enforce per-area rules
  regardless of caller.
- **4-published** — NAS publish root = `/mnt/lego-media-store/published/`;
  conservative cleanup of prior-convention artifacts (TODO 2).

---

## 1. 1b confirmation — media-pipeline compatibility (COMPLETE)

**Claim under test:** decision 1b (bridge-minted signed URLs for thor
work-area files) is safe and workable for the media pipeline:

1. Matrix ffmpeg/join ops stay on Matrix-local `media_jobs` paths served by
   Matrix's own `/dl` tokens;
2. bridge tokens serve thor work-area files only (finished artifacts after
   `media_fetch` download);
3. the pipeline token flow is unchanged — `file_pull(source=pipeline token)`
   still relays to Matrix `/dl`, `file_push(dest=matrix_pipeline)` still
   uploads to Matrix `/upload`;
4. zero Matrix changes.

**Verdict: CONFIRMED.** 1b is additive on thor only. Evidence below is a
code trace of `mcp/servers/media/` (the `mcp_media` container — the only
file-ops client of the Matrix pipeline in this repo; the P12-A bridge
merely relays `/dl`/`/upload` and performs no file ops) plus the P12-A
bridge (`mcp/servers/filebridge/app.py`) and the Caddy routes.

### 1.1 What 1b adds (and nothing else)

1b adds exactly one new route to the thor-side bridge:
`GET /media/files/dl/{token}` — a bridge-minted, path-bound, TTL'd token
serving a file under a registered thor work area (the token IS the
credential; 404-not-403; one-line JSON log per mint/serve). It is served
under the existing Caddy route `/media/files/*` → `mcp_filebridge:8000`
(`caddy/Caddyfile` `@blog` lines 33-34 and `@siri_media` lines 81-97), so
**no Caddyfile change** is required. It does not touch Matrix, the
pipeline service, `mcp_media`, or any existing bridge route.

### 1.2 The two token namespaces do not collide

| | Matrix pipeline token (existing) | 1b bridge token (new) |
|---|---|---|
| Public URL | `https://siri.choukalos.com/media/pipeline/dl/<token>` | `https://siri.choukalos.com/media/files/dl/<token>` |
| Minted by | Matrix pipeline `POST /dl_token` (LAN-only) | the bridge, in-process |
| Validated by | Matrix `/dl/{token}` (relay passes through) | the bridge, in-process |
| Serves | Matrix-local `media_jobs` files | thor work-area files only |
| Caddy route | `@siri_pipeline` (Caddyfile 110-131, `handle /dl/*`) | `@siri_media` / `@blog` (`/media/files/*`) |
| TTL | 1–168 h | 1–168 h (parity, see §4 stub) |

Different URL prefix, different Caddy route block, different validator.
An existing Matrix token URL never reaches the new route and vice versa.

### 1.3 Evidence: all ffmpeg/join ops target Matrix-local `media_jobs` paths

The `mcp_media` container is a **thin HTTP client** — all GPU/ffmpeg work
runs on the Matrix pipeline service (`MEDIA_PIPELINE_URL`,
`http://192.168.4.55:8189`):

- `mcp/servers/media/media_pipeline_client.py:64` —
  `_JOB_PREFIX = "/home/chuck/data/comfyui/run/media_jobs/"`: the Matrix
  (GPU host) job dir. `:67` — `_JOB_ROOT` is its parent, the root against
  which relative `media_jobs/...` refs resolve.
- `media_pipeline_client.py:163-171` — `_ensure_source(source)`: the ONLY
  source resolution for the ffmpeg tools. A GPU-host path (starting with
  `_JOB_PREFIX`) passes through unchanged; a local file is uploaded via
  `POST /upload` (multipart, sync) and the returned **`media_jobs` path**
  is used. Either way, the pipeline receives a Matrix-local `media_jobs`
  path.
- `media_pipeline_client.py:651-674` (`trim`), `676-691` (`freeze`),
  `693-714` (`caption`): each POSTs `{"source": self._ensure_source(source),
  ...}` to the pipeline's `/trim` / `/freeze` / `/caption` — ffmpeg
  (re-encode trim, static-clip freeze, drawtext caption) executes **on
  Matrix**, reading/writing Matrix-local `media_jobs` paths. The MCP tools
  (`server.py:1292-1305` `media_trim`, `1335-1348` `media_freeze`,
  `1380-1394` `media_caption`) only validate the staging root
  (`_staging_error`, `server.py:303-321`) and forward; they run no ffmpeg.
- **Join (concat + mix):** `media_pipeline_client.py:600-648`
  (`assemble`) POSTs the shot list to `/assemble`; `server.py:994`
  (`media_assemble` tool description) requires `shots` to be **GPU-host
  paths** ("MUST be GPU-host paths ... do NOT pass locally downloaded
  paths").
  Concat/mix runs on Matrix against Matrix-local `media_jobs` inputs.
  Local inputs to any tool are auto-fetched/re-uploaded
  (`_ensure_local`, `server.py:275-279` → `PIPELINE.fetch` → re-upload),
  so even the inputs land in `media_jobs` before the pipeline touches
  them.
- **No ffmpeg exists in the `mcp_media` image.** `mcp/servers/media/Dockerfile`
  installs only pango/cairo (WeasyPrint), poppler-utils, yt-dlp, and
  WeasyPrint — no ffmpeg. `subprocess` is used exactly once, for yt-dlp
  audio ingest (`server.py:336-351`; the only `subprocess.run` is at
  `:342`, "no ffmpeg needed — the pipeline decodes the container").
  Every ffmpeg invocation in the media pipeline therefore happens on
  Matrix, on `media_jobs` paths.

**Conclusion 1:** ffmpeg/join ops never read or write thor files; they
operate exclusively on Matrix-local `media_jobs` paths, which are served
publicly only through Matrix's own `/dl/{token}` (below). 1b changes
none of this.

### 1.4 Evidence: the pipeline token flow is unchanged (`media_pull`)

- `server.py:1497-1505` (`media_pull`) → `PIPELINE.pull` →
  `media_pipeline_client.py:818-834`: `POST /dl_token` to the Matrix
  pipeline (LAN) with the resolved absolute path + `ttl_hours`
  (1–168 h); the returned URL is
  `PUBLIC_URL + d["url_path"]` where
  `PUBLIC_URL = "https://siri.choukalos.com/media/pipeline"`
  (`media_pipeline_client.py:61-62`). The **token is minted and validated
  on Matrix**; `_resolve_path` (`:173-189`) normalizes relative
  `media_jobs/` refs against `_JOB_ROOT`, so tokens are only ever minted
  for absolute Matrix `media_jobs` paths.
- Public chain (post-P12-A, unchanged by 1b): Caddy `@siri_pipeline`
  (`caddy/Caddyfile:110-131`) strips `/media/pipeline` and routes
  `handle /dl/*` to `mcp_filebridge:8000`; the bridge's
  `GET /dl/{token}` (`app.py:179-209`, `dl_relay`) is a **transparent
  streaming relay** to `{MEDIA_PIPELINE_URL}/dl/{token}` — Range
  passthrough, never buffered, token validation stays on Matrix.
- 1b adds no code path to any of this: the new `/media/files/dl/{token}`
  route is a different FastAPI route under a different Caddy prefix.

**Conclusion 2:** `media_pull` signed URLs (Matrix-minted) and the public
`/media/pipeline/dl/<token>` chain are byte-for-byte unchanged by 1b.

### 1.5 Evidence: finished artifacts land in the thor work area (`media_fetch`)

- `server.py:1232-1262` (`media_fetch`): accepts only `_JOB_PREFIX`
  (Matrix `media_jobs`) paths (`:1234-1240`), downloads via
  `PIPELINE.fetch` (`:1246`) → `media_pipeline_client.py:367-390`:
  `GET {base}/files/{name}` (LAN direct to Matrix :8189) written to
  `dest = PIPELINE_FETCH_DIR` =
  `/home/chuck/data/media/generated/pipeline`
  (`server.py:84-85`; `compose/compose.mcp.yml:148`).
- That fetch dir is under the bridge's `MEDIA_ROOT=/home/chuck/data/media`
  (`compose/compose.mcp.yml` filebridge service) and its top-level
  `generated` subdir is **allowlisted** in
  `mcp/servers/filebridge/filebridge.yaml` (`public_file_serving.allow`).
  The finished artifacts are therefore exactly the class of file 1b
  tokens serve: files under a registered thor work area, path-bound.
- The `media_jobs` side of the same file (Matrix-local) remains reachable
  via Matrix `/dl` tokens for 14 days — the two namespaces coexist
  independently.

**Conclusion 3:** 1b tokens serve thor work-area files only — the finished
artifacts after `media_fetch` (and, per the §3 stub registry, the other
registered work areas). They never serve Matrix `media_jobs` files, which
stay behind Matrix's own `/dl` tokens.

### 1.6 Evidence: `file_pull` / `file_push` relays are unchanged

The P12-B MCP tools (TODO 3) will sit on top of the **existing P12-A
bridge relays**, which 1b does not modify:

- `file_pull(source=pipeline token)` → bridge `GET /dl/{token}`
  (`app.py:179-209`) → Matrix `/dl/{token}` (transparent relay; token
  validated on Matrix). Unchanged.
- `file_push(dest=matrix_pipeline)` → bridge `POST /upload`
  (`app.py:234-284`, `upload_relay`) → Matrix `/upload` (streaming
  multipart; X-Api-Key stripped on the upstream leg; 500 MB relay cap).
  Unchanged. Public entry point keeps the Caddy X-Api-Key gate
  (`caddy/Caddyfile:127-131`).
- The existing `mcp_media` equivalents are likewise untouched:
  `media_put` (`server.py:1467-1483`) → `PIPELINE.put`
  (`media_pipeline_client.py:808-816`) → Matrix `/upload`;
  `media_download` (`server.py:1444-1453`) → `PIPELINE.download`
  (`media_pipeline_client.py:797-806`) → Matrix `/download` (Matrix
  fetches the URL into `media_jobs`); `media_upload`
  (`server.py:1426-1434`) → Matrix `/upload_local` (Matrix-basedir copy).
  None of these reference the new token route.

**Conclusion 4:** the cross-boundary relays used by `file_pull` /
`file_push` (and by `mcp_media` today) are unchanged by 1b; 1b only adds a
new mint/serve pair for thor work-area files.

### 1.7 Zero Matrix changes

- No Matrix pipeline code/config changes: 1b touches only
  `mcp/servers/filebridge/` (new route + token store) and the registry
  (`filebridge.yaml`). The pipeline service, its `/dl_token`, `/dl`,
  `/upload`, `/download`, `/files` endpoints, and `media_jobs` retention
  are all untouched.
- No Caddyfile change: `/media/files/*` already proxies to the bridge on
  both public hosts (`caddy/Caddyfile:33-34` `@blog`, `94-97`
  `@siri_media`). The 1b token URL is reachable on
  `siri.choukalos.com` and `choukalos.com` exactly like the rest of
  `/media/files/*`.
- No `mcp_media` change: no env, no code, no compose entry.
- No new host ports; the bridge stays minimal-env (env gate 0) — the
  token store holds path+expiry, no secrets.

**Implementation note (TODO 3):** FastAPI matches routes in registration
order — the new `GET /media/files/dl/{token}` route MUST be registered
before the `GET /media/files/{filepath:path}` catch-all
(`app.py:317-327`), otherwise `dl/<token>` is swallowed by the catch-all
and 404s (`dl` is not allowlisted). Covered by the route-precedence test
in TODO 3.

### 1.8 Verdict

1b is **safe and workable**: it is additive on thor only (one new bridge
route + in-process token store), the media pipeline's ffmpeg/join work
stays entirely on Matrix-local `media_jobs` paths with Matrix-minted
tokens, the existing token/relay flows are unchanged, and Matrix requires
zero changes. Proceed to P12-B (TODO 3).

---

## 2. MCP face (P12-B) — IMPLEMENTED (TODO 3)

- **Transport:** FastMCP streamable-HTTP endpoint at `POST /mcp` on the
  existing bridge app (`mcp_face.py`, `mcp>=1.10,<2` in
  `pyproject.toml`). `mcp.settings.streamable_http_path = "/mcp"` and
  `stateless_http = True` — each request is independent, so the litellm
  proxy's registry handshake + per-call auth work with no session state
  on our side. The face is mounted LAST (`app.mount("/", ...)` in
  `app.py`) so every explicit route above it wins — including the
  `/media/files/dl/{token}` precedence over the `/media/files` catch-all.
  The session manager's task group is started in the app lifespan
  (uvicorn); the SDK's DNS-rebinding protection is kept ON with
  `allowed_hosts = [mcp_filebridge:*, 127.0.0.1[:*], localhost[:*],
  [::1][:*]]` — the only production caller is the litellm proxy on the
  docker network (Host: `mcp_filebridge:8000`).
- **Auth (decision 3a):** the face carries NO auth of its own — the
  litellm key gate (per-key access groups) decides which callers see the
  tools; registry policies enforce per-area rules regardless of caller.
- **Tools (4):**
  - `file_pull(source, work_area)` — source = http(s) URL (decision 2a
    parity with `media_download`) | bare Matrix `/dl` token (relayed
    through the existing P12-A `GET /dl/{token}`) | media_jobs path
    (absolute `/home/chuck/data/comfyui/run/media_jobs/...` or relative
    `media_jobs/<job_id>/<file>` — both normalize to the Matrix `/files`
    job-dir-relative convention, `media_pipeline_client.fetch`) | a path
    under a registered work area (default-deny: unregistered paths are
    rejected). Destination = any registered writable work area; basename
    collisions suffixed (`name_2.ext`), never overwritten; remote fetches
    stream to `*.part` + atomic `os.replace` (no partial files) with the
    `PULL_MAX_MB` cap (default 500, parity with the upload cap). Returns
    `{local_path, size_bytes, source_type, work_area}`.
  - `file_push(file, destination, subdirectory="", ttl_hours=24)` — file
    must be under a registered work area (default-deny). Destination =
    work-area name (local copy) | `matrix_pipeline` (existing P12-A
    `POST /upload` relay → `{path: media_jobs path}`) | `client` (mints a
    1b signed token, returns `{url, expires_at, token, ttl_hours}` — the
    token IS the credential) | publish-target name (blog/nas — same
    semantics as the publish-file engine; P12-C extracts the engine).
  - `file_work_areas()` / `file_targets()` — enumerate the registry
    (areas with flags + writability; targets with root/subdirs/url_base/
    size_cap_mb/source_roots).
- **LiteLLM registration prep:** the `mcp_filebridge` entry in
  `litellm/config.yml` `mcp_servers` + the `family-mcp-full` access-group
  mechanism land in TODO 5 (config only) / TODO 7 (runbook) — this TODO
  keeps the face reachable and stateless so the registration is a config
  change, not a code change.
- **Logging:** every tool call emits a one-line JSON audit entry via
  `fileops.audit()` (`logger filebridge.fileops`) — `event`, `ts`, the
  tool's key fields (source/destination truncated to 200 chars, paths,
  sizes, token id for mints), `status` ok/error. The HTTP face's
  `_RequestLog` one-line JSON covers the wire-level view (incl. the
  token route's serves).
- **Test harness note:** the MCP session manager's anyio task group must
  be entered and exited in the same task, so tests run it in a
  session-scoped background task (`mcp_session` fixture; pytest-asyncio
  session loop scope in `pyproject.toml`); production uses the app
  lifespan. `tools/list` / `tools/call` are exercised with raw JSON-RPC
  POSTs (httpx ASGITransport) — no session headers needed (stateless).

## 3. Registry schema + boot lint (P12-B) — IMPLEMENTED (TODO 3)

- **Schema** (`filebridge.yaml`, loaded by `registry.py`):
  - `public_file_serving` (P12-A, unchanged): `root` + `allow` (the
    `/media/files` catch-all policy; default-deny, 404-not-403).
  - `work_areas`: name → `{path: <abs>}` (local area) or `{api: <url>}`
    (Matrix pipeline, first-class per D12) — exactly one of the two.
    Optional boolean flags: `remote_write: false` (D13 siri-only),
    `automount: true` (autofs — missing path is a warning, not an error),
    `shared_output: true` (non-siri persistent output). Shipped areas:
    `media_staging` (`/home/chuck/workspace/media`), `pipeline_fetch`
    (`/home/chuck/data/media/generated/pipeline`), `siri_outputs`
    (`remote_write: false`), `nas_media_store` (`automount +
    shared_output`), `matrix_pipeline` (`api: http://192.168.4.55:8189`).
  - `publish_targets`: name → `{root, subdirs[], default_subdir,
    url_base, source_roots[], size_cap_mb}`. Shipped: `blog` (existing
    publish-file semantics — subdirs ai/images/audio/video/tabs,
    `'files'` banned, 500 MB cap) and `nas`
    (`/mnt/lego-media-store/published/`, flat, `url_base: ""` — not
    public; access via work-area tools / 1b tokens, decision
    4-published). `bluebovine` reserved (future, D14 — interface only).
- **Default-deny:** anything not registered is invisible to the MCP face
  (unregistered pull sources / push files / destinations are rejected)
  and to public serving (404, never 403).
- **Lint** (`registry.lint()` — errors + warnings): all three sections
  present; each work area has exactly one of path/api; local paths exist
  (missing + `automount` → warning "autofs expected", else error);
  no overlapping area paths (nested = ambiguous `area_of_path`);
  flags are booleans; each publish target has an existing `root`, no
  `'files'` subdir, a valid `url_base` (https:// or empty), non-empty
  `source_roots`, `size_cap_mb` > 0; **D13 consistency** — a
  `remote_write: false` area is never in `public_file_serving.allow`
  (siri_outputs must not be publicly served, finding 12.4).
- **Fail-fast:** linted at import (module level in `app.py`) — a broken
  registry prevents boot (`main()` raises `SystemExit` with the error
  list) — and standalone: `python app.py lint` exits 0 with
  `registry lint: OK (N work areas, M publish targets)` or 1 with
  `registry lint: FAILED` + one error per line. Test coverage:
  `tests/test_registry.py` (green registry, every lint rule, CLI both
  ways, and the shipped registry lints green on thor).

## 4. Token design — 1b signed tokens (P12-B) — IMPLEMENTED (TODO 3)

- **Mint:** ONLY via the MCP face — `file_push(file, destination="client",
  ttl_hours=24)` (no public mint endpoint; D10 holds). Path-bound to the
  exact resolved file path; TTL clamped to 1–168 h (default 24 — parity
  with Matrix `/dl_token`); token = 32 hex chars (`secrets.token_hex(16)`) —
  the token IS the credential, no other auth. Minting a file under a
  `remote_write: false` area (siri_outputs) is rejected for ALL callers
  (D13). Every mint → one-line JSON audit (`event: token_mint`, token,
  path, ttl_h, via, status).
- **Store:** in-process `TokenStore` (`tokens.py`) — dict
  token → {path, expires_at}; nothing sensitive (path + expiry); env
  gate stays 0. A restart revokes all outstanding tokens (acceptable:
  they're TTL'd conveniences, re-mintable in one tool call).
- **Serve:** `GET /media/files/dl/{token}` (`app.py`) — registered
  BEFORE the `/media/files/{filepath:path}` catch-all (FastAPI matches
  in registration order; `dl` is not allowlisted, so without precedence
  the catch-all would 404-swallow every token URL). Unknown / expired /
  file-deleted → **404** (never 403 — do not leak which tokens exist);
  `FileResponse` → native Range support. Every serve → the HTTP face's
  one-line JSON request log (path includes the token — the token is the
  credential and the log is container-local; same exposure class as the
  P12-A `/dl/{token}` relay log).
- **Public URL base:** `FILEBRIDGE_PUBLIC_URL` env (default
  `https://siri.choukalos.com/media/files`) — Caddy routes `/media/files/*`
  to the bridge on both hosts, so the URL works on `siri.choukalos.com`
  and `choukalos.com`; not a secret (the token is the credential).
- **Tests:** `tests/test_tokens.py` — mint/serve byte-identical + Range
  206, bad token 404, expiry 404 (fake clock), path-binding (token-A
  serves A, delete-A → 404, token-B unaffected), route precedence over
  the catch-all, TTL clamp bounds, public URL shape.

## 5. Publish engine + adapter (P12-C) — IMPLEMENTED (TODO 4)

- **Extraction:** `skills/publish_file/skill.py` (validated / atomic /
  size-capped / idempotent; source roots restricted; subdirs
  ai/images/audio/video/tabs, `'files'` banned, 500 MB cap, duplicate =
  no-op success) is extracted into
  `mcp/servers/filebridge/publish_engine.py`, PARAMETERIZED BY TARGET
  CONFIG (the registry `publish_targets` section: root, subdirs,
  default_subdir, url_base, source_roots, size_cap_mb). The blog target's
  exact behavior is preserved (same validation order, same error
  messages, same report shape, same 0644 chmod, same `.publish_*` temp +
  `os.replace` atomicity, same sha256 dedup no-op with mtime unchanged).
  The old `fileops.publish_to_target` (the P12-B interim publish path) is
  deleted — the engine is the single publish engine; `file_push`
  (destination = publish target) delegates to it.
- **`PublishTarget` adapter interface (D14):** a `runtime_checkable`
  `Protocol` — `name: str` + `publish(file, subdir, name, overwrite) ->
  report` (the report shape; `PublishError` on validation failure). The
  protocol docstring documents the contract any implementation must
  honor (source-root default-deny, destination containment, size cap,
  atomic visibility, idempotent republish). **LocalFSTarget** implements
  it for local-filesystem targets (blog, nas). **bluebovine is
  interface-only** — the docstring documents what a remote implementation
  must provide (an authenticated `upload(file) -> {url, sha256?}` API
  round-trip, then the same report shape); NO bluebovine implementation
  exists (D14).
- **`file_publish(file, target, destination_name="",
  subdirectory="", overwrite=false)` MCP tool** (the 5th tool on the
  face): wraps the engine; `subdirectory=""` = the target's default
  (blog: `ai`; flat targets like nas: `""`); returns the skill's report
  shape `{summary, artifact_path, report: {path, url, size_bytes,
  sha256, destination_name, subdirectory[, duplicate]}}` — `url` is
  `null` for non-public targets (nas). One-line JSON audit per call
  (`event: file_publish`).
- **`POST /publish` HTTP endpoint (ai-net only):** JSON body
  `{source_path, target, destination_name?, subdirectory?, overwrite?}`
  → 200 = the report shape; 400 = `{error}` (validation / unknown target
  / bad body). Wrapping the SAME engine function as the tool. NOT routed
  publicly: Caddy has no `/publish` route and the container publishes no
  host ports — reachable only from the ai-net docker network (the trust
  model of the existing `/upload` / `/dl` ai-net surfaces). One-line JSON
  audit per call (`event: publish`).
- **Thin skill wrapper:** `skills/publish_file/skill.py` keeps the
  original contract (skill.yml inputs: source_path, destination_name,
  subdirectory, overwrite — unchanged) and POSTs to
  `http://mcp_filebridge:8000/publish` (ai-net; the skill runs inside
  skill-runner on ai-net, where the docker DNS name resolves; override
  via `PUBLISH_FILE_BRIDGE_URL`), passing the result through VERBATIM.
  NO fallback — if the bridge is down the skill fails with a clear error
  (single engine, no duplicate logic). The wrapper keeps the `SUBDIRS`
  enum for fail-fast input validation (skill.yml enum-drift regression
  still tested). `agents-skills/publish-file/SKILL.md` notes the engine
  move. `skills/publish_file/test_skill.py` is updated to test the
  wrapper contract (request shape, pass-through, rejection surfacing,
  bridge-down error, enum drift, thinness).
- **Publish surface vs D13:** the engine enforces the target's
  `source_roots` (the skill's existing boundary, now parameterized) — it
  does NOT write to `siri_outputs` (a publish target is never
  siri_outputs) and mints no public tokens; D13 is unaffected.
- **Tests:** `tests/test_publish.py` — engine parameterization (blog +
  nas), all ported skill cases (subdir enum, `'files'` ban, idempotent
  republish, overwrite force flag, distinct destinations), source
  validation (source_roots / symlink / absolute / missing / size cap /
  destination_name charset), nas flat + non-public, adapter protocol
  check, `file_publish` tool, `POST /publish` (200 / 400 / duplicate /
  audit). The P12-B `file_push` publish-target tests stay green via
  delegation.

## 6. D13 — shared persistent output — IMPLEMENTED (TODO 3)

- `siri_outputs` is siri-only: `remote_write: false` in the registry.
  Enforcement (`fileops.area_write_error` + the token-mint guard):
  - `file_pull(..., work_area="siri_outputs")` → rejected for ALL
    callers ("D13: siri-only").
  - `file_push(file, destination="siri_outputs")` → rejected for ALL
    callers.
  - `file_push(file, destination="client")` where the file is under
    `siri_outputs` → rejected (no public tokens for siri files — the
    public-serving allowlist also excludes it, finding 12.4).
  - The lint's D13-consistency check fails boot if a `remote_write:
    false` area ever lands in `public_file_serving.allow`.
  - Siri keeps its own access path (skill API artifact endpoint + LAN) —
    unchanged.
- Non-siri persistent output → `nas_media_store`
  (`/mnt/lego-media-store`, `automount + shared_output: true`); publish
  root `/mnt/lego-media-store/published/` (decision 4-published; created
  in TODO 2, chuck-owned 755).

## 7. Security properties

From `security_todo.md` Phase 12 "Security properties" + the test
evidence in §8 (all verified 2026-11-26 in this run; public-surface
items are re-verified by the deploy runbook's battery).

- **One audited public file edge.** Every cross-boundary file move goes
  through one service (`mcp_filebridge`) with one one-line-JSON log
  format: the HTTP face's `_RequestLog` (method, path, upstream,
  status, bytes_in, bytes_out, duration_ms, client_ip) + the MCP
  face's `fileops.audit()` entries (event, ts, tool, key fields,
  status). The 1b token route logs every mint (`event: token_mint`,
  token, path, ttl, via) and every serve (request log — the token is
  the credential and the log is container-local; same exposure class
  as the P12-A `/dl/{token}` relay log). Feeds Phase 11 monitoring
  (canaries, log anomalies, size/rate limits). No other service logs
  public file traffic — `mcp_media` and skill-runner no longer serve
  `/media/files` (P12-A cutover).
- **Minimal-env container preserved.** The bridge env is exactly
  `FILEBRIDGE_PORT`, `MEDIA_PIPELINE_URL`, `MEDIA_ROOT`,
  `UPLOAD_MAX_MB`, `TZ` (+ `FILEBRIDGE_PUBLIC_URL` optional) — no
  LiteLLM key, no memory key, no master key, no API key. Hard gate:
  `docker inspect <bridge> | grep -ciE 'litellm|memory|master|api_key'`
  = 0 (verified on the side test container; the compose env list is
  unchanged by P12-B/C). The token store holds path + expiry only —
  nothing sensitive, in-process. **No new host ports** (the service
  defines no `ports:`; the side test container published none —
  `docker port` empty; runbook K2 re-checks the `ss` diff).
- **Default-deny registry + fail-fast lint.** Anything unregistered is
  invisible to the MCP face (pull sources / push files / destinations
  rejected) and to public serving (404, never 403). The registry is
  linted at import (a broken registry prevents boot — `SystemExit`)
  and standalone (`python app.py lint`, exit 0/1); the lint includes
  the D13 consistency rule (a `remote_write: false` area can never
  land in `public_file_serving.allow`).
- **Kill switch.** `docker stop mcp_filebridge` kills the public file
  routes (dl relay, upload relay, `/media/files` both hosts, the 1b
  token route, the MCP face, `POST /publish`) while Matrix and
  skill-runner stay up (P12-A live-verified; re-verified by the
  runbook battery K1). Matrix is untouched by the bridge's state —
  token validation for pipeline tokens stays on Matrix.
- **Rollback.** Old image rebuild from git `79c39d5` + recreate (the
  fast variant tags the pre-deploy image — runbook anchor A); litellm
  config revert + restart (anchor B); access-group revert from the
  step-0 snapshot (anchor C). The 1b token route is **additive — no
  Caddy rollback needed** (the Caddyfile is unchanged by this deploy;
  anchor D). A bridge restart revokes all outstanding 1b tokens
  (in-process store) — acceptable: they're TTL'd conveniences,
  re-mintable in one tool call.
- **1b token surface.** No new public WRITE surface — minting is ONLY
  via the MCP face (`file_push destination="client"`), which sits
  behind the litellm key gate (decision 3a); D10 holds. The token
  namespace is disjoint from Matrix pipeline tokens (different URL
  prefix, different Caddy route block, different validator — §1.2).
  Tokens are path-bound, TTL'd (1–168 h), 128-bit random, and the
  token IS the credential; unknown/expired/deleted → 404 (never 403 —
  no token enumeration).
- **MCP face exposure.** The face carries no auth of its own (decision
  3a — the litellm key gate + per-key access groups decide which
  callers see the tools; registry policies enforce per-area rules
  regardless of caller). The SDK's DNS-rebinding protection stays ON
  (`allowed_hosts` = `mcp_filebridge:*`, loopback) — the only
  production caller is the litellm proxy on the docker network. The
  face is stateless (no session state to leak) and mounted LAST so
  every explicit route wins. `POST /publish` is ai-net only (no Caddy
  route, no published ports) — same trust model as the existing
  `/upload` / `/dl` ai-net surfaces.
- **D13 (siri-only outputs).** `siri_outputs` is `remote_write: false`:
  `file_pull`/`file_push` writes AND `client`-token mints are rejected
  for ALL callers (tested); the public allowlist excludes it (finding
  12.4, resolved at the edge + in the registry); the lint fails boot
  if it ever drifts into the allowlist. Non-siri persistent output →
  `nas_media_store` (`shared_output`), publish root
  `/mnt/lego-media-store/published/` (decision 4-published).
- **Publish engine boundary.** The engine enforces the target's
  `source_roots` (default-deny), destination containment, size cap,
  atomic visibility (`.publish_*` temp + `os.replace`), idempotent
  republish — the skill's existing semantics, now parameterized. It
  never writes to `siri_outputs` and mints no public tokens; the
  `nas` target is non-public (`url_base: ""`) — NAS access stays
  behind the work-area tools / 1b tokens.

## 8. Test & deploy plan — COMPLETE (TODO 6 / TODO 7)

### Unit (green 2026-11-26)

```
$ PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 -m pytest mcp/servers/filebridge/tests/ -q
107 passed in 46.08s
$ PYTHONPATH=/home/chuck/homelab/tmp/pydeps python3 skills/publish_file/test_skill.py
PASS: 32  FAIL: 0
```

107 = the existing 22 P12-A tests (test_policy / test_dl_relay /
test_upload — all green) + 59 P12-B (registry load/lint + CLI +
fail-fast, token mint/serve/expiry/path-binding/route-precedence,
`file_pull` all 4 source types with stubbed upstreams, `file_push`
work-area/matrix_pipeline/client/publish-target, D13 rejection for all
callers, MCP `tools/list` + `tools/call` via raw JSON-RPC against the
ASGI app) + 26 P12-C (engine parameterization blog + nas, ported skill
cases, source validation, `file_publish` tool, `POST /publish`, adapter
protocol check). Registry lint on the shipped registry:
`python app.py lint` → exit 0, `registry lint: OK (5 work areas, 2
publish targets)` (also verified inside the side test container).

### E2E — side test container only (TODO 6, green 2026-11-26)

`mcp_filebridge_test` on ai-net port 8001 (same env + mounts, **no
published host ports**, user 1000:1000, env gate 0) — 43/43 checks
passed (`tmp/e2e_filebridge_test.py`): MCP `initialize`/`tools/list`/
`tools/call` (all 5 tools incl. D13 + default-deny negatives +
DNS-rebinding refusal), `POST /publish` (blog/nas/duplicate/overwrite/
400s), 1b token route (mint → fetch 200 + sha256 + Range 206; bad
token 404; TTL bounds; D13), `/media/files` policy (allowlisted 200;
siri_outputs / non-allowlisted / traversal / directory 404),
`/health` + `pipeline_reachable` vs the real Matrix. The battery found
+ fixed one real bug (double module import under script-mode boot —
`mcp_face._app()`). Container torn down; test image
`mcp_filebridge_p12bc_test` kept (distinct tag — the live
`ai-mcp-mcp_filebridge` image untouched).

### Deploy (runbook — NOT executed in this run)

`docs/filebridge_p12bc_deploy.md` (task-16 style): baselines + rollback
anchors → build + recreate live `mcp_filebridge` (env gate 0, no
ports, health, in-container lint) → litellm-proxy restart (**user
timing — severs active proxy sessions**; applies the `mcp_servers`
entry) → `family-mcp-full` access-group update (exact
`PUT /v1/access_group/{id}` command, fetch-union-PUT, idempotent;
verified against installed litellm v1.104.0 source; NOT executed) →
public E2E battery (1b token route via Caddy: mint → fetch 200 +
sha256 + Range 206 + cf-cache-status DYNAMIC, bad token 404, TTL
bounds, second host; full P12-A regression battery: dl relay sha256,
Range 206, upload 401/401/200 + round-trip, `/media/files` policy both
hosts, pipeline admin 404s; MCP via litellm public; publish-file skill
wrapper — hot, no skill-runner restart; kill switch; `ss` port diff)
→ rollback anchors (A old-image rebuild from git `79c39d5` + recreate;
B litellm config revert; C access-group revert; **D token route is
additive — no Caddy rollback needed**; E wrapper revert) → post-deploy
(suggested commit messages, `security_todo.md` Phase 12 flip to LIVE,
kanban Ideas 29/30 close, artifact cleanup).

**NO live cutover was performed in this task run** — the live
`mcp_filebridge`, Caddy, litellm-proxy, and skill-runner are all
untouched; the deploy is pending user timing.
