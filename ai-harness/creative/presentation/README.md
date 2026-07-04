# Presentation Module

> AI-powered presentation generation using [Presenton](https://github.com/presenton/presenton).
> Integrated into ai-harness for use by Siri, OpenWebUI, and direct API.

## Overview

This module wraps the Presenton API to generate PowerPoint/PDF presentations
from topics, outlines, or research content. Generated files are saved to
`/data/media/presentations/` with companion `metadata.json` files for tracking
and versioning.

## Capabilities

- **Sync & Async Generation** — One-shot blocking generation or Celery-backed
  fire-and-forget with task polling
- **Outline Generation** — AI-powered outline creation from topics, with optional
  deep research (via crawl4ai) and family knowledge base search (via Qdrant)
- **Versioning** — Auto-incremented versions with parent-child linkage via
  `parent_id`; regenerate with any subset of params changed
- **Async Updates** — Update existing presentations via Celery background tasks
  (Siri can't wait 3-5 minutes for a response)
- **Siri Voice Flow** — Intent detection for create, update, list, and find
  presentations; LLM-based parsing of natural language update instructions
- **OpenWebUI Integration** — Full tool suite for create, async create, update,
  regenerate, outline, list, find, download, and task status checking
- **Public Downloads** — Files exposed via public URL (`siri.choukalos.com`)
  without authentication; internal download via authenticated API

## Architecture

```
User (Siri / OpenWebUI / API)
    │
    ▼
ai-harness (FastAPI, port 8090)
    │
    ├── presentation/
    │   ├── router.py        — FastAPI endpoints
    │   ├── service.py       — PresentonClient + generation pipeline
    │   ├── tasks.py         — Celery tasks (generate + update)
    │   ├── schemas.py       — Pydantic models
    │   └── prompts.py       — LLM prompts (outline + update parsing)
    │
    ├── siri/service.py      — Intent detection + update handler
    │
    └── channels/openwebui/creative_tools.py  — OpenWebUI tools
           │
           ▼
       Celery Workers (ai-harness-worker-1/2)
           │
           ▼
       Presenton (LLM → slides → PPTX/PDF)
           │
           ▼
       /data/media/presentations/  (local storage + metadata.json)
```

## Endpoints

```
POST /presentation/generate          — One-shot sync generation
POST /presentation/generate/async    — Async generation (Celery, fire-and-forget)
POST /presentation/outline           — Collaborative outline generation
PATCH /presentation/{id}             — Regenerate with changes (sync, new version)
POST /presentation/{id}/update/async — Regenerate with changes (async, Celery)
GET  /presentation/list              — List all presentations
GET  /presentation/{id}              — Get presentation details by Presenton ID
GET  /presentation/search?title=     — Find presentations by title (fuzzy match)
GET  /presentation/tasks/{task_id}   — Check async task status
GET  /presentation/download/{fn}     — Download a presentation file (auth required)
DELETE /presentation/{id}            — Delete a presentation + metadata
```

All endpoints require `HARNESS_API_KEY` or `SIRI_API_KEY` via
`Authorization: Bearer <key>` or `X-Api-Key: <key>` header.

## Usage Examples

### Generate a presentation (sync)

```bash
curl -X POST http://thor.local:8090/presentation/generate \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Q4 Review",
    "content": "Quarterly business review covering revenue, growth, and outlook",
    "n_slides": 10,
    "template": "general",
    "tone": "professional",
    "export_as": "pptx"
  }'
```

### With a pre-built outline (skips AI outline generation)

```bash
curl -X POST http://thor.local:8090/presentation/generate \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "AI Strategy",
    "outline": "# AI Strategy\n\n## 1. Current State\n- Where we are\n\n## 2. Roadmap\n- Q1/Q2 goals",
    "n_slides": 8,
    "tone": "professional"
  }'
```

### With deep research + KB search

```bash
curl -X POST http://thor.local:8090/presentation/generate \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Market Analysis",
    "content": "Analysis of the current AI market trends",
    "research": true,
    "kb_search": true,
    "n_slides": 10
  }'
```

### Async generation (fire-and-forget)

```bash
# Step 1: Dispatch
curl -X POST http://thor.local:8090/presentation/generate/async \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Q4 Review",
    "content": "Quarterly business review",
    "n_slides": 10
  }'
# → {"task_id": "abc-123", "title": "Q4 Review", "status": "submitted"}

# Step 2: Poll status
curl http://thor.local:8090/presentation/tasks/abc-123 \
  -H "X-API-Key: $HARNESS_API_KEY"
# → {"status": "completed", "result": {"presentation_id": "...", "download_url": "..."}}
```

### Update an existing presentation (async)

```bash
# Update: change tone to casual, increase to 5 slides
curl -X POST http://thor.local:8090/presentation/{id}/update/async \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tone": "casual", "n_slides": 5}'
# → {"task_id": "def-456", "title": "Q4 Review", "status": "submitted"}
```

This creates a new version (v2, v3, ...) linked via `parent_id`.
Only the fields you send are changed; everything else is inherited from the parent.

### Sync regeneration

```bash
curl -X PATCH http://thor.local:8090/presentation/{presentation_id} \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"n_slides": 12, "tone": "casual", "template": "creative"}'
```

### Generate an outline (standalone)

```bash
curl -X POST http://thor.local:8090/presentation/outline \
  -H "X-API-Key: $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Introduction to homelab infrastructure",
    "instructions": "Keep it to 5-6 slides, focus on getting started"
  }'
```

### List and search

```bash
# List all
curl http://thor.local:8090/presentation/list \
  -H "X-API-Key: $HARNESS_API_KEY"

# Search by title
curl "http://thor.local:8090/presentation/search?title=Q4" \
  -H "X-API-Key: $HARNESS_API_KEY"

# Download (auth required)
curl -O http://thor.local:8090/presentation/download/q4-review-v1.pptx \
  -H "X-API-Key: $HARNESS_API_KEY"
```

## Siri Voice Integration

Siri intents are auto-detected from natural language:

| User Says | Intent | Flow |
|---|---|---|
| "Create a presentation about X" | `create_presentation` | Dispatch async task |
| "Update the X presentation to be more casual" | `update_presentation` | Search → LLM parse instructions → dispatch async update |
| "List my presentations" | `list_presentations` | Return formatted list |
| "Find presentation about X" | `find_presentation` | Search by title, return matches |

The update flow uses an LLM (`UPDATE_INSTRUCTION_PROMPT`) to parse natural
language instructions into structured `PresentationUpdateRequest` fields:
- "more casual" → `tone: "casual"`
- "12 slides" → `n_slides: 12`
- "dark template" → `template: "dark"`
- "less text per slide" → `verbosity: "concise"`

## OpenWebUI Tools

Available tools for OpenWebUI integration:

| Tool | Description |
|---|---|
| `create_presentation()` | Sync generation, waits for completion |
| `create_presentation_async()` | Async generation, returns task_id |
| `update_presentation_async()` | Async update, returns task_id |
| `regenerate_presentation()` | Sync regeneration (PATCH) |
| `check_task_status()` | Poll Celery task status |
| `generate_outline()` | Standalone outline generation |
| `list_presentations()` | List all presentations |
| `find_presentations()` | Search by title/topic |

## Schemas

### PresentationRequest

| Field | Type | Default | Description |
|---|---|---|---|
| `title` | `str` | *(required)* | Presentation title |
| `content` | `str` | *(required)* | Topic description or content prompt |
| `outline` | `str \| None` | `None` | Pre-built markdown outline (skips AI generation) |
| `research` | `bool` | `False` | Deep research via crawl4ai |
| `kb_search` | `bool` | `False` | Search family knowledge base |
| `n_slides` | `int` | `8` | Target slides (3–50) |
| `template` | `str` | `"general"` | Presenton template name |
| `tone` | `enum` | `"default"` | `default`, `casual`, `professional`, `funny`, `educational`, `sales_pitch` |
| `verbosity` | `enum` | `"standard"` | `concise`, `standard`, `text-heavy` |
| `language` | `str` | `"English"` | Output language |
| `export_as` | `enum` | `"pptx"` | `pptx` or `pdf` |
| `version` | `int \| None` | `None` | Explicit version (auto-incremented if omitted) |
| `parent_id` | `str \| None` | `None` | Presenton ID of parent presentation |
| `instructions` | `str \| None` | `None` | Additional instructions for the AI |
| `include_table_of_contents` | `bool` | `False` | Include TOC slide |
| `include_title_slide` | `bool` | `True` | Include title slide |

### PresentationUpdateRequest

Same fields as `PresentationRequest`, but **all optional**. Only the provided
fields override the parent's values.

## Celery Tasks

| Task | Name | Description |
|---|---|---|
| `presentation.generate_presentation` | `generate_presentation_task` | Full pipeline: research → outline → Presenton → save |
| `presentation.update_presentation` | `update_presentation_task` | Regenerate with updated params, new version with parent_id |

Both tasks use Presenton's async API + polling (never hold an HTTP connection
open for 10-20 minutes). Worker logs include `task kwargs` for debugging
parameter passthrough.

## Storage

```
/data/media/presentations/
  ├── q4-review-v1.pptx
  ├── q4-review-v1.metadata.json
  ├── q4-review-v2.pptx          ← update created v2
  ├── q4-review-v2.metadata.json
  └── ...
```

Filenames: `{slug}-v{version}.{ext}`
Metadata: `{slug}-v{version}.metadata.json` with `presentation_id`, `title`,
`version`, `parent_id`, `download_url`, `internal_download_url`, `edit_url`,
`outline`, `sources`, etc.

## URL Formats

| URL Type | Format | Auth Required? |
|---|---|---|
| `download_url` | `https://siri.choukalos.com/media/files/presentations/{filename}` | No (public StaticFiles) |
| `internal_download_url` | `http://thor.local:8090/presentation/download/{filename}` | Yes (`X-API-Key`) |
| `edit_url` | `http://presenton:80/presentation?id={id}` | Yes (internal, Basic auth) |

Old metadata files with legacy internal `download_url` format are auto-migrated
on read via `PresentationMetadata._fill_urls()`.

## Configuration

| Variable | Value | Description |
|---|---|---|
| `PRESENTON_BASE_URL` | `http://presenton:80` | Presenton container URL |
| `PRESENTON_AUTH_USERNAME` | `presenton` | Presenton Basic auth username |
| `PRESENTON_AUTH_PASSWORD` | `${PRESENTON_AUTH_PASSWORD}` | Presenton Basic auth password |
| `INTERNAL_BASE_URL` | `http://thor.local:8090` | Internal API base URL |
| `PUBLIC_BASE_URL` | `https://siri.choukalos.com` | Public download base URL |

## Testing

```bash
cd /home/chuck/homelab/ai-harness
bash tests/test_presentation.sh
```

Runs 23 tests covering: health, list, sync generation, async generation + polling,
outline, search, download, public URL validation, metadata, versioning, update flow,
and Siri intent detection.

## See also

- [Presenton GitHub](https://github.com/presenton/presenton) — Upstream project
- `tests/test_presentation.sh` — End-to-end smoke tests
- `channels/openwebui/creative_tools.py` — OpenWebUI tool definitions
- `siri/service.py` — Siri intent detection and handlers
