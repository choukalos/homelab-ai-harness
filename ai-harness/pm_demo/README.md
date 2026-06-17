# PM Demo — Simple One-Click Demo Generator

Instant single-file HTML demos without research or multi-phase pipelines.
Feeds an LLM a title + prompt and saves the resulting HTML directly.

---

## Architecture

```
Siri "html demo"/"prototype" intent
  → pm_demo.service.generate_demo_html()
    → LLM (via LiteLLM) with SYSTEM_PROMPT
    → Strip code fences, save as {name}-{hash}.html
    → Return { title, filename, url, html }
```

- **Output directory**: `MEDIA_OUTPUT_DIR/demos/` (unified with workflow demos)
- **URL path**: `{INTERNAL_BASE_URL}/media/files/demos/{filename}`
- **Filename format**: `{safe-name}-{8-char-hash}.html` (via `generate_media_filename()`)

---

## Integration Points

### Siri (`ai-harness/siri/service.py`)
- **Intent**: `demo` (triggered by `"html demo"`, `"one page demo"`, `"prototype"`)
- **Handler**: `_handle_demo()` — calls `generate_demo_html()` directly
- **URL rewriting**: `_rewrite_to_public_urls()` converts internal to public URLs
- **Response**: Returns link with public URL for CarPlay/Siri display

### Unified Demo Listing
Simple demos save as flat `.html` files in `demos/` alongside workflow demo
subdirectories. Both the router (`_list_all_demos()`) and Siri
(`_scan_all_demos()`) scan for both formats, providing a unified listing
and search experience. Simple demos are tagged `simple`.

---

## File Structure

- `__init__.py`: Empty module init
- `service.py`: `generate_demo_html()` — the core function
- `prompts.py`: `SYSTEM_PROMPT` — LLM instructions for HTML demo generation
- `schemas.py`: Pydantic models for request/response

---

## Comparison: PM Demo vs Demo Workflow

| Feature | PM Demo | Demo Workflow |
|---|---|---|
| Pipeline | Single LLM call | 8-phase agent pipeline |
| Research | None | Web research + KB lookup |
| Output | `demos/{name}-{hash}.html` | `demos/{slug}/final_demo.html` + `metadata.json` |
| Speed | Seconds | 2-5 minutes |
| Siri intent | `"html demo"`, `"prototype"` | `"create a demo"`, `"build a demo"` |
