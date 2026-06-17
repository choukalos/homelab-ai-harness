# AI Harness Open WebUI Tools

## Install

In Open WebUI:

- Workspace
- Tools
- Add Tool
- Paste `harness_tools.py`
- Save

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


