# Presentation Module — Smoke Test Debug Session

> **Date**: 2026-06-19
> **Trigger**: `tests/test_presentation.sh` reveals 3 issues in the presentation pipeline
> **Status**: In progress
>
> ### Smoke test failure summary
>
> ```
> Test 6:  GET /presentation/search?title=Smoke   → ❌ HTTP 404
> Test 8:  Siri list_presentations                 → "I had trouble listing presentations."
> Test 9:  Siri find_presentation                  → "I had trouble searching presentations."
> ```
>
> Tests 1–5 and 7 pass. The presentations directory (`/data/media/presentations/`) is empty
> (the async Celery task from Test 3 hasn't completed by the time the smoke test finishes).

---

## Root Cause Analysis

### Problem 1: `/presentation/search` returns HTTP 404

**Cause**: The `/search` route is defined in `router.py` before `/{presentation_id}`,
which should work in FastAPI. However, the route ordering has a latent bug:
`/download/{filename}` is defined AFTER `/{presentation_id}`, meaning
`/presentation/download/foo` would be matched by `presentation_id="download"` first,
returning 404 because no presentation has ID "download".

The `/search` returning 404 likely means either:
- The running app hasn't been restarted to pick up the latest `router.py` with the
  `/search` endpoint (this endpoint was added in Session 3/4).
- OR there's a route conflict where `/{presentation_id}` is matching "search" as a literal ID.

**Verification needed**: Check if the running app has the latest code. The `/list` endpoint
works (Test 2 passes), so the router IS loaded. The question is whether `/search` was
actually deployed.

### Problem 2: Siri handlers use wrong API key for internal calls

**Cause**: In `siri/service.py`, the `_handle_list_presentations()` and
`_handle_find_presentation()` functions call internal harness endpoints using:

```python
headers={"X-API-Key": req.session_id or ""}
```

But the test sends `{"text": "list my presentations"}` without `session_id`,
so `req.session_id` is `None`, and the header becomes `X-API-Key: ""`.

The `/presentation/list` and `/presentation/search` endpoints use
`require_harness_auth`, which checks against `HARNESS_API_KEY`, not `SIRI_API_KEY`
and certainly not an empty string. The 401 is caught by the `except` block and
returns the "I had trouble..." response.

The same bug exists in `_handle_create_presentation()` (Test 7 passes only because
it uses fire-and-forget with `asyncio.create_task()` — the auth failure is silently
logged in the background).

**Fix**: Use `HARNESS_API_KEY` from `core.config` for internal-to-harness calls
from the Siri service. This is the same pattern that would be needed for the
demo workflow's internal calls (and likely has the same bug there too).

### Problem 3: `/download/{filename}` route conflicts with `/{presentation_id}`

**Cause** (latent bug): In `router.py`, the download endpoint:
```python
@router.get("/download/{filename}")
```
is defined AFTER:
```python
@router.get("/{presentation_id}")
```

So `/presentation/download/foo.pptx` matches `presentation_id="download"` first,
`get_presentation("download")` returns None, and the endpoint raises 404.
The actual download endpoint is never reached.

---

## Fix Plan

### Task 1: Fix route ordering in `presentation/router.py`

**File**: `presentation/router.py`

Move `/search` and `/download/{filename}` to be defined BEFORE `/{presentation_id}`
to prevent route conflicts. The final route order should be:

```
POST /outline
POST /generate
POST /generate/async
GET  /tasks/{task_id}
GET  /list
GET  /search               ← keep before /{id} (already is)
GET  /download/{filename}  ← MOVE before /{id} (currently after)
GET  /{presentation_id}    ← catch-all, must be after all literal routes
PATCH /{presentation_id}
DELETE /{presentation_id}
```

**Change**: Move the `@router.get("/download/{filename}")` block to appear
immediately after `@router.get("/search")` and BEFORE `@router.get("/{presentation_id}")`.

### Task 2: Fix Siri internal auth — use HARNESS_API_KEY

**Files**: `siri/service.py`

In the following functions, change `X-API-Key: req.session_id or ""` to
`X-API-Key: HARNESS_API_KEY`:

- `_handle_create_presentation()` — line ~635: `"X-API-Key": req.session_id or ""`
- `_handle_list_presentations()` — line ~678: `"X-API-Key": req.session_id or ""`
- `_handle_find_presentation()` — line ~740: `"X-API-Key": req.session_id or ""`

Also check the demo workflow handlers for the same pattern:
- `_handle_create_demo_workflow()` — line ~274: `"X-API-Key": req.session_id or ""`
- `_handle_demo_complexity()` — check if it has similar issue
- `_handle_demo_quality()` — check if it has similar issue
- `_handle_list_demos()` — check if it has similar issue
- `_handle_find_demo()` — check if it has similar issue

**Implementation**:
```python
from core.config import HARNESS_API_KEY, INTERNAL_BASE_URL

# In each handler, replace:
headers={"X-API-Key": req.session_id or ""}
# With:
headers={"X-API-Key": HARNESS_API_KEY}
```

### Task 3: Verify the running app has the latest code

After applying fixes, rebuild and restart the harness:
```bash
cd /home/chuck/homelab/compose
docker compose -f compose.ai-harness.yml down
docker compose -f compose.ai-harness.yml up -d --build ai-harness
```

### Task 4: Re-run the smoke test

```bash
cd /home/chuck/homelab/ai-harness/tests
./test_presentation.sh
```

Expected results after fixes:
- Test 6 (Search): Should return HTTP 200 with 0 results (no presentations yet)
- Test 8 (Siri list): Should return "There are no presentations yet" or list any that exist
- Test 9 (Siri find): Should return "No presentations found matching 'machine learning'"

### Task 5 (Optional): Fix the async task completion gap

The smoke test dispatches a presentation via Celery (Test 3) but doesn't wait for
completion. By Test 6, the task is still running, so there are no presentations
on disk yet. This is expected behavior for the smoke test (it's testing the API
endpoints, not waiting for full pipeline completion).

However, to make the test more robust, consider:
- Adding a poll-and-wait for the task to complete before running search/list tests
- OR explicitly acknowledging that tests 6–9 test against an empty state

---

## Files to modify

| File | Changes |
|------|---------|
| `presentation/router.py` | Move `/download/{filename}` before `/{presentation_id}` (fix route conflict) |
| `siri/service.py` | Replace `req.session_id or ""` → `HARNESS_API_KEY` on lines 121, 274, 635, 677, 740 |

---

## Risks

| Risk | Mitigation |
|------|------------|
| `HARNESS_API_KEY` not set in container | Check `.env` — should be set. If empty, the harness itself can't authenticate. |
| Demo workflow handlers have same auth bug | Audit and fix all Siri→internal calls in the same pass |
| Route reordering breaks existing clients | The download endpoint is likely already broken, so fixing it is net-positive |
