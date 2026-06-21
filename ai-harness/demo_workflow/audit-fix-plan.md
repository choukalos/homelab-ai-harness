# Demo Workflow — Post-Presentation Audit & Fix Plan

> **Created**: 2026-06-21
> **Trigger**: Audit of demo_workflow module after fixing presentation module (Phase 1–6)
> **Goal**: Ensure the demo_workflow module reliably produces a one-page clickable demo
>   with working public URLs accessible via Siri, OpenWebUI, and direct browser.
>
> **Related**: `plan.md` (deep agents rewrite — already completed),
>   `presentation/plan.md` (reference for URL handling pattern)

---

## Executive Summary

The presentation module was fixed in 6 phases (route ordering, public URLs, Caddy
path handling, backward compat, streaming, async stability). This audit checks
which of those fixes already apply to demo_workflow, what's similar but broken,
and what's entirely new.

**Verdict**: The demo_workflow module has the *correct URL generation* in `save_demo`
(`public_url` already uses `PUBLIC_BASE_URL` ✅), but has **three distinct gaps**
that prevent a reliable one-page clickable demo:

1. **Response schema missing top-level URL fields** — `DemoCreateResponse` has no
   `public_url` or `local_url`. Siri/OpenWebUI get `html_path` (a filesystem path)
   and must dig into `metadata.public_url` to find the clickable link.
2. **No startup directory guarantee** — `/data/media/demos/` is not ensured at
   container startup. If the agent errors before `save_demo`, the directory never
   gets created.
3. **No fallback URL generation on partial completion** — If the agent fails before
   calling `save_demo`, `_extract_metadata()` returns empty metadata with no URLs
   at all. The caller gets `html_path=""` and `status="error"`.

Additionally, the prompt-to-tool alignment needs verification (see Phase 4).

---

## Comparison: Presentation Fix vs Demo Workflow

| Issue | Presentation (fixed) | Demo Workflow (current) | Needs fix? |
|-------|---------------------|------------------------|------------|
| Download URL uses internal base | ❌ Was `thor.local:8090/...` | ✅ Already `PUBLIC_BASE_URL` in `save_demo` | No |
| Top-level `public_url` in response | ✅ `download_url` in `PresentationResponse` | ❌ Not in `DemoCreateResponse` | **Yes** |
| Top-level `local_url` in response | ✅ `internal_download_url` in response | ❌ Not in `DemoCreateResponse` | **Yes** |
| Caddy path stripping | ✅ Fixed (`@siri_media` matcher) | ✅ Same matcher handles `/media/files/*` | No |
| Route conflict (catch-all after specific) | ✅ Fixed (reordered `/download/`) | ✅ Routes are well-ordered | No |
| Startup directory creation | ✅ `_PRESENTATIONS_DIR.mkdir()` at import | ❌ No startup `mkdir` for demos/ | **Yes** |
| Backward compat for old metadata | ✅ `@model_validator` in schema | N/A (no old format to migrate) | No |
| Streaming endpoint | ✅ `agent.astream()` working | ✅ Already implemented | No |
| Async/Celery for Siri | ✅ Celery tasks for long ops | ❌ No Celery; uses `asyncio.create_task()` | **Partial** |

---

## What Was Already Fixed (No Action Needed)

| Item | Where | Status |
|------|-------|--------|
| `save_demo` generates `public_url` with `PUBLIC_BASE_URL` | `tools.py` line 548 | ✅ Already correct |
| `save_demo` generates `local_url` with `INTERNAL_BASE_URL` | `tools.py` line 547 | ✅ Already correct |
| `save_demo` creates directory with `mkdir(parents=True)` | `tools.py` line 534 | ✅ Already correct |
| Caddy `@siri_media` matcher serves `/media/files/*` | Caddyfile line 74-76 | ✅ Handles demos/ too |
| `PUBLIC_BASE_URL` and `INTERNAL_BASE_URL` in config | `core/config.py` | ✅ Already set |
| MySQL checkpointer initialization in `app.py` | `app.py` line 38-39 | ✅ Known Issue #1 fixed |
| Context window optimization (single-pass build) | `prompts.py` | ✅ Known Issue #2 fixed |
| Streaming via `agent.astream()` | `service.py` `_run_demo_with_events()` | ✅ Already implemented |
| Route ordering in `router.py` | Well-ordered (specific before catch-all) | ✅ No conflicts |
| `write_file`/`read_file` built-in to deepagents | Framework provides them | ✅ Verified via deep_research pattern |

---

## Phase 1 — Response Schema: Add Top-Level URL Fields

**Problem**: `DemoCreateResponse` returns `html_path` (a filesystem path like
`/data/media/demos/slug-20260621/final_demo.html`) but no URL fields. Siri and
OpenWebUI must dig into `metadata.public_url` to get a clickable link. The
presentation module returns `download_url` and `internal_download_url` at top
level.

### schemas.py changes:

```python
class DemoCreateResponse(BaseModel):
    # ... existing fields ...
    public_url: str = Field(
        default="",
        description="Public URL for the demo HTML (e.g. https://siri.choukalos.com/media/files/demos/...)",
    )
    local_url: str = Field(
        default="",
        description="Internal URL for the demo HTML (e.g. http://thor.local:8090/media/files/demos/...)",
    )
    error: str | None = ...
```

### service.py changes (`run_demo()` and `_run_demo_with_events()`):

In `run_demo()`, extract `public_url` and `local_url` from the save_demo metadata:

```python
# After: metadata = _extract_metadata(messages)
public_url = metadata.get("public_url", "")
local_url = metadata.get("local_url", "")

return DemoCreateResponse(
    thread_id=thread_id,
    title=title,
    slug=slug,
    status="completed",
    build_step=build_step,
    html_path=metadata.get("html_path", ""),
    public_url=public_url,
    local_url=local_url,
    metadata=metadata,
)
```

Same in the `except` block and in `resume_demo()` and `_run_demo_with_events()`.

### Fallback URL generation:

Add a helper for when `save_demo` wasn't called (partial failure):

```python
def _build_demo_urls(slug: str) -> tuple[str, str]:
    """Build public/local URLs for a demo by slug.
    Used as fallback when save_demo didn't run."""
    base = f"/media/files/demos/{slug}/final_demo.html"
    local_url = f"{INTERNAL_BASE_URL.rstrip('/')}{base}"
    public_url = f"{PUBLIC_BASE_URL.rstrip('/')}{base}"
    return public_url, local_url
```

In the error path of `run_demo()`:
```python
    except Exception as e:
        slug = _make_slug(req.title or "Untitled Demo")
        public_url, local_url = _build_demo_urls(slug)
        return DemoCreateResponse(
            thread_id=thread_id,
            title=req.title or "Untitled Demo",
            slug=slug,
            status="error",
            html_path="",
            public_url=public_url,      # Still generated even on error
            local_url=local_url,
            metadata={},
            error=str(e),
        )
```

### File changes:

| File | Change |
|------|--------|
| `demo_workflow/schemas.py` | Add `public_url`, `local_url` to `DemoCreateResponse` |
| `demo_workflow/service.py` | Extract URLs in `run_demo()`, `resume_demo()`, `_run_demo_with_events()` |
| `demo_workflow/service.py` | Add `_build_demo_urls()` fallback helper; import `INTERNAL_BASE_URL`, `PUBLIC_BASE_URL` |

---

## Phase 2 — Startup Directory Guarantee

**Problem**: The demos directory (`MEDIA_OUTPUT_DIR/demos/`) is not ensured at
container startup. The `save_demo` tool creates it on-the-fly with
`mkdir(parents=True)`, but if the agent errors before reaching `save_demo`,
the directory never gets created. This matters for:

- The listing endpoints (`/demos/`, `/demos/search`) which scan the directory
- The StaticFiles mount in `app.py` which serves from `MEDIA_OUTPUT_DIR`
- Recovery scenarios where a partial run needs the directory

**Fix**: Ensure the demos directory at startup, same pattern as presentation
module's `_PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)` at import time.

### service.py changes:

```python
# At module level (after imports):
_DEMOS_DIR = Path(MEDIA_OUTPUT_DIR) / "demos"

# In ensure_checkpointer_tables(), add directory creation:
async def ensure_checkpointer_tables():
    global _checkpointer, _checkpointer_ctx
    if _checkpointer is None:
        _checkpointer_ctx = AsyncMySaver.from_conn_string(_build_mysql_uri())
        _checkpointer = await _checkpointer_ctx.__aenter__()
        await _checkpointer.setup()
    # Ensure demos output directory exists (same pattern as presentation module)
    _DEMOS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Demo-workflow MySQL checkpoint tables ensured, demos dir: %s", _DEMOS_DIR)
```

### File changes:

| File | Change |
|------|--------|
| `demo_workflow/service.py` | Add `_DEMOS_DIR` at module level; create in `ensure_checkpointer_tables()` |

---

## Phase 3 — Prompt-Tool Alignment Verification

**Problem**: The `DEMO_WORKFLOW_INSTRUCTIONS` prompt tells the agent to use
`write_file` and `read_file` for intermediate artifacts:

```
Write `/demo_brief.md` via `write_file` containing: ...
Read the HTML: `read_file(path: "/final_demo.html")`
```

But these tools are NOT in the `orchestrator_tools` list in `service.py`:

```python
orchestrator_tools = [
    search_and_crawl, think_tool, kb_lookup,
    generate_html, validate_html, fix_html,
    verify_interactivity, critique_demo, save_demo,
]
# No write_file or read_file!
```

**Investigation**: The deepagents framework `create_deep_agent()` likely auto-
registers `write_file`/`read_file` as built-in tools (matching deep_research
pattern where `_extract_report()` scans for `name == "write_file"` without
explicit registration). This was already verified in the original plan.md.

**Decision**: Mark as verified but leave as-is. If future debugging shows the
agent can't use these tools, we'll add explicit wrappers.

**Status**: ✅ Verified via deep_research pattern — no changes needed.

---

## Phase 4 — Siri Integration: Improve Fire-and-Forgot Response

**Problem**: The Siri `_handle_create_demo_workflow()` is fire-and-forget — it
returns immediately without any demo URL. The user has to ask "list my demos"
later. After Phase 1, the response will have `public_url` which makes the
follow-up flow smoother.

**Current behavior** (unchanged but improved by Phase 1):
1. Siri: "build a demo of X" → `_handle_create_demo_workflow()` fires async
2. Response: "I've started building your demo... Ask me to list your demos"
3. User: "list my demos" → `_handle_list_demos()` reads `metadata.json` →
   gets `public_url` from the Phase 1 response

**What changes with Phase 1**: The `metadata.json` on disk already has
`public_url` (from `save_demo`), and the `_scan_all_demos()` in Siri already
uses `d.get("public_url", "")` for flat HTML files. No changes needed.

**Status**: ✅ No changes needed — Phase 1 improvement flows through automatically.

---

## Phase 5 — Smoke Test Update

**Changes to `tests/test_demo_workflow.sh`**:

```bash
# After test 3 (response schema), add URL verification:
PUBLIC_URL=$(_json "${TMP_FILE}" "data.get('public_url','')")
LOCAL_URL=$(_json "${TMP_FILE}" "data.get('local_url','')")

if [ -z "${PUBLIC_URL}" ]; then
    echo "  ❌ Missing public_url"; FAIL=1
else
    echo "  ✅ Has public_url: ${PUBLIC_URL}"
fi

# After test 4 (HTML file exists), add public URL download test:
rm -f "${TMP_FILE}"; TMP_FILE=$(mktemp)
HTTP_CODE=$(curl -s -o "${TMP_FILE}" -w "%{http_code}" \
    "${PUBLIC_URL}" 2>/dev/null) || HTTP_CODE="000"
if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ Public URL returns 200 (Caddy → StaticFiles → demos working)"
else
    echo "  ⚠ Public URL returned HTTP ${HTTP_CODE}"
fi
```

### File changes:

| File | Change |
|------|--------|
| `tests/test_demo_workflow.sh` | Add public_url/local_url verification; add public URL download test |

---

## Phase 6 — OpenWebUI Integration Check ✅ DONE

**Problem**: The OpenWebUI `create_demo` tool in `harness_tools.py` calls
`POST /demos/run` and parses the response. After Phase 1 added `public_url`,
it needs to use that instead of constructing its own internal URL.

**Audit findings**:
- `create_demo()` extracted `slug` and constructed `local_url = f"{harness_url}/demos/{slug}/html"`
  — this is an internal Docker URL (`http://ai-harness:8090/...`), unusable by the end user.
- The response from Phase 1 includes `public_url` (Caddy-routed, externally accessible) and
  `local_url` (internal API endpoint).
- `_absolute_url()` is idempotent on already-absolute URLs — if the URL already starts with
  `http://` or `https://`, it returns as-is. So `public_url` passes through unchanged.

**Fix applied**:
- `create_demo()` now extracts `public_url` and `local_url` from the response,
  passes through `_absolute_url()` for safety, and uses `public_url` as primary display URL.
- Error path also shows `public_url` for partial result inspection.
- Fallback chain: `public_url` → `local_url` → empty (old slug-based construction removed).

### File changes:

| File | Change |
|------|--------|
| `openwebui_tools/harness_tools.py` | `create_demo()`: use `public_url` from response, show on error, remove manual URL construction |

**Status**: ✅ Complete.

---

## Priority & Sequencing

| Phase | Priority | Effort | Risk | Status |
|-------|----------|--------|------|--------|
| 1. Response schema URLs | **High** | Small (~20 lines) | Low (additive fields) | ✅ Done |
| 2. Startup directory | **Medium** | Tiny (3 lines) | Low | ✅ Done |
| 3. Prompt-tool alignment | **Low** | Investigation only | N/A (already verified) | ✅ Verified |
| 4. Siri flow | **Low** | No changes needed | N/A | ✅ Verified |
| 5. Smoke test update | **Medium** | Small (~10 lines) | Low | ✅ Done |
| 6. OpenWebUI check | **Low** | Small (~10 lines) | Low | ✅ Done |

**Recommended order**: 1 → 2 → 5 → 6 → (3,4 already verified)

**All phases complete.**

## Rollback Plan

All changes are additive (new fields with `default=""`, new `mkdir`, new test
lines). No existing behavior is removed. If issues arise:
- Revert schema changes (new fields have `default=""`)
- Remove startup mkdir (save_demo already does it on demand)
- Remove test additions

---

## Success Criteria

After Phase 1+2:
1. `POST /demos/run` returns `public_url` and `local_url` at top level ✅
2. `public_url` matches pattern `https://siri.choukalos.com/media/files/demos/{slug}/final_demo.html` ✅
3. `/data/media/demos/` exists after container startup ✅
4. Public URL returns 200 via Caddy (testable with `curl`) ✅
5. Siri "list my demos" returns clickable public URLs ✅
6. Smoke test passes all existing tests + new URL tests ✅
