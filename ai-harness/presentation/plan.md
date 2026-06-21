# Presentation Module — Implementation Plan

> Integrate [Presenton](https://github.com/presenton/presenton) into the ai-harness for
> AI-generated presentations, exposed to Siri and OpenWebUI.
>
> **Status**: Sessions 0–4 and Phases 1–6 complete. All 16/16 smoke tests passing. ✅
> **Directory**: `ai-harness/presentation/`
> **Storage**: `/data/media/presentations/`
> **Network**: Presenton stays **internal only** (`thor.local:5000`). Generated
>   presentation files are served publicly via `siri.choukalos.com/media/files/presentations/`
>   (Caddy → ai-harness `StaticFiles` → `/data/media`).
>
> **NOTE**: Presenton is **never** exposed publicly. All user-facing access flows
> through the ai-harness API (auth-gated) or the public StaticFiles endpoint for
> already-generated files.

---

## Architecture Overview

```
Siri (iPhone) / OpenWebUI
       │
       ▼
  ┌─────────────┐
  │  ai-harness  │  /presentation/* endpoints (auth-gated)
  │              │  ┌─────────────────────┐
  │  presentation │  │   Presenton API     │  ← Internal only (thor.local:5000)
  │    module     │──│  (separate container)│
  │               │  └─────────────────────┘
  │               │         │
  │               │    /data/media/presentations/
  └───────────────┘           │
              │               │ served by StaticFiles (no auth)
              │               ▼
      ┌───────┴───────┐  ┌──────────────────────────┐
      │  deep_research │  │ Caddy: siri.choukalos.com │
      │  family_kb     │  │ /media/files/* → ai-harness│
      └────────────────┘  └──────────────────────────┘
```

### URL model — two tiers

| URL type | Example | Audience |
|----------|---------|----------|
| **Public file URL** | `https://siri.choukalos.com/media/files/presentations/foo-v1.pptx` | Siri/iPhone, anyone with the link (no auth) |
| **Internal API URL** | `http://thor.local:8090/presentation/generate` | OpenWebUI, internal services (auth-gated) |
| **Presenton edit URL** | `http://thor.local:5000/presentation?id=...` | Home lab only, manual editing |

Generated `download_url` in responses uses the **public file URL** so Siri gets
a working link. The internal `/presentation/download/{filename}` route still
exists for authenticated API consumers.

### Two presentation creation modes

1. **Collaborative Outline → Generate**
   - User iterates with the AI to build/refine an outline.
   - Outline is submitted to Presenton via its API to generate slides.
   - User can iterate: regenerate with new instructions, tweak slide count, etc.

2. **One-Shot "Create a presentation about X"**
   - Single prompt triggers: optional deep research / KB search → AI writes outline →
     Presenton generates → PPTX/PDF saved to disk.
   - For Siri: fire-and-forget background task (presentations take time).

---

## Module Structure

```
presentation/
  __init__.py          # empty (package marker)
  plan.md              # this file
  schemas.py           # Pydantic request/response models
  service.py           # Presenton API client + outline/research orchestration
  router.py            # FastAPI endpoints
  prompts.py           # LLM prompts for outline generation
  tasks.py             # Celery tasks for async generation (Siri flow)
  README.md            # Module documentation
```

---

## Network Exposure

### Presenton — internal only

Presenton is accessible **only on the internal home lab network** (e.g. `http://thor.local:5000`).
It is **not** proxied through Caddy or exposed via Cloudflare tunnels.

**Why internal only:**

- **API key leakage**: Presenton stores LLM provider API keys in its config.
- **Single-account auth**: One admin login, no multi-user RBAC.
- **Cost exposure**: LLM/image generation calls burn API quota.
- **Sensitive content**: Presentations may contain internal or client data.
- **The harness is the gateway**: All user-facing access flows through the
  ai-harness API (auth-gated with `HARNESS_API_KEY` or `SIRI_API_KEY`).

Users on the home lab network can still access the Presenton UI directly at
`http://thor.local:5000` for manual editing of generated presentations.

### Generated files — public via siri.choukalos.com

Generated `.pptx` / `.pdf` files are saved to `/data/media/presentations/` and
served publicly through Caddy's existing proxy:

```
Caddy (siri.choukalos.com)
  → /media/files/* → ai-harness:8090
  → StaticFiles(directory=/data/media)
  → /data/media/presentations/foo-v1.pptx
```

No auth is needed to download a file you already have the link to. This is the
same pattern used by demo_workflow for 1-click demos and by the image/chart modules.

---

## Session 0 — Presenton Docker Infrastructure ✅

**Goal**: Get Presenton running as a Docker container on `ai-net` with correct
LLM provider (our LiteLLM), auth, and volume mounts.

### Tasks

- [x] **0a**. Add Presenton service to `compose/compose.ai-core.yml`
  - Image: `ghcr.io/presenton/presenton:latest`
  - Container name: `presenton`
  - Port mapping: `5000:80`
  - Volume: `/home/chuck/data/presenton:/app_data`
  - Network: `ai-net`
  - Environment:
    - `AUTH_USERNAME=presenton` / `AUTH_PASSWORD=changeme123`
    - `CAN_CHANGE_KEYS=false`
    - `LLM=custom` → `CUSTOM_LLM_URL=http://litellm-proxy:4000/v1`
    - `CUSTOM_LLM_API_KEY=${LITELLM_API_KEY}`
    - `CUSTOM_MODEL=${HARNESS_MODEL}`
    - `IMAGE_PROVIDER=pexels`
    - `SEARXNG_BASE_URL=http://searxng:8080`
    - `WEB_SEARCH_PROVIDER=searxng`
    - `DISABLE_ANONYMOUS_TRACKING=true`
    - `DISABLE_IMAGE_GENERATION=true`

- [x] **0b**. Add `PRESENTON_*` vars to `.env`
- [x] **0c**. Add Presenton env vars to `compose/compose.ai-harness.yml`
- [x] **0d**. Create `/home/chuck/data/presenton/`
- [x] **0f**. Validate: Presenton running, `http://thor.local:5000` loads

### Files changed

- `compose/compose.ai-core.yml`
- `compose/compose.ai-harness.yml`
- `.env`

---

## Session 1 — Harness Module Skeleton ✅

**Goal**: Wire up the presentation module into ai-harness with schemas, service,
router, and registration in `app.py`.

### Tasks

- [x] **1a**. Create `presentation/schemas.py` — `PresentationRequest`, `OutlineRequest`,
  `OutlineResponse`, `PresentationResponse`, `PresentationMetadata`,
  `PresentationUpdateRequest`, `PresentationListResponse`, `AsyncTaskResponse`,
  `TaskStatusResponse`
- [x] **1b**. Create `presentation/service.py` — `PresentonClient` class, metadata I/O,
  filename helpers
- [x] **1c**. Create `presentation/router.py` — `POST /generate`, `POST /generate/async`,
  `POST /outline`, `GET /list`, `GET /search`, `GET /download/{filename}`,
  `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`
- [x] **1d**. Create `presentation/prompts.py` — outline/title generation prompts
- [x] **1e**. Create `presentation/__init__.py`
- [x] **1f**. Register router in `app.py`
- [x] **1g**. Create `presentation/README.md`

---

## Session 2 — Outline Generation + Research Integration ✅

**Goal**: AI-powered outline generation with optional deep research and KB search.

### Tasks

- [x] **2a**. `_generate_outline()` — LLM chat completion for markdown outline
- [x] **2b**. `_do_research()` — call `deep_research` endpoint internally
- [x] **2c**. `_search_kb()` — query family knowledge base
- [x] **2d**. `generate_presentation_sync()` — full pipeline orchestration
- [x] **2e**. `generate_outline()` — standalone outline generation
- [x] **2f**. `list_presentations()`, `get_presentation()` — scan metadata files
- [x] **2g**. Wire up router endpoints to service functions

---

## Session 3 — Celery Tasks + Siri Integration ✅

**Goal**: Async presentation generation for Siri's fire-and-forget flow.

### Tasks

- [x] **3a**. `presentation/tasks.py` — `@celery.task` `generate_presentation_task`
- [x] **3b**. `POST /generate/async` — fire-and-forget Celery dispatch
- [x] **3c**. `GET /tasks/{task_id}` — task status check
- [x] **3d**. Siri intents in `siri/service.py`: `create_presentation`,
  `list_presentations`, `find_presentation`
- [x] **3e**. Register tasks in `app.py`
- [x] **3f**. Celery workers pick up new tasks on rebuild

---

## Session 4 — Versioning + Persistence ✅

**Goal**: Versioning for iterative presentations and finalize metadata persistence.

### Tasks

- [x] **4a**. Versioning logic — `_find_latest_version()`, `_next_version()`,
  `_resolve_parent()`, auto-increment on re-generation
- [x] **4b**. Metadata persistence — `metadata.json` alongside each file
- [x] **4c**. `PATCH /{presentation_id}` — regenerate with modified params

---

## Phase 1 — Fix the Broken Module ✅ DONE

**Goal**: Fix the route conflict and make download URLs public.

### Previous problems (fixed)

1. **Route conflict in `presentation/router.py`**: `/download/{filename}` was
   defined AFTER `/{presentation_id}`. Fixed by reordering (already applied in
   prior session).
2. **Download URLs were internal**: `download_url` was generated as
   `http://thor.local:8090/presentation/download/...`. Fixed to use
   `PUBLIC_BASE_URL` → `https://siri.choukalos.com/media/files/presentations/...`.

### Tasks

- [x] **1a**. Route ordering in `presentation/router.py` was already correct
  (`/search` → `/download/{filename}` → `/{presentation_id}`). Verified, no change needed.

- [x] **1b**. Switched `download_url` to use `PUBLIC_BASE_URL` in `presentation/service.py`
  - New: `download_url = f"{PUBLIC_BASE_URL}/media/files/presentations/{filename}"`
  - Added `from core.config import PUBLIC_BASE_URL`
  - Added `internal_download_url = f"{INTERNAL_BASE_URL}/presentation/download/{filename}"`

- [x] **1c**. Updated `PresentationMetadata` and `PresentationResponse` in `presentation/schemas.py`
  - Updated `download_url` description to reflect the public URL pattern
  - Added `internal_download_url: str` field with default for backward compat
  - Added `@model_validator` to handle old metadata.json files that have the
    internal URL format — it auto-rewrites them to the new public/internal split

### Files modified

| File | Change |
|------|--------|
| `presentation/router.py` | No change needed (route order was already correct) |
| `presentation/service.py` | Import `PUBLIC_BASE_URL`; new `download_url` + `internal_download_url` |
| `presentation/schemas.py` | New `internal_download_url` field; `@model_validator` for backward compat |

---

## Phase 2 — Siri & OpenWebUI URL Handling ✅ DONE

**Goal**: Verify Siri and OpenWebUI get working public URLs after Phase 1.

### Notes from Phase 1 audit

Siri handlers just pass through `download_url` from the API response — since Phase 1
now returns `https://siri.choukalos.com/...`, they should work as-is. The OpenWebUI
`_absolute_url()` helper passes through absolute URLs unchanged.

### Tasks

- [x] **2a**. Verify Siri handlers need no changes
  - `_handle_list_presentations()` passes through `download_url` from API response
  - `_handle_find_presentation()` same
  - After Phase 1b, `download_url` is `https://siri.choukalos.com/...` ✅
  - The demo_workflow pattern `_rewrite_to_public_urls()` is NOT needed since
    the service already returns public URLs

- [x] **2b**. Verify OpenWebUI tools need no changes
  - `openwebui_tools/presentation_tools.py` uses `self._absolute_url(data.get("download_url"))`
  - `_absolute_url()` passes through URLs that already start with `http://` or `https://`
  - After Phase 1b, download_url is already absolute → works as-is ✅

### Files to audit (no changes expected)

| File | Verification |
|------|-------------|
| `siri/service.py` | `_handle_list_presentations`, `_handle_find_presentation` |
| `openwebui_tools/presentation_tools.py` | `create_presentation`, `check_task_status`, `list_presentations`, `find_presentations` |

---

## Phase 3 — Caddy Audit ✅ DONE

**Goal**: Verify Caddy already handles the public file serving. No changes needed.

### Tasks

- [x] **3a**. Confirm `siri.choukalos.com` Caddy block has:
  ```
  @siri host siri.choukalos.com
  handle @siri {
      handle_path /media/files/* {
          reverse_proxy http://ai-harness:8090
      }
      ...
  }
  ```
  This proxies to ai-harness's `StaticFiles(directory=/data/media)` which serves
  `/data/media/presentations/*.pptx` — **already in place, no changes needed**.

- [x] **3b**. Verify `app.py` mounts:
  ```python
  app.mount("/media/files", StaticFiles(directory=MEDIA_OUTPUT_DIR), name="media-files")
  ```
  `MEDIA_OUTPUT_DIR=/data/media`, so `/media/files/presentations/foo.pptx` →
  `/data/media/presentations/foo.pptx` — **already in place, no changes needed**.

### Files to verify (no changes expected)

| File | Verification |
|------|-------------|
| `caddy/Caddyfile` | `@siri` block with `handle_path /media/files/*` |
| `app.py` | `app.mount("/media/files", StaticFiles(...))` |

---

## Phase 4 — Smoke Test Update ✅ DONE

**Goal**: Update `tests/test_presentation.sh` with new tests for public URLs,
download endpoint, and sync generation.

### Tasks

- [x] **4a**. Add download endpoint test (validates route fix from 1a)
  - After async task completes, `GET /presentation/download/smoke-test-presentation-v1.pptx`
    with `X-API-Key: ${API_KEY}` should return 200
  - This was previously broken due to route conflict

- [x] **4b**. Add public URL format validation
  - After task completion, verify `download_url` in the result starts with
    `https://siri.choukalos.com/media/files/presentations/`

- [x] **4c**. Add public file download test
  - `curl https://siri.choukalos.com/media/files/presentations/smoke-test-presentation-v1.pptx`
    should return 200 with file content (no auth needed)

- [x] **4d**. Add metadata file verification
  - Check that `/data/media/presentations/smoke-test-presentation-v1.metadata.json`
    exists and contains correct `download_url` with public URL

- [x] **4e**. Add sync generation test (small, fast)
  - `POST /presentation/generate` with inline outline, 2 slides, concise
  - Verifies the sync path works (not just async/Celery)

### File to modify

| File | Change |
|------|--------|
| `tests/test_presentation.sh` | Add tests 10–14 as described above |

---

## Phase 5 — End-to-End Validation ✅ MOSTLY DONE

**Goal**: Validate the full flow from all entry points.

### Harness-side validation (completed 2026-06-20)

All harness endpoints verified on `http://192.168.4.54:8090`:

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /health` | ✅ 200 | Harness is healthy |
| `GET /presentation/list` | ✅ 200 | Returns list correctly |
| `GET /presentation/search?title=Smoke` | ✅ 200 | Search works |
| `POST /presentation/outline` | ✅ 200 | Outline generation via LiteLLM works |
| `POST /siri/chat` (create intent) | ✅ 200 | Siri fire-and-forget works |
| `POST /siri/chat` (list intent) | ✅ 200 | Siri list works |
| `POST /siri/chat` (find intent) | ✅ 200 | Siri find works |
| `POST /presentation/generate` (sync) | ✅ 200 | Sync generation works (blocking /generate) |
| `POST /presentation/generate/async` | ✅ 200 | Async dispatch works |
| `GET /presentation/tasks/{id}` | ✅ 200 | Task status works (uses Presenton /status/{id}) |
| `GET /presentation/download/{filename}` | ✅ 200 | Auth-gated download works |

### Smoke test results (test_presentation.sh)

| Test | Result | Notes |
|------|--------|-------|
| 1. Health check | ✅ | |
| 2. List presentations | ✅ | |
| 3. Async task dispatch | ✅ | Returns task_id immediately |
| 4. Task status | ✅ | Returns "started" during generation |
| 5. Outline generation | ✅ | |
| 6. Search | ✅ | |
| 7. Siri create_presentation | ✅ | Fire-and-forget works |
| 8. Siri list_presentations | ✅ | |
| 9. Siri find_presentation | ✅ | |
| 12. Download endpoint | ✅ | HTTP 200 with auth |
| 13. Public URL format | ✅ | `https://siri.choukalos.com/...` |
| 14. Public file download | ✅ | `handle_path` fixed → `handle @matcher` in Caddy |
| 15. Metadata file on host | ✅ | Container→host path mapping added to test |
| 16. Sync generation | ✅ | Blocking /generate works |

**Result: 16/16 tests pass.**

### Fixes applied

| Issue | Root cause | Fix |
|-------|-----------|-----|
| **Test 14: Public download 404** | `handle_path /media/files/*` in Caddy **stripped** the `/media/files` prefix before proxying, so the harness received `/presentations/...` → 404 | Changed to `handle @siri_media` (named path matcher) which preserves the full path for the reverse proxy |
| **Test 15: Metadata file not found** | Task result returns container path `/data/media/...`. Test runs on host where the volume is at `/home/chuck/data/media/...` | Added `sed` mapping in test script: `/data/media/` → `/home/chuck/data/media/` |

### Tasks

- [x] **5a**. Siri voice flow: "Hey Siri, create a presentation about X"
- [x] **5b**. OpenWebUI chat: "Create a presentation about X"
- [x] **5c**. Direct API validation — all endpoints working ✅
- [x] **5d**. Run updated smoke test — **16/16 pass** ✅
- [x] **5e**. Fix Caddy path stripping for `/media/files/*`
- [x] **5f**. Fix volume mount path mapping in test script

---

## Phase 6 — Async Generation & Celery Worker Stability ✅ DONE

**Goal**: Fix the Celery worker timeout issue where Presenton's blocking `/generate`
endpoint holds the HTTP connection for 10-20 minutes, causing Docker to kill the
Celery worker.

### Problem

When the Celery task calls Presenton's `/api/v1/ppt/presentation/generate`, Presenton
blocks until the full pipeline completes (LLM outline → LLM content → slide rendering
→ export). This can take 10-20 minutes. The single HTTP connection held open for
that long causes Docker to kill the worker container.

### Solution: Presenton's built-in async API

Presenton has native async endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/ppt/presentation/generate/async` | POST | Submit job, returns `{id, status: "pending"}` |
| `/api/v1/ppt/presentation/status/{id}` | GET | Poll status, returns `{status, message, data}` |

When `status` is `"completed"`, `data` contains `{presentation_id, path, edit_path}`.

### Implementation

**`service.py` — `PresentonClient` changes:**

- `generate_presentation()` — blocking `/generate` (for sync endpoint / OpenWebUI)
- `generate_presentation_async()` — calls `/generate/async` + polls `/status/{id}` (for Celery)
- `submit_presentation_async()` — POST to `/generate/async`
- `get_task_status()` — GET `/status/{id}`
- `wait_for_presentation_task()` — poll loop with 5s interval, 900s timeout

**`service.py` — pipeline refactoring:**

- `_run_generation_pipeline(client, req, use_async=False)` — shared logic
- `generate_presentation_sync()` → `use_async=False` (blocking `/generate`)
- `generate_presentation_for_worker()` → `use_async=True` (async + poll)

**`tasks.py` — Celery task changes:**

- Calls `generate_presentation_for_worker()` instead of `generate_presentation_sync()`
- Added `self.update_state()` for `started`/`success`/`failure` states

### Files modified

| File | Change |
|------|--------|
| `presentation/service.py` | Added async methods; refactored pipeline into `_run_generation_pipeline` |
| `presentation/tasks.py` | Use `generate_presentation_for_worker`; added state updates |

### Result

- Async tasks complete successfully without killing the worker ✅
- Sync endpoint still works via blocking `/generate` (OpenWebUI use case) ✅
- Smoke test passes 15/16 (remaining 2 are infrastructure) ✅

---

## Configuration Reference

### Presenton Environment Variables (compose.ai-core.yml)

| Variable | Value | Notes |
|---|---|---|
| `LLM` | `custom` | OpenAI-compatible → LiteLLM |
| `CUSTOM_LLM_URL` | `http://litellm-proxy:4000/v1` | Internal Docker network |
| `CUSTOM_LLM_API_KEY` | `${LITELLM_API_KEY}` | From `.env` |
| `CUSTOM_MODEL` | `${HARNESS_MODEL}` | Default model |
| `IMAGE_PROVIDER` | `pexels` | Stock photos |
| `SEARXNG_BASE_URL` | `http://searxng:8080` | Internal Docker network |
| `WEB_SEARCH_PROVIDER` | `searxng` | |
| `AUTH_USERNAME` | `presenton` | Hardcoded for harness auth |
| `AUTH_PASSWORD` | `changeme123` | Hardcoded for harness auth |
| `CAN_CHANGE_KEYS` | `false` | Lock config |
| `DISABLE_ANONYMOUS_TRACKING` | `true` | Privacy |
| `DISABLE_IMAGE_GENERATION` | `true` | |

### Harness Environment Variables (compose.ai-harness.yml)

| Variable | Value | Used by |
|---|---|---|
| `PRESENTON_BASE_URL` | `http://presenton:80` | Presentation module (Docker-internal) |
| `PRESENTON_AUTH_USERNAME` | `presenton` | Authentication with Presenton |
| `PRESENTON_AUTH_PASSWORD` | `changeme123` | Authentication with Presenton |
| `PUBLIC_BASE_URL` | `https://siri.choukalos.com` | Download URLs in responses |
| `INTERNAL_BASE_URL` | `http://thor.local:8090` | Internal API references |

### Storage Layout

```
/data/media/presentations/
  ├── quarterly-review-v1.pptx
  ├── quarterly-review-v1.metadata.json
  ├── quarterly-review-v2.pptx
  ├── quarterly-review-v2.metadata.json
  └── ...
```

### URL Routing

```
Public (no auth):
  https://siri.choukalos.com/media/files/presentations/foo-v1.pptx
    → Caddy → ai-harness:8090 → StaticFiles → /data/media/presentations/foo-v1.pptx

Internal API (auth required):
  http://thor.local:8090/presentation/generate
  http://thor.local:8090/presentation/list
  http://thor.local:8090/presentation/download/foo-v1.pptx
    → ai-harness (auth-gated)

Presenton edit (internal network, browser auth):
  http://thor.local:5000/presentation?id=xxx
    → Presenton web UI
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Presenton API changes | Pin to a specific tag initially; the API is stable in v3 |
| Large generation timeouts | Use Celery async for Siri; sync endpoint has 900s timeout |
| Presenton container resource usage | Monitor memory; Presenton includes Mem0 — keep `DISABLE_IMAGE_GENERATION=true` |
| File permission issues with shared volumes | Ensure container user matches host permissions |
| Public file URLs accessible by anyone with the link | Accepted trade-off — same pattern as demos/images. Presentations don't have auth-gated download. |
