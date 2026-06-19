# Presentation Module — Implementation Plan

> Integrate [Presenton](https://github.com/presenton/presenton) into the ai-harness for
> AI-generated presentations, exposed to Siri and OpenWebUI.
>
> **Status**: Sessions 1–4 complete. Versioning with parent resolution, metadata
> persistence, and PATCH regeneration endpoint implemented. Presenton infrastructure
> added to compose files.
> **Directory**: `ai-harness/presentation/`
> **Storage**: `/data/media/presentations/` (already exists, currently empty)
> **Network**: Internal home lab only — Presenton is accessible at
> `http://thor.local:5000` but is **NOT** exposed publicly via Caddy or
> Cloudflare. See the "Network Exposure" section for rationale.
>
> **NOTE**: Restart `compose/compose.ai-core.yml` to bring up the Presenton
> container. The harness also needs a rebuild + restart to pick up the new
> `PRESENTON_*` env vars.

---

## Architecture Overview

```
Siri / OpenWebUI
       │
       ▼
  ┌─────────────┐
  │  ai-harness  │  /presentation/* endpoints
  │              │  ┌─────────────────────┐
  │  presentation │  │   Presenton API     │
  │    module     │──│  (separate container)│
  │               │  └─────────────────────┘
  │               │         │
  │               │    /data/media/presentations/
  └───────────────┘
         │
         ├── deep_research (optional research phase)
         ├── family_kb (optional KB lookup)
         └── web_search (optional web grounding)
```

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

Each session below produces concrete files. Final layout:

```
presentation/
  __init__.py          # empty (package marker)
  plan.md              # this file
  schemas.py           # Pydantic request/response models
  service.py           # Presenton API client + outline/research orchestration
  router.py            # FastAPI endpoints
  prompts.py           # LLM prompts for outline generation
  tasks.py             # Celery tasks for async generation (Siri flow)
  README.md            # Module documentation (written in Session 1)
```

---

## Session 0 — Presenton Docker Infrastructure

**Goal**: Get Presenton running as a Docker container on `ai-net` with correct
LLM provider (our LiteLLM), auth, and volume mounts.

### Tasks

- [x] **0a**. Add Presenton service to `compose/compose.ai-core.yml`
  - Image: `ghcr.io/presenton/presenton:latest`
  - Container name: `presenton`
  - Port mapping: `5000:80` (internal port 80, host port 5000 for debugging)
  - Volume: `/home/chuck/data/presenton:/app_data`
  - Network: `ai-net`
  - Environment (key vars from `.env`):
    - `AUTH_USERNAME=presenton` / `AUTH_PASSWORD=changeme123` (hardcoded;
      the harness module uses these for Basic auth, never exposed to users)
    - `CAN_CHANGE_KEYS=false`
    - `LLM=custom` (OpenAI-compatible mode → our LiteLLM)
    - `CUSTOM_LLM_URL=http://litellm-proxy:4000/v1`
    - `CUSTOM_LLM_API_KEY=${LITELLM_API_KEY}`
    - `CUSTOM_MODEL=${HARNESS_MODEL}`
    - `IMAGE_PROVIDER=pexels` (stock photos; see Gemini Flash note below)
    - `SEARXNG_BASE_URL=http://searxng:8080`
    - `WEB_SEARCH_PROVIDER=searxng`
    - `DISABLE_ANONYMOUS_TRACKING=true`
    - `DISABLE_IMAGE_GENERATION=true` (optional — can enable later)

- [x] **0b**. Add `PRESENTON_BASE_URL` and `PRESENTON_AUTH` vars to `.env`:
  - `PRESENTON_BASE_URL=http://presenton:80`
  - `PRESENTON_AUTH_USERNAME=presenton`
  - `PRESENTON_AUTH_PASSWORD=changeme123`

- [x] **0c**. Add Presenton env vars to `compose/compose.ai-harness.yml`
  so the harness container can reach it:
  - `PRESENTON_BASE_URL=http://presenton:80`
  - `PRESENTON_AUTH_USERNAME=presenton`
  - `PRESENTON_AUTH_PASSWORD=changeme123`

- [x] **0d**. Create `/home/chuck/data/presenton/` directory (if it doesn't exist).

  - [ ] **0e**. ~~Add Caddy reverse proxy for `presentations.choukalos.com`~~ — skipped.
    Presenton stays internal only. See the "Network Exposure" section above.

- [x] **0f**. Validate: `docker compose -f compose/compose.ai-core.yml up -d presenton`
  and confirm `http://thor.local:5000` loads the Presenton UI.

### Files changed

- `compose/compose.ai-core.yml` — add presenton service
- `compose/compose.ai-harness.yml` — add presenton env vars to all harness services
- `.env` — add PRESENTON_* variables
- `caddy/Caddyfile` — ~~add `@presentations` host block~~ (skipped — internal only)

---

## Session 1 — Harness Module Skeleton

**Goal**: Wire up the presentation module into ai-harness with schemas, service,
router, and registration in `app.py`.

### Tasks

- [x] **1a**. Create `presentation/schemas.py`:
  - `PresentationRequest` — input model for one-shot generation:
    - `title: str` — presentation title
    - `content: str` — topic / raw content prompt
    - `outline: str | None` — optional pre-built outline markdown
    - `research: bool = False` — whether to do deep research first
    - `kb_search: bool = False` — whether to search family KB first
    - `n_slides: int = 8` — slide count
    - `template: str = "general"` — Presenton template name
    - `tone: str = "default"` — tone (default/casual/professional/funny/educational/sales_pitch)
    - `verbosity: str = "standard"` — (concise/standard/text-heavy)
    - `language: str = "English"`
    - `export_as: str = "pptx"` — (pptx/pdf)
    - `version: int | None = None` — version number for iteration on existing presentation
    - `parent_id: str | None = None` — ID of parent presentation being versioned
    - `instructions: str | None = None` — additional instructions for slide generation
    - `include_table_of_contents: bool = False`
    - `include_title_slide: bool = True`

  - `OutlineRequest` — for collaborative outline generation:
    - `topic: str` — topic description
    - `existing_outline: str | None` — existing outline to refine
    - `instructions: str | None` — specific outline instructions
    - `research: bool = False` — whether to research first
    - `kb_search: bool = False` — whether to search KB first

  - `OutlineResponse` — AI-generated outline:
    - `outline: str` — markdown outline text
    - `title: str` — suggested presentation title
    - `slide_count: int` — estimated slide count
    - `sources: list[dict]` — research sources used (if any)

  - `PresentationResponse` — response after generation:
    - `presentation_id: str` — Presenton internal ID
    - `title: str` — presentation title
    - `version: int` — version number
    - `parent_id: str | None` — parent presentation ID
    - `slide_count: int`
    - `local_path: str` — path under `/data/media/presentations/`
    - `download_url: str` — internal URL for downloading (home lab network)
    - `edit_url: str | None` — Presenton web UI edit URL (internal only, e.g. `http://thor.local:5000/presentation?id=...`)
    - `metadata_path: str` — path to metadata.json

  - `PresentationListResponse` — list of existing presentations
  - `PresentationMetadata` — single presentation metadata record

- [x] **1b**. Create `presentation/service.py`:
  - `PresentonClient` class — HTTP client for Presenton's API:
    - `_login()` — authenticate and get session token
    - `generate_presentation(content, **kwargs)` — call `/api/v1/ppt/presentation/generate`
    - `get_presentation(presentation_id)` — fetch presentation details
    - Copy generated PPTX/PDF from Presenton's `/app_data/` volume to
      `/data/media/presentations/` with proper naming
  - `_save_metadata(metadata)` — write `metadata.json` alongside each presentation
  - `_scan_presentations()` — scan `/data/media/presentations/` for metadata files
  - `_find_presentation_by_title(title)` — find existing presentations by title
    (for versioning)
  - `_generate_filename(title, version)` — deterministic filename:
    `presentations/{slug}-v{version}.pptx`

---

## Network Exposure

Presenton is accessible **only on the internal home lab network** (e.g. `http://thor.local:5000`).
It is **not** proxied through Caddy or exposed via Cloudflare tunnels.

**Why internal only:**

- **API key leakage**: Presenton stores LLM provider API keys (OpenAI, etc.) in its
  config. Anyone with web access could extract them.
- **Single-account auth**: Presenton has one admin login, not multi-user RBAC.
  Exposing it publicly means one set of credentials for all access.
- **Cost exposure**: LLM/image generation calls burn your API quota — unbounded
  public access could lead to unexpected costs.
- **Sensitive content**: Presentations may contain internal documents, client decks,
  or research data that shouldn't be public.
- **The harness is the gateway**: All user-facing access flows through the ai-harness
  API (auth-gated with `HARNESS_API_KEY` or `SIRI_API_KEY`). Presenton is purely a
  backend engine — the harness handles auth, rate-limiting, and orchestration.

Users on the home lab network can still access the Presenton UI directly at
`http://thor.local:5000` for manual editing of generated presentations.

---

## Session 1 — Harness Module Skeleton

**Goal**: Wire up the presentation module into ai-harness with schemas, service,
router, and registration in `app.py`.

### Tasks

- [x] **1a**. Create `presentation/schemas.py`:
  - `PresentationRequest` — input model for one-shot generation:
    - `title: str` — presentation title
    - `content: str` — topic / raw content prompt
    - `outline: str | None` — optional pre-built outline markdown
    - `research: bool = False` — whether to do deep research first
    - `kb_search: bool = False` — whether to search family KB first
    - `n_slides: int = 8` — slide count
    - `template: str = "general"` — Presenton template name
    - `tone: str = "default"` — tone (default/casual/professional/funny/educational/sales_pitch)
    - `verbosity: str = "standard"` — (concise/standard/text-heavy)
    - `language: str = "English"`
    - `export_as: str = "pptx"` — (pptx/pdf)
    - `version: int | None = None` — version number for iteration on existing presentation
    - `parent_id: str | None = None` — ID of parent presentation being versioned
    - `instructions: str | None = None` — additional instructions for slide generation
    - `include_table_of_contents: bool = False`
    - `include_title_slide: bool = True`

  - `OutlineRequest` — for collaborative outline generation:
    - `topic: str` — topic description
    - `existing_outline: str | None` — existing outline to refine
    - `instructions: str | None` — specific outline instructions
    - `research: bool = False` — whether to research first
    - `kb_search: bool = False` — whether to search KB first

  - `OutlineResponse` — AI-generated outline:
    - `outline: str` — markdown outline text
    - `title: str` — suggested presentation title
    - `slide_count: int` — estimated slide count
    - `sources: list[dict]` — research sources used (if any)

  - `PresentationResponse` — response after generation:
    - `presentation_id: str` — Presenton internal ID
    - `title: str` — presentation title
    - `version: int` — version number
    - `parent_id: str | None` — parent presentation ID
    - `slide_count: int`
    - `local_path: str` — path under `/data/media/presentations/`
    - `download_url: str` — internal URL for downloading (home lab network)
    - `edit_url: str | None` — Presenton web UI edit URL (internal only, e.g. `http://thor.local:5000/presentation?id=...`)
    - `metadata_path: str` — path to metadata.json

  - `PresentationListResponse` — list of existing presentations
  - `PresentationMetadata` — single presentation metadata record

- [x] **1b**. Create `presentation/service.py`:
  - `PresentonClient` class — HTTP client for Presenton's API:
    - `_login()` — authenticate and get session token
    - `generate_presentation(content, **kwargs)` — call `/api/v1/ppt/presentation/generate`
    - `get_presentation(presentation_id)` — fetch presentation details
    - Copy generated PPTX/PDF from Presenton's `/app_data/` volume to
      `/data/media/presentations/` with proper naming
  - `_save_metadata(metadata)` — write `metadata.json` alongside each presentation
  - `_scan_presentations()` — scan `/data/media/presentations/` for metadata files
  - `_find_presentation_by_title(title)` — find existing presentations by title
    (for versioning)
  - `_generate_filename(title, version)` — deterministic filename:
    `presentations/{slug}-v{version}.pptx`

- [x] **1c**. Create `presentation/router.py`:
  - `POST /generate` — one-shot presentation generation (synchronous, long timeout)
  - `POST /generate/async` — async generation via Celery task (for Siri)
  - `POST /outline` — collaborative outline generation
  - `GET /list` — list all presentations
  - `GET /{presentation_id}` — get presentation details by ID
  - `DELETE /{presentation_id}` — delete a presentation
  - `GET /download/{filename}` — serve a presentation file
  - All endpoints use `require_harness_auth` (except `/list` can be siri-auth)

- [x] **1d**. Create `presentation/prompts.py`:
  - `OUTLINE_GENERATION_PROMPT` — prompt template for generating outlines
    from a topic + optional research material
  - `TITLE_GENERATION_PROMPT` — prompt for clean presentation titles

- [x] **1e**. Create `presentation/__init__.py` (empty package marker)

- [x] **1f**. Register the router in `app.py`:
  - `from presentation.router import router as presentation_router`
  - `app.include_router(presentation_router, prefix="/presentation", tags=["presentation"])`

- [x] **1g**. Create `presentation/README.md` — module documentation describing
  endpoints, config, and usage patterns.

### Files created

- `presentation/__init__.py`
- `presentation/schemas.py`
- `presentation/service.py`
- `presentation/router.py`
- `presentation/prompts.py`
- `presentation/README.md`

### Files modified

- `app.py` — register the new router

---

## Session 2 — Outline Generation + Research Integration

**Goal**: Implement the AI-powered outline generation with optional deep research
and KB search. This is the "brain" of the module.

### Tasks

- [x] **2a**. Implement `_generate_outline()` in `service.py`:
  - Takes a `OutlineRequest` and uses LiteLLM chat completion to produce
    a structured markdown outline.
  - The outline format: title + numbered slide sections with bullet points
    per slide (matching Presenton's expected content format).
  - Uses `OUTLINE_GENERATION_PROMPT` from `prompts.py`.

- [x] **2b**. Implement `_do_research()` in `service.py`:
  - If `research=True`, call the deep_research endpoint internally
    (same pattern as `siri/service.py` `_handle_deep_research`).
  - Returns research text + sources to prepend to the outline prompt.
  - Timeout: 180s.

- [x] **2c**. Implement `_search_kb()` in `service.py`:
  - If `kb_search=True`, query the family knowledge base for relevant
    content on the topic.
  - Returns KB excerpts to prepend to the outline prompt.
  - Uses existing `family_kb` search infrastructure.

- [x] **2d**. Implement `generate_presentation()` in `service.py`:
  - Orchestrates: optional research → optional KB → outline generation →
    Presenton API call → file copy → metadata save.
  - Returns `PresentationResponse`.

- [x] **2e**. Implement `generate_outline()` in `service.py`:
  - Standalone outline generation (for the collaborative flow).
  - Returns `OutlineResponse`.

- [x] **2f**. Implement `list_presentations()` and `get_presentation()` in `service.py`:
  - Scan `/data/media/presentations/` for `metadata.json` files.
  - Return sorted by creation date (newest first).

- [x] **2g**. Wire up the router endpoints to call the service functions:
  - `POST /outline` → `generate_outline()`
  - `POST /generate` → `generate_presentation()` (sync, timeout=300s)

### Files modified

- `presentation/service.py` — add generation logic
- `presentation/router.py` — wire up endpoints

---

## Session 3 — Celery Tasks + Siri Integration

**Goal**: Add async presentation generation (for Siri's fire-and-forget flow)
and wire up Siri intent detection for presentation commands.

### Tasks

- [x] **3a**. Create `presentation/tasks.py`:
  - `@celery.task` `generate_presentation_task(title, content, **kwargs)` —
    the Celery worker version of `generate_presentation()`.
  - Runs in background; writes result to a task-completion file in
    `/data/media/presentations/` that the list endpoint can pick up.
  - Same logic as Session 2's `generate_presentation()` but sync (runs
    in Celery worker, not async).

- [x] **3b**. Add `POST /generate/async` to `presentation/router.py`:
  - Fire-and-forget endpoint that dispatches the Celery task.
  - Returns immediately with a `task_id` for status checking.
  - Uses `require_harness_auth`.

- [x] **3c**. Add `GET /tasks/{task_id}` to check async task status.

- [x] **3d**. Add presentation intents to `siri/service.py`:
  - In `_detect_intent()`, add detection for:
    - `"create presentation"` / `"make a presentation"` / `"build a presentation"`
      → intent `create_presentation`
    - `"list presentations"` / `"my presentations"` / `"show presentations"`
      → intent `list_presentations`
    - `"presentation about"` / `"find presentation"`
      → intent `find_presentation`
  - Add `_handle_create_presentation()` — same fire-and-forget pattern as
    `_handle_create_demo_workflow()`:
    - Extract title from voice text
    - Call `POST /presentation/generate/async` via httpx
    - Return immediate Siri response: "I've started creating your presentation..."
  - Add `_handle_list_presentations()` — scan presentations dir, return
    list with internal URLs (home lab network only).
  - Add `_handle_find_presentation()` — search by title/topic.

- [x] **3e**. Register tasks in `app.py` or via existing task registration pattern:
  - `from presentation.tasks import register as register_presentation_tasks`
  - Call during startup.

- [x] **3f**. Ensure the Celery workers pick up the new tasks (they use the
  same image, so rebuilding + restarting workers handles this).

### Files created

- `presentation/tasks.py`

### Files modified

- `presentation/router.py` — add async endpoint
- `siri/service.py` — add presentation intents
- `app.py` — register presentation tasks

---

## Session 4 — Versioning + Persistence

**Goal**: Implement versioning for iterative presentations and finalize
metadata persistence.

### Tasks

- [x] **4a**. Implement versioning logic in `service.py`:
  - `_find_latest_version(title)` — find the highest version number
    for a given presentation title (from metadata files).
  - When `parent_id` is provided, read parent's title and auto-increment.
  - When only `title` is provided (no `parent_id`), check for existing
    versions and auto-increment.
  - First version = 1, subsequent = N+1.

- [x] **4b**. Implement metadata persistence:
  - Each presentation gets a `metadata.json` in `/data/media/presentations/`:
    ```json
    {
      "presentation_id": "uuid-from-presenton",
      "title": "Quarterly Review",
      "version": 2,
      "parent_id": "abc-123",
      "slide_count": 10,
      "filename": "quarterly-review-v2.pptx",
      "local_path": "/data/media/presentations/quarterly-review-v2.pptx",
      "download_url": "http://thor.local:8090/presentation/download/...",
      "created_at": "2025-01-15T10:30:00-06:00",
      "sources": [...],
      "outline": "...original outline used...",
      "tags": [...]
    }
    ```

- [x] **4c**. Add `PATCH /{presentation_id}` to `router.py`:
  - Regenerate a presentation with modified parameters (e.g., change tone,
    add slides, change template).
  - Creates a new version automatically.

- [ ] **4d**. ~~Add Caddy config for `presentations.choukalos.com`~~ — skipped.
  Presenton stays internal only (see "Network Exposure" section above).
  The harness `/presentation/*` endpoints serve download URLs using internal
  hostnames (`thor.local`).

- [ ] **4e**. ~~Cloudflare tunnel~~ — not needed. No public domain for Presenton.

### Files modified

- `presentation/service.py` — versioning + metadata
- `presentation/router.py` — PATCH endpoint
- ~~`caddy/Caddyfile`~~ — no changes (internal only)

---

## Session 5 — OpenWebUI Integration + Testing

**Goal**: Expose the presentation tool to OpenWebUI and validate the end-to-end flow.

### Tasks

- [ ] **5a**. Register the presentation API as an OpenWebUI tool/toolkit:
  - OpenWebUI already connects to the harness via `HARNESS_URL` and
    `HARNESS_API_KEY`.
  - The tool definition can be:
    - Name: `create_presentation`
    - Description: "Generate a PowerPoint presentation from a topic or outline"
    - URL: `http://ai-harness:8090/presentation/generate`
    - Method: POST
    - Parameters: `title`, `content`, `n_slides`, `template`, `tone`, etc.
  - Alternatively, add a tool definition in the harness itself that
    OpenWebUI can discover via the harness's OpenAPI spec.

- [ ] **5b**. Validate OpenAPI spec includes the new `/presentation/*` endpoints:
  - The router is already tagged with `tags=["presentation"]` so it
    shows up in the spec automatically.

- [ ] **5c**. Smoke test the full flow:
  - `curl` to `POST /presentation/outline` with a test topic
  - `curl` to `POST /presentation/generate` with the outline
  - Verify PPTX appears in `/data/media/presentations/`
  - Verify `metadata.json` is written
  - `curl` to `GET /presentation/list` to confirm listing works

- [ ] **5d**. Test Siri flow:
  - `curl` to `POST /siri/chat` with `"create presentation about AI in healthcare"`
  - Verify background task runs and file appears

- [ ] **5e**. Test versioning:
  - Generate same title twice, verify v1 and v2 are created
  - Verify `parent_id` links correctly

### Files modified

- Potentially `compose/compose.ai-core.yml` — if OpenWebUI needs additional
  env vars for the presentation tool

---

## Configuration Reference

### Presenton Environment Variables (compose.ai-core.yml)

| Variable | Value | Notes |
|---|---|---|
| `LLM` | `custom` | OpenAI-compatible → LiteLLM |
| `CUSTOM_LLM_URL` | `http://litellm-proxy:4000/v1` | Internal Docker network |
| `CUSTOM_LLM_API_KEY` | `${LITELLM_API_KEY}` | From .env |
| `CUSTOM_MODEL` | `${HARNESS_MODEL}` | Default model |
| `IMAGE_PROVIDER` | `pexels` | Stock photos; see Gemini Flash alternative below |
| `PEXELS_API_KEY` | (optional) | For Pexels stock photo provider |

**Image generation alternatives:**

- **Pexels** (default): Free stock photos. Fast, free, but generic. Requires a
  [Pexels API key](https://www.pexels.com/api/) if you want higher rate limits.
- **Gemini Flash** (better quality AI images): Swap in if you want AI-generated
  images instead of stock photos. Requires:
  ```env
  IMAGE_PROVIDER=gemini_flash
  GOOGLE_API_KEY=your-google-api-key
  ```
  Uses the same Google API key as our LiteLLM `google` provider. Image quality
  is better than Pexels for thematic/custom slide visuals.
- **Disable**: Set `DISABLE_IMAGE_GENERATION=true` if you don't want images at all
  (clean text/layout-only slides).
| `SEARXNG_BASE_URL` | `http://searxng:8080` | Internal Docker network |
| `WEB_SEARCH_PROVIDER` | `searxng` | Use our SearXNG |
| `AUTH_USERNAME` | `presenton` | Hardcoded for harness auth |
| `AUTH_PASSWORD` | `changeme123` | Hardcoded for harness auth |
| `CAN_CHANGE_KEYS` | `false` | Lock config |
| `DISABLE_ANONYMOUS_TRACKING` | `true` | Privacy |

### Harness Environment Variables (compose.ai-harness.yml)

| Variable | Value |
|---|---|
| `PRESENTON_BASE_URL` | `http://presenton:80` |
| `PRESENTON_AUTH_USERNAME` | `presenton` |
| `PRESENTON_AUTH_PASSWORD` | `changeme123` |

### Storage Layout

```
/data/media/presentations/
  ├── quarterly-review-v1.pptx
  ├── quarterly-review-v1.metadata.json
  ├── quarterly-review-v2.pptx
  ├── quarterly-review-v2.metadata.json
  ├── ai-in-healthcare-v1.pptx
  ├── ai-in-healthcare-v1.metadata.json
  └── ...
```

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Presenton API changes | Pin to a specific tag initially; the API is stable in v3 |
| Large generation timeouts | Use Celery async for Siri; sync endpoint has 300s timeout |
| Presenton container resource usage | Monitor memory; Presenton includes Mem0 + Ollama by default — disable unused features |
| File permission issues with shared volumes | Ensure container user matches host permissions |
| Download URLs only work on internal network | Document this limitation; users on the home lab network access via `thor.local` |

---

## Session Order

Run sessions sequentially: **0 → 1 → 2 → 3 → 4 → 5**. Each session is
self-contained — you can stop after any session and have a working subset:

- After **Session 0**: Presenton is running and accessible
- After **Session 1**: Harness module is registered, basic API works
- After **Session 2**: Full one-shot generation with research/KB works
- After **Session 3**: Siri can create presentations via voice
- After **Session 4**: Versioning works, presentations accessible on internal network
- After **Session 5**: OpenWebUI integration + everything validated
