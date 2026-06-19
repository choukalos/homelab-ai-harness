# Demo Workflow Module

An automated, LLM-driven 11-phase pipeline that researches, designs, builds,
functionally verifies, and saves high-quality single-file HTML demos. Built on
the coordinator pattern with per-phase agent invocations to avoid context window
limits on the vLLM backend.

Each phase runs as a separate short-lived LLM call, passing structured JSON
state between phases. This keeps per-invocation context well under 30K tokens
and avoids vLLM's 70K context limit that broke the old single-agent approach.

---

## Architecture

```
User Prompt → Coordinator (run_demo)
  → Phase 1:  Parse Request             (chat_completion_sync)
  → Phase 2:  KB Lookup                 (family_kb search)
  → Phase 3:  Web Research              (search_and_crawl + think_tool)
  → Phase 4:  Requirements & Design     (chat_completion_sync)
  → Phase 5:  Build Plan                (chat_completion_sync)
  → Phase 6a: Core Structure & Nav      (generate_html → validate → fix)
  → Phase 6b: Interactive Features      (generate_html → validate → fix)
  → Phase 6c: Polish & Micro-interactions (generate_html → validate → fix)
  → Phase 7:  Functional Verification   (verify_interactivity → fix, max 3 retries)
  → Phase 8:  Polish & Critique         (critique_demo → fix)
  → Phase 9:  Save Final                (save_demo → metadata.json + HTML)
```

### Key Design Decisions

- **Coordinator pattern** — each phase is a fresh LLM invocation, not a
  single long-running agent. Structured `DemoState` is passed between phases.
- **Progressive build** — Phase 6 is split into 6a/6b/6c so failures in
  polish don't invalidate the working skeleton.
- **Level 3 mock behavior** — demos simulate async behavior: loading
  spinners, toast notifications, confirmation dialogs, localStorage
  persistence, and simulated API delays (300–800ms).
- **Functional verification** — Phase 7 does static analysis of JS event
  handlers to ensure every button, form, and navigation element actually
  works. Auto-retries up to 3 times if score < 7.
- **Product insights metadata** — `metadata.json` includes `discovery_notes`,
  `complexity_score`, `level3_patterns`, and `phase_timings` for every demo.
- **Checkpoint/resume** — if the pipeline is interrupted, it can resume from
  the last completed phase via file-based checkpoints (24h TTL).
- **SSE streaming** — `/run/stream` emits real-time phase progress events
  for OpenWebUI or any SSE consumer.

---

## File Structure

All files for this module live in `ai-harness/demo_workflow/`:

| File | Purpose |
|---|---|
| `__init__.py` | Module docstring + re-exports (`CheckpointManager`, etc.) |
| `schemas.py` | Pydantic models: `DemoCreateRequest`, `DemoCreateResponse`, `DemoMetadata`, `DemoCheckpointStatus`, `DemoStreamEvent`, `DemoResumeResponse` |
| `service.py` | Coordinator: `run_demo()`, `resume_demo()`, `_run_demo_with_events()`, `CheckpointManager`, per-phase functions |
| `state.py` | `DemoState` — structured inter-phase state with `to_dict()`/`from_dict()` |
| `prompts.py` | All system prompts: phase prompts, build prompts (6a/6b/6c), verification, critique, Level 3 patterns |
| `tools.py` | Build tools: `generate_html`, `validate_html`, `fix_html`, `verify_interactivity`, `critique_demo`, `save_demo` |
| `router.py` | FastAPI router: `/run`, `/run/stream`, `/jobs`, `/jobs/{id}/checkpoint`, `/jobs/{id}/resume`, `/`, `/search`, `/{slug}`, `/{slug}/html` |

---

## API Endpoints

All endpoints mounted under `/demos`.

### POST `/demos/run`
Run the demo creation pipeline synchronously (all 11 phases). Returns
`DemoCreateResponse` with `thread_id`, `title`, `slug`, `status`,
`html_path`, and enriched `metadata`.

### POST `/demos/run/stream`
Stream the pipeline via Server-Sent Events. Emits `DemoStreamEvent` for
each phase boundary and progress update:

```
data: {"event_type":"pipeline_start","elapsed":"0:00","data":{"thread_id":"...","title":"...","prompt":"..."}}
data: {"event_type":"phase_start","phase":"Phase 1: Parse Request","phase_number":0,"elapsed":"0:00"}
data: {"event_type":"phase_complete","phase":"Phase 6a: Core Structure","phase_number":5,"elapsed":"2:15","data":{"summary":"HTML: 8432 chars","phase_elapsed":47.2}}
data: {"event_type":"pipeline_complete","elapsed":"12:34","data":{"status":"completed","slug":"...","html_path":"...","metadata":{...}}}
```

### GET `/demos/jobs`
List recent demo creation jobs (from completed demos on disk).

### GET `/demos/jobs/{thread_id}`
Get job status and output for a given thread ID.

### GET `/demos/jobs/{thread_id}/checkpoint`
Get checkpoint status: whether a checkpoint exists, last completed phase,
and whether the pipeline can be resumed. Returns `DemoCheckpointStatus`.

### POST `/demos/jobs/{thread_id}/resume`
Resume a demo pipeline from a saved checkpoint. Continues from the phase
after the last saved one. Returns `DemoCreateResponse` with `status="resumed"`.

### DELETE `/demos/jobs/{thread_id}/checkpoint`
Remove a checkpoint. Allows starting a fresh build with the same thread ID.

### POST `/demos/jobs/{thread_id}/cancel`
Best-effort cancellation for running jobs.

### GET `/demos/`
List all completed demos from the unified `demos/` directory. Supports both
workflow demos (subdirectories with `metadata.json`) and simple one-click
demos (flat `.html` files).

### GET `/demos/search?q=...`
Search demos by natural language query (matches title, description, tags).

### GET `/demos/{slug}`
Get a single demo's `metadata.json`. Includes enriched fields:
`code_quality_score`, `level3_patterns`, `discovery_notes`,
`complexity_score`, `phase_timings`, `total_build_time_seconds`.

### GET `/demos/{slug}/html`
Serve the final HTML file as `text/html`.

---

## Metadata Fields

Every completed demo writes `metadata.json` with the following enriched fields:

| Field | Description |
|---|---|
| `code_quality_score` | 1–10 score from Phase 7 static analysis of JS event handlers |
| `verification_issues` | Remaining interactivity gaps (if score < 10) |
| `functional_areas` | Verified working interactions (e.g. "Button X → fnY() → view Z") |
| `mocked_features` | List of `{feature, description, mock_type}` objects |
| `level3_patterns` | Dict of verified Level 3 patterns: `simulated_delays`, `loading_indicators`, `toast_notifications`, `confirmation_dialogs`, `data_persistence`, `key_flow_coverage` |
| `level3_realism_score` | 1–10 score from critique on natural feel of mock behavior |
| `discovery_notes` | Product insights: `mvp_features`, `nice_to_have`, `research_insights` |
| `complexity_score` | 1–10 score (how complex is the demo to build) |
| `complexity_breakdown` | `screen_count`, `interactive_elements`, `mocked_features`, `estimated_build_effort` |
| `phase_timings` | Dict of phase name → elapsed seconds |
| `total_build_time_seconds` | Total pipeline wall-clock time |

---

## Integration Points

### Siri (`ai-harness/siri/service.py`)
- **`create demo` / `build demo`** → fire-and-forget `POST /demos/run`
- **`list demos` / `find demo`** → unified listing of workflow + simple demos
- **`how well does X demo work?`** → reads quality metadata (`code_quality_score`, `level3_patterns`, etc.)
- **`how complex is X demo?`** → reads complexity metadata (`complexity_score`, `discovery_notes`)

### OpenWebUI (`ai-harness/openwebui_tools/harness_tools.py`)
- **`create_demo`** tool → `POST /demos/run` (timeout 600s)
- **`list_demos` / `find_demo`** → `/demos/` and `/demos/search`
- **Streaming** → `/demos/run/stream` for real-time phase progress in the UI

---

## Configuration

| Env Var | Default | Purpose |
|---|---|---|
| `DEMO_WORKFLOW_MODEL` | `matrix-coder` | LLM model for all demo workflow agents |
| `HARNESS_MODEL` | `gemma-moe` | Fallback model |
| `LITELLM_BASE_URL` | `http://litellm:4000` | LiteLLM proxy URL |
| `LITELLM_API_KEY` | — | LiteLLM API key |
| `MEDIA_OUTPUT_DIR` | `/data/media` | Base for generated media |
| `SEARXNG_BASE_URL` | `http://searxng:8080` | SearXNG instance |
| `CRAWL4AI_BASE_URL` | `http://crawl4ai:11235` | Crawl4AI instance |
| `MYSQL_DB_HOST` | `host.docker.internal` | MySQL host (shared with deep_research) |
| `AI_DB_NAME` | `ai_harness` | MySQL database name |

---

## Checkpointing

Checkpoints are stored at `~/.ai-harness/demo_checkpoints/{thread_id}.json`
with a 24-hour TTL. Auto-cleanup runs on each save/load operation.

- On success: checkpoint is removed automatically.
- On failure: checkpoint is saved at the failed phase, allowing resume.
- Resume via `POST /demos/jobs/{thread_id}/resume` or by calling `run_demo()` again
  with the same `thread_id` (auto-resumes).

---

## Prompt Architecture

### Phase Prompts (per-phase agent invocations)
- `PHASE_PARSE_SYSTEM` — extract structured demo brief
- `PHASE_KB_LOOKUP_SYSTEM` — analyze KB results
- `PHASE_DESIGN_SYSTEM` — comprehensive design spec + discovery notes
- `PHASE_PLAN_SYSTEM` — numbered build plan + complexity scoring
- `PHASE_SAVE_SYSTEM` — finalize metadata

### Build Prompts (6a/6b/6c progressive enhancement)
- `BUILD_STRUCTURE_SYSTEM` — DOM skeleton, nav, CSS framework only
- `BUILD_FEATURES_SYSTEM` — forms, data, state management on existing structure
- `BUILD_POLISH_SYSTEM` — transitions, active states, edge cases

All build prompts enforce senior-engineer coding standards:
IIFE/modular JS, BEM CSS, semantic HTML, defensive coding, mobile-first.

### Verification & Critique Prompts
- `VERIFY_INTERACTIVITY_SYSTEM` — static JS analysis, handler tracing,
  Level 3 pattern checks (deducts 1 pt per missing pattern)
- `CRITIQUE_SYSTEM` — visual, code quality, functional scores +
  `level3_realism_score` for natural feel of mock behavior

### Level 3 Mock Behavior (`MOCK_BEHAVIOR_LEVEL3_SYSTEM`)
Provides CSS/JS patterns for: `delay()` utility, loading overlays/spinners,
toast notifications, confirmation modals, localStorage-backed state,
optimistic updates with undo.

---

## Testing

```bash
# Run the end-to-end smoke test
bash tests/test_demo_workflow.sh
```

The smoke test exercises all endpoints: health check, synchronous creation,
response schema, HTML file verification, HTML structure, jobs listing,
demo listing, search, metadata with enriched fields, checkpoint status,
SSE streaming, and Siri integrations (create, list, quality, complexity).
