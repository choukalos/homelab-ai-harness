# AI Harness — Open WebUI Channel

Each `.py` file here is a **standalone Open WebUI tool extension** that calls
back into the AI Harness REST API. Every file is self-contained: the shared
`HarnessBase` class (Valves, HTTP helpers, auth headers) is inlined at the top
of each file, so no cross-file imports are needed.

---

## How to install a tool in Open WebUI

1. **Open WebUI** → **Workspace** → **Tools** → **Add Tool**
2. **Paste** the *entire contents* of one `.py` file from this directory
3. **Save**
4. Go to any chat, click the **Tools** icon, and **enable** the tool for that
   model or for all models

You can install as many (or as few) tool files as you want — each is independent.

### Available tool files

| File | What it adds |
|---|---|
| `research_tools.py` | Web search, research briefs, deep research |
| `knowledge_tools.py` | Family KB search, ask, ingest, raw ingestion |
| `creative_tools.py` | Document creation + presentations (create, outline, list, search, async) |
| `media_tools.py` | Image generation, image editing, video clip generation |
| `apps_tools.py` | PM demos, workflow demos, demo listing/search |
| `filetools_tools.py` | File read/write *(stub — ready for methods)* |
| `scheduler_tools.py` | Schedule management *(stub — ready for methods)* |

---

## Architecture — how it works (for both humans and AI agents)

### The HarnessBase pattern

Every tool file follows this structure:

```python
"""
title: <human-readable name>
author: <author>
version: <version>
description: <what this tool group does>
"""

import os
import requests
from pydantic import BaseModel, Field


# ── Inlined HarnessBase ──────────────────────────────────────────
# Copied verbatim into every tool file so each is self-contained.
# Provides: Valves, __init__, _headers, _absolute_url, _post, _get_with_params
# ──────────────────────────────────────────────────────────────────
class HarnessBase:
    class Valves(BaseModel):
        harness_url: str = Field(
            default=os.getenv("HARNESS_URL", "http://ai-harness:8090"),
            description="Internal API URL for the AI Harness (Docker DNS)",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
        )
        harness_display_url: str = Field(
            default=os.getenv("HARNESS_DISPLAY_URL", "http://192.168.4.54:8090"),
            description="Browser-accessible URL for media files (LAN IP)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _headers(self, content_type: bool = True) -> dict: ...
    def _absolute_url(self, url: str) -> str: ...
    def _post(self, path: str, payload: dict, timeout: int = 180) -> dict: ...
    def _get_with_params(self, path: str, params: dict) -> dict: ...


# ── Tool implementations ─────────────────────────────────────────
class Tools(HarnessBase):
    def my_tool_method(self, arg1: str, arg2: int = 5) -> str:
        """
        Docstring here is the tool description the LLM sees.
        Make it clear when the user (or model) should call this tool.
        """
        data = self._post("/some/endpoint", {"arg1": arg1, "arg2": arg2})
        return f"Result: {data}"
```

### Key rules for adding new tooling

1. **HarnessBase is inlined**, never imported. Copy the full `HarnessBase` class
   into every new tool file (or ask the AI agent to generate it).

2. **The class must be named `Tools`** — that's what Open WebUI looks for.

3. **The module-level docstring** MUST contain `title:`, `author:`, `version:`,
   and `description:` — Open WebUI parses these to display the tool in the UI.

4. **Each method on `Tools` becomes an invocable tool**. The method's docstring
   is what the LLM reads to decide when to call it. Make docstrings descriptive
   — include what the tool does and *when* to use it.

5. **Return strings, not dicts**. The return value is shown to the user in chat.
   Use markdown formatting (`[Link](url)`, `![Image](url)`, bold, etc.) for
   rich output.

6. **Use the helpers**: `self._post()`, `self._get_with_params()`,
   `self._absolute_url()`, `self._headers()` — don't write raw requests unless
   needed (e.g. multipart file uploads).

7. **Adding a new tool file**: create it in this directory, paste in the
   `HarnessBase` block, add a `class Tools(HarnessBase)` with your methods,
   then install it in Open WebUI as described above.

8. **Adding methods to an existing tool file**: just add new methods to the
   `class Tools` and reinstall the file in Open WebUI (paste the updated
   contents over the existing tool).

9. **`harness_base.py`** in this directory is the source-of-truth reference
   for the `HarnessBase` class. Copy from here when creating new tool files or
   updating the inlined copy. Keep it in sync.

---

## Configuration

### Valves (settable per-tool in the Open WebUI UI)

| Valve | Default | Description |
|---|---|---|
| `harness_url` | `http://ai-harness:8090` | Internal API URL of the AI Harness (Docker DNS) |
| `harness_api_key` | `""` | API key (also sent as `Authorization: Bearer` header) |
| `harness_display_url` | `http://192.168.4.54:8090` | Browser-accessible URL for media files (LAN IP) |

### Environment variables (optional, set in the Open WebUI container)

```env
HARNESS_URL=http://ai-harness:8090
HARNESS_DISPLAY_URL=http://192.168.4.54:8090   # your LAN IP for browser-accessible URLs
HARNESS_API_KEY=your_api_key
```

---

## Tool reference

### Research Tools (`research_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `web_search(query, max_results)` | `POST /web/search` | Raw search results with source links |
| `summarize_web_search(query, max_results)` | `POST /web/search` | Crawled + summarized answer with citations |
| `research_brief_web_search(topic, ...)` | `POST /web/research` | Multi-query research brief |
| `deep_research(query)` | `POST /workflows/deep-research/run` | Deep Agents framework investigation |

### Knowledge Tools (`knowledge_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `family_kb_search(query, category, limit)` | `POST /kb/search` | Search family KB for matching chunks |
| `family_kb_ask(question, category, limit)` | `POST /kb/ask` | Ask a question against the KB |
| `family_kb_ingest()` | `POST /kb/ingest` | Re-index markdown KB into Qdrant |
| `family_kb_ingest_raw()` | `POST /kb/ingest/raw` | Convert raw files to markdown |

### Creative Tools (`creative_tools.py`)

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

### Media Tools (`media_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `generate_image(prompt, ...)` | `POST /media/image` | Text-to-image via ComfyUI |
| `edit_image(image_url, prompt, ...)` | `POST /media/image/edit` or `/edit/url` | Image-to-image / img2img |
| `generate_clip(prompt, ...)` | `POST /media/clip` | Text-to-video clip via ComfyUI |

### App Tools (`apps_tools.py`)

| Method | Endpoint | Description |
|---|---|---|
| `create_quick_demo(title, prompt, ...)` | `POST /pm/demo` | Fast, simple one-shot HTML demo (~10s) |
| `create_workflow_demo(title, prompt, model)` | `POST /demos/run` | Full research-backed demo pipeline (2-5 min) |
| `list_demos(tags, limit)` | `GET /demos/` | List all demos |
| `find_demo(query, limit)` | `GET /demos/search` | Search demos by title, description, or tags |

---

## Using tools in chat

Once tools are installed and enabled for a model, the LLM decides when to
invoke them based on each method's docstring. You can also be explicit:

```
Use summarize_web_search to find current best practices for FastAPI health checks.
Use family_kb_ask to answer from saved documents about our house.
Use generate_image to create a cinematic photo of a silver 1980s sports car at sunset.
Use create_workflow_demo to build a product demo for a mobile calculator app.
Use create_presentation to build a slide deck about a topic.
Use deep_research to investigate local-first AI knowledge base architecture.
```
