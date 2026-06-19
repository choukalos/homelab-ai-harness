# AI Harness Open WebUI Tools

## Install

In Open WebUI:

- Workspace
- Tools
- Add Tool
- Paste the `.py` file below
- Save

Two tool files are available:

| File | Description |
|---|---|
| `harness_tools.py` | Full suite: web search, KB, media, demos, documents, deep research |
| `presentation_tools.py` | Presentations only: create, outline, list, search, async + status |

Use `harness_tools.py` for everything, or `presentation_tools.py` if you only want presentation tools.

## Environment Variables

Optional environment variables:

```env
HARNESS_URL=http://ai-harness:8090
HARNESS_API_KEY=your_api_key
```

## Demo Tools

Both **workflow demos** (research-backed, 8-phase pipeline) and **simple demos**
(one-click HTML) are stored in a unified `demos/` directory and discoverable
through the same listing and search endpoints.

| Method | Endpoint | Description |
|---|---|---|
| `create_demo(title, prompt, model)` | `POST /demos/run` | Full 8-phase pipeline with research, design, build, validation |
| `list_demos(tags, limit)` | `GET /demos/` | List all demos (workflow + simple) with metadata |
| `find_demo(query, limit)` | `GET /demos/search` | Search demos by title, description, or tags |

Simple one-click demos created via Siri's `"html demo"` / `"prototype"` intent
are tagged `simple` for filtering.

## Presentation Tools

| Method | Endpoint | Description |
|---|---|---|
| `create_presentation(title, content, ...)` | `POST /presentation/generate` | Full pipeline: research → outline → Presenton → save |
| `create_presentation_async(title, content, ...)` | `POST /presentation/generate/async` | Fire-and-forget via Celery, returns task_id |
| `check_task_status(task_id)` | `GET /presentation/tasks/{task_id}` | Poll async task status |
| `generate_outline(topic, ...)` | `POST /presentation/outline` | Brainstorm an outline before building |
| `list_presentations(limit)` | `GET /presentation/list` | List all presentations |
| `find_presentations(query)` | `GET /presentation/search?title=` | Search presentations by title |
| `regenerate_presentation(presentation_id, ...)` | `PATCH /presentation/{id}` | Create a new version with modified params |

## Use during a chat
- Enable the tool
- Prompts like:
-- Use summarize_web_search to find current best practices for FastAPI health checks.
-- Use research_brief_web_search to research local-first AI knowledge base architecture for a homelab.
-- Use generate_image to create a cinematic photo of a silver 1980s sports car at sunset.
-- Use edit_image to turn /tmp/car.png into a cinematic rainy night scene.
-- Use create_demo to build a product demo for a mobile calculator app.
-- Use list_demos to see all available demos.
-- Use find_demo to search for demos about tic-tac-toe.
-- Use create_presentation to build a slide deck about a topic.
-- Use create_presentation_async to start a background generation job.
-- Use check_task_status to poll for completion of async jobs.
-- Use generate_outline to plan a presentation before building it.
-- Use list_presentations to see all available presentations.
-- Use find_presentations to search for presentations about a topic.
-- Use regenerate_presentation to create a new version with different params.


