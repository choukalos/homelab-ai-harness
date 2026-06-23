# AI Harness Open WebUI Tools

## Install

In Open WebUI:

- Workspace
- Tools
- Add Tool
- Paste the `.py` file below
- Save

### Modular Tool Files (Recommended)

Each file independently defines a `class Tools` inheriting from `HarnessBase`
and can be installed standalone in Open WebUI. Pick the ones you need:

| File | Description |
|---|---|
| `research_tools.py` | Web search, research briefs, deep research |
| `knowledge_tools.py` | Family KB search, ask, ingest, raw ingestion |
| `creative_tools.py` | Document creation + presentations (create, outline, list, search, async) |
| `media_tools.py` | Image generation, image editing, video clip generation |
| `apps_tools.py` | PM demos, workflow demos, demo listing/search |
| `filetools_tools.py` | File read/write (extensible, stub for now) |
| `scheduler_tools.py` | Schedule management (extensible, stub for now) |



## Architecture

Each tool file inherits from `HarnessBase` (defined in `harness_base.py`),
which provides:

- `Valves` class — configurable `harness_url` and `harness_api_key`
- `_headers()` — builds auth headers from valves
- `_post()` — POST helper with JSON body
- `_get_with_params()` — GET helper with query params
- `_absolute_url()` — resolves relative URLs to full URLs

## Environment Variables

Optional environment variables in Open WebUI:

```env
HARNESS_URL=http://ai-harness:8090
HARNESS_API_KEY=your_api_key
```

## Research Tools (`research_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `web_search(query, max_results)` | `POST /web/search` | Raw search results with source links |
| `summarize_web_search(query, max_results)` | `POST /web/search` | Crawled + summarized answer with citations |
| `research_brief_web_search(topic, ...)` | `POST /web/research` | Multi-query research brief |
| `deep_research(query)` | `POST /workflows/deep-research/run` | Deep Agents framework investigation |

## Knowledge Tools (`knowledge_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `family_kb_search(query, category, limit)` | `POST /kb/search` | Search family KB for matching chunks |
| `family_kb_ask(question, category, limit)` | `POST /kb/ask` | Ask a question against the KB |
| `family_kb_ingest()` | `POST /kb/ingest` | Re-index markdown KB into Qdrant |
| `family_kb_ingest_raw()` | `POST /kb/ingest/raw` | Convert raw files to markdown |

## Creative Tools (`creative_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `create_document(title, template, zones, ...)` | `POST /layout/build` | Formatted documents with images, tables, PDF export |
| `create_presentation(title, content, ...)` | `POST /presentation/generate` | Full pipeline: research → outline → Presenton → save |
| `create_presentation_async(...)` | `POST /presentation/generate/async` | Fire-and-forget via Celery |
| `check_task_status(task_id)` | `GET /presentation/tasks/{id}` | Poll async task status |
| `generate_outline(topic, ...)` | `POST /presentation/outline` | Brainstorm an outline before building |
| `list_presentations(limit)` | `GET /presentation/list` | List all presentations |
| `regenerate_presentation(id, ...)` | `PATCH /presentation/{id}` | New version with modified params |
| `update_presentation_async(id, ...)` | `POST /presentation/{id}/update/async` | Async update |
| `find_presentations(query)` | `GET /presentation/search` | Search presentations by title |

## Media Tools (`media_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `generate_image(prompt, ...)` | `POST /media/image` | Text-to-image via ComfyUI |
| `edit_image(image_url, prompt, ...)` | `POST /media/image/edit` or `/edit/url` | Image-to-image / img2img |
| `generate_clip(prompt, ...)` | `POST /media/clip` | Text-to-video clip via ComfyUI |

## App Tools (`apps_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `create_pm_demo(title, prompt, ...)` | `POST /pm/demo` | Simple one-click HTML demo |
| `create_demo(title, prompt, model)` | `POST /demos/run` | Full 8-phase research-backed demo pipeline |
| `list_demos(tags, limit)` | `GET /demos/` | List all demos |
| `find_demo(query, limit)` | `GET /demos/search` | Search demos by title, description, or tags |

## Use during a chat

Enable whichever tool files you need, then prompt like:

- `Use summarize_web_search to find current best practices for FastAPI health checks.`
- `Use family_kb_ask to answer from saved documents about our house.`
- `Use generate_image to create a cinematic photo of a silver 1980s sports car at sunset.`
- `Use create_demo to build a product demo for a mobile calculator app.`
- `Use create_presentation to build a slide deck about a topic.`
- `Use deep_research to investigate local-first AI knowledge base architecture.`
