# Presentation Module — Update Flow Implementation Plan

> Add "update existing presentation" capability so users can review a generated
> presentation and request changes via Siri or OpenWebUI, producing a new version.
>
> **Status**: Phases 1–6 from original plan complete. All 16/16 smoke tests passing.
> This plan adds the **update/regenerate flow** on top of that foundation.
> **Directory**: `ai-harness/presentation/`
>
> **Prerequisites already in place:**
> - `PATCH /presentation/{id}` endpoint exists and works (Session 4)
> - `PresentationUpdateRequest` schema exists
> - `regenerate_presentation()` in service.py calls `generate_presentation_sync`
> - OpenWebUI has `regenerate_presentation()` tool
> - Versioning (auto-increment, parent_id chaining) works
> - Async generation via Celery + Presenton's async API works
>
> **What's missing for a complete update flow:**
> 1. No **async** update endpoint — Siri can't wait 3-5 minutes
> 2. No **Siri intent** for "update" / "change" / "revise" a presentation
> 3. No **Celery task** for async regeneration
> 4. OpenWebUI's `regenerate_presentation` is sync only — needs async variant

---

## Architecture of the Update Flow

```
User (Siri): "Update the Q4 review to be more casual and have 12 slides"
  │
  ▼
_siri/service.py: _detect_intent() → "update_presentation"
  │
  ▼
_handle_update_presentation()
  │  ├── POST /presentation/search?title=Q4+review  → find latest version
  │  ├── LLM parse: "more casual" → tone=casual, "12 slides" → n_slides=12
  │  └── POST /presentation/{id}/update/async       → dispatch Celery task
  │
  ▼
update_presentation_task (Celery)
  │  ├── regenerate_presentation() → generate_presentation_for_worker()
  │  └── Presenton async generate + poll
  │
  ▼
Result stored in /data/media/presentations/ as {title}-v{N+1}.pptx

User (Siri): "List my presentations" → sees new version with download URL
```

```
User (OpenWebUI): "Change the Q4 review presentation to use the dark template"
  │
  ▼
OpenWebUI tool: update_presentation(presentation_id, instructions, ...)
  │  ├── POST /presentation/{id}/update/async → dispatch Celery
  │  └── return task_id
  │
  ▼
check_task_status(task_id) → completed, download link shown
```

---

## Phase 1 — Async Update Endpoint + Celery Task

**Goal**: Add `POST /presentation/{id}/update/async` so Siri can fire-and-forget.

### 1a. New Celery task: `update_presentation_task`

**File**: `presentation/tasks.py`

Add a new `@celery.task` that accepts:
- `presentation_id: str` — the presentation to update
- `update_params: dict` — same shape as `PresentationUpdateRequest` fields
- Returns `PresentationResponse` dict (same as `generate_presentation_task`)

The task calls `regenerate_presentation()` from service.py, but uses
`generate_presentation_for_worker()` (async Presenton) instead of
`generate_presentation_sync()` (blocking).

**Problem**: `regenerate_presentation()` currently hardcodes
`generate_presentation_sync(client, req)`. We need to parameterize which
generation function it calls.

**Solution**: Add `use_async: bool = False` parameter to `regenerate_presentation()`.
When `use_async=True`, call `generate_presentation_for_worker()` instead of
`generate_presentation_sync()`.

```python
def regenerate_presentation(
    client: PresentonClient,
    presentation_id: str,
    update: PresentationUpdateRequest,
    *,
    use_async: bool = False,
) -> PresentationResponse:
    # ... existing merge logic ...
    presenton_fn = (
        generate_presentation_for_worker if use_async
        else generate_presentation_sync
    )
    return presenton_fn(client, req)
```

### 1b. New router endpoint: `POST /presentation/{id}/update/async`

**File**: `presentation/router.py`

```
POST /presentation/{presentation_id}/update/async
  Body: PresentationUpdateRequest (all fields optional)
  Response: AsyncTaskResponse (task_id, title, status, message)
```

Dispatches to `update_presentation_task.apply_async()` with merged params.
Must be placed BEFORE `/{presentation_id}` catch-all in route ordering.

### 1c. Update the existing `PATCH /{presentation_id}` route

The existing PATCH route already works for sync/OpenWebUI. No changes needed
unless we want to add an `X-Async: true` header option. **Deferring this** —
the new `/update/async` endpoint is cleaner.

### 1d. Export `regenerate_presentation` for the Celery task

**File**: `presentation/tasks.py`

```python
@celery.task(bind=True, name="presentation.update_presentation", ...)
def update_presentation_task(self, presentation_id, **kwargs):
    from presentation.service import PresentonClient, regenerate_presentation
    from presentation.schemas import PresentationUpdateRequest

    update = PresentationUpdateRequest(**kwargs)
    client = PresentonClient()
    try:
        resp = regenerate_presentation(client, presentation_id, update, use_async=True)
    finally:
        client.close()
    return resp.model_dump()
```

### Files modified

| File | Change |
|------|--------|
| `presentation/service.py` | Add `use_async` param to `regenerate_presentation()` |
| `presentation/router.py` | Add `POST /{id}/update/async` endpoint |
| `presentation/tasks.py` | Add `update_presentation_task` |

---

## Phase 2 — Siri Update Intent + Handler

**Goal**: Siri recognizes "update/change/revise the [presentation]" and dispatches.

### 2a. Add "update_presentation" intent detection

**File**: `siri/service.py` — `_detect_intent()`

Add BEFORE `create_presentation` (more specific match takes priority):

```python
# Presentation update (check BEFORE creation to avoid misrouting)
if any(p in text for p in [
    "update a presentation", "update presentation",
    "update the", "update my",
    "change the presentation", "change presentation",
    "revise the presentation", "revise presentation",
    "revise my presentation", "revise a presentation",
    "modify the presentation", "modify presentation",
    "improve the presentation", "improve presentation",
]):
    return "update_presentation"
```

### 2b. Add `_handle_update_presentation()` handler

**File**: `siri/service.py`

The handler does three things:

1. **Find the presentation**: Strip the update prefix, extract the title/topic,
   call `GET /presentation/search?title=...` to find matching presentations.
   Pick the most recent version.

2. **Parse update instructions via LLM**: Send the remaining text + parent
   presentation metadata to LiteLLM and ask it to output JSON mapping
   to `PresentationUpdateRequest` fields:
   - "more casual" → `tone: "casual"`
   - "12 slides" → `n_slides: 12`
   - "dark template" → `template: "dark"`
   - "less text per slide" → `verbosity: "concise"`
   - "add a slide about budget" → appended to `instructions`

3. **Dispatch async update**: `POST /presentation/{id}/update/async` with
   the parsed params. Return fire-and-forget response.

**LLM parsing prompt** (added to `presentation/prompts.py`):

```python
UPDATE_INSTRUCTION_PROMPT = """\
The user wants to update an existing presentation. Parse their instructions
into structured update parameters.

Presentation title: {title}
Current version: {version}
Current slide count: {slide_count}
Current template: {template}
Current tone: {tone}
Current verbosity: {verbosity}
Current language: {language}

User's update instructions: {instructions}

Output ONLY a JSON object with the fields that should change. Valid fields:
- title (string)
- content (string) - new content description
- outline (string) - new markdown outline
- n_slides (integer, 3-50)
- template (string, e.g. "general", "academic", "dark", "creative")
- tone (string: "default", "casual", "professional", "funny", "educational", "sales_pitch")
- verbosity (string: "concise", "standard", "text-heavy")
- language (string)
- export_as (string: "pptx" or "pdf")
- instructions (string) - additional free-form instructions for the AI
- include_table_of_contents (boolean)
- include_title_slide (boolean)
- research (boolean)
- kb_search (boolean)

Only include fields that the user explicitly asked to change. Omit fields
the user didn't mention. If the user said something ambiguous, put it in
the "instructions" field as free-text.

Output ONLY the JSON — no preamble, no explanation, no code fences.
"""
```

### 2c. Wire up the intent in `handle_siri_chat()`

**File**: `siri/service.py`

```python
if intent == "update_presentation":
    return await _handle_update_presentation(req)
```

### 2d. Edge cases

- **No matching presentation**: "I couldn't find a presentation matching 'X'. 
  Try 'list my presentations' to see what's available."
- **Ambiguous instructions**: Put everything in `instructions` field as free-text.
- **Multiple matches**: Pick the most recent version (highest version number).
- **Async result follow-up**: "I've started updating your presentation. 
  Ask me to list your presentations when it's done."

### Files modified

| File | Change |
|------|--------|
| `siri/service.py` | Add `_detect_intent` patterns, `_handle_update_presentation`, route in `handle_siri_chat` |
| `presentation/prompts.py` | Add `UPDATE_INSTRUCTION_PROMPT` |

---

## Phase 3 — OpenWebUI Async Update Tool

**Goal**: Add `update_presentation_async()` tool so OpenWebUI can also use
the fire-and-forget flow (with `check_task_status` for polling).

### 3a. New OpenWebUI tool: `update_presentation_async()`

**File**: `openwebui_tools/presentation_tools.py`

```python
def update_presentation_async(
    self,
    presentation_id: str,
    title: str = "",
    content: str = "",
    n_slides: int = 0,
    template: str = "",
    tone: str = "",
    verbosity: str = "",
    language: str = "",
    export_as: str = "",
    instructions: str = "",
    research: bool = False,
    kb_search: bool = False,
) -> str:
    """
    Start an async update to an existing presentation (fire-and-forget).

    Returns immediately with a task_id. Use check_task_status to poll.
    Creates a new version with the specified changes.
    """
    payload = {}
    if title: payload["title"] = title
    if content: payload["content"] = content
    if n_slides > 0: payload["n_slides"] = n_slides
    if template: payload["template"] = template
    if tone: payload["tone"] = tone
    if verbosity: payload["verbosity"] = verbosity
    if language: payload["language"] = language
    if export_as: payload["export_as"] = export_as
    if instructions: payload["instructions"] = instructions
    if research: payload["research"] = research
    if kb_search: payload["kb_search"] = kb_search

    data = self._post(f"/presentation/{presentation_id}/update/async", payload, timeout=30)

    task_id = data.get("task_id", "")
    title_resp = data.get("title", "")
    message = data.get("message", "")

    lines = [
        "Presentation update started (background).",
        f"Title: {title_resp}",
        f"Task ID: {task_id}",
        "",
        message,
        "",
        f"Use check_task_status(task_id='{task_id}') to check progress.",
    ]
    return "\n".join(lines)
```

### 3b. Keep existing `regenerate_presentation()` as-is

The existing sync tool is fine for OpenWebUI's synchronous conversation flow.
The new async tool is an addition for longer-running updates.

### Files modified

| File | Change |
|------|--------|
| `openwebui_tools/presentation_tools.py` | Add `update_presentation_async()` method |

---

## Phase 4 — Smoke Tests

**Goal**: Validate the update flow end-to-end.

### 4a. Add tests to `tests/test_presentation.sh`

| Test # | Description |
|--------|-------------|
| 17 | Find existing presentation by title via `/search` |
| 18 | `POST /{id}/update/async` — dispatch update task |
| 19 | `GET /tasks/{task_id}` — verify task completes |
| 20 | Verify new version exists (v2) with correct parent_id |
| 21 | Verify new version has updated params (e.g., changed tone) |
| 22 | Siri update intent detection test |
| 23 | Siri update handler end-to-end (title match + async dispatch) |

### 4b. Test data setup

The smoke test first creates a baseline presentation, then tests updating it:

```bash
# Step 1: Create baseline
TITLE="Smoke Update Test"
RESP=$(curl -s -X POST ... /presentation/generate -d '{"title": "$TITLE", ...}')
PRESENTATION_ID=$(echo $RESP | jq -r '.presentation_id')

# Step 2: Update async
UPDATE_RESP=$(curl -s -X POST ... /presentation/$PRESENTATION_ID/update/async \
  -d '{"tone": "casual", "n_slides": 5}')
TASK_ID=$(echo $UPDATE_RESP | jq -r '.task_id')

# Step 3: Poll until complete
# Step 4: Verify v2 exists with tone=casual, n_slides=5
```

### Files modified

| File | Change |
|------|--------|
| `tests/test_presentation.sh` | Add tests 17–23 |

---

## Phase 5 — Integration Testing

**Goal**: Validate from all entry points.

### 5a. Siri voice flow

```
User: "Hey Siri, update the Q4 review presentation to be more casual"
Siri: "I've started updating your Q4 review presentation. 
       It will take a few minutes. 
       Ask me to list your presentations when it's done."

User: "Hey Siri, list my presentations"
Siri: "I found 3 presentations. ... Q4 Review v2: https://..."
```

### 5b. OpenWebUI flow

```
User: "Update the Q4 review to use the dark template and have 12 slides"
Tool: update_presentation_async(id="xxx", template="dark", n_slides=12)
Assistant: "Starting update... use check_task_status to check progress"
User: "Check the status"
Tool: check_task_status(task_id="...")
Assistant: "Done! Download: https://..."
```

### 5c. Direct API

```bash
curl -X POST .../presentation/{id}/update/async \
  -d '{"tone": "casual", "n_slides": 12}'
# → {"task_id": "...", "title": "Q4 Review", "status": "submitted"}

curl .../presentation/tasks/{task_id}
# → {"status": "completed", "result": {...}}
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| LLM misparses Siri instructions | Fallback: put all text in `instructions` field; Presenton's LLM handles it |
| No matching presentation found | Clear error message + suggestion to list presentations |
| Update task fails mid-way | Celery retry + error state with message |
| Version number conflict | Existing versioning logic handles this via `_next_version()` |
| Presenton async update not supported | Presenton's `/generate` and `/generate/async` both accept `parent_id` — 
  same mechanism we already use for versioning ✅ |

---

## Implementation Order

1. **Phase 1** — Service/router/task changes (backend foundation)
2. **Phase 2** — Siri intent + handler (voice entry point)
3. **Phase 3** — OpenWebUI async tool (chat entry point)
4. **Phase 4** — Smoke tests
5. **Phase 5** — Integration testing

Estimated total: ~3-4 hours of implementation.
