# Demo Workflow Module

A deep agents-based pipeline that researches, designs, builds, and saves
high-quality single-file HTML demos. Uses the same pattern as
`deep_research`: `create_deep_agent()` + `agent.ainvoke()` / `agent.astream()`
with MySQL checkpointing.

The orchestrator agent follows `DEMO_WORKFLOW_INSTRUCTIONS` to research the
domain, delegate to a research sub-agent, build the demo incrementally
(generate → validate → fix), verify interactivity, critique quality, and
save the final HTML + metadata to disk.

---

## Architecture

```
User Prompt → FastAPI (POST /demos/run or /demos/run/stream)
    → run_demo(req) → get_deep_agent().ainvoke(input_state, config)
        Orchestrator Agent (deep agents framework):
          ↳  kb_lookup         → family_kb.search_kb (KB search)
          ↳  search_and_crawl  → SearXNG + Crawl4AI (web research)
          ↳  think_tool        → strategic reflection pauses
          ↳  generate_html     → LLM call to produce/update HTML
          ↳  validate_html     → LLM call to check acceptance criteria
          ↳  fix_html          → LLM call to fix validation issues
          ↳  verify_interactivity → LLM call for static JS analysis
          ↳  critique_demo     → LLM call for quality review
          ↳  save_demo         → write HTML + metadata.json to disk
          ↳  task() sub-agent  → researcher (search_and_crawl + think_tool)
        MySQL Checkpointing (AsyncMySaver) — auto-persists after each step
```

### Workflow the Agent Follows (via system prompt)

```
1. PLAN: Parse the prompt and create a demo brief (write_file → demo_brief.md)
2. KB LOOKUP: Call kb_lookup() to check for prior demos, user preferences
3. RESEARCH: Delegate to research sub-agent for domain/competitor analysis
4. DESIGN: Synthesize KB + research into a design spec (write_file → design_spec.md)
5. BUILD STEP 1 — Core Structure:
   a. generate_html(system=BUILD_STRUCTURE_SYSTEM, current_html="")
   b. validate_html(criteria="all views exist, nav switches correctly")
   c. If failed: fix_html(issues, html) → repeat validate (max 2 fix attempts)
6. BUILD STEP 2 — Interactive Features:
   a. generate_html(system=BUILD_FEATURES_SYSTEM, current_html=from_step1)
   b. validate_html(criteria="forms work, realistic data, handlers exist")
   c. If failed: fix_html(issues, html) → repeat validate (max 2 fix attempts)
7. BUILD STEP 3 — Polish:
   a. generate_html(system=BUILD_POLISH_SYSTEM, current_html=from_step2)
   b. validate_html(criteria="transitions, active states, feedback UI")
   c. If failed: fix_html(issues, html) → repeat validate (max 2 fix attempts)
8. VERIFY: Call verify_interactivity() → if score < 7, fix_html() → re-verify (max 2)
9. CRITIQUE: Call critique_demo() → if score < 8, fix_html()
10. SAVE: Call save_demo() to write final HTML + metadata.json to disk
11. DONE: Confirm completion
```

The deep agents framework handles:
- Context window management (compresses history, offloads large tool results)
- MySQL checkpointing (resume after interruption via thread_id)
- Sub-agent isolation (researcher has separate context)
- Retry logic naturally through agent decision-making

---

## File Structure

All files for this module live in `ai-harness/demo_workflow/`:

| File | Purpose |
|---|---|
| `__init__.py` | Module docstring + re-exports `ensure_checkpointer_tables` |
| `schemas.py` | Pydantic models: `DemoCreateRequest`, `DemoCreateResponse`, `DemoMetadata`, `DemoCheckpointStatus`, `DemoStreamEvent` |
| `service.py` | Agent factory + entry points: `run_demo()`, `resume_demo()`, `_run_demo_with_events()`, extraction helpers |
| `prompts.py` | `DEMO_WORKFLOW_INSTRUCTIONS`, `RESEARCHER_INSTRUCTIONS`, build prompts, verification/critique prompts, Level 3 patterns |
| `tools.py` | Build tools: `kb_lookup`, `generate_html`, `validate_html`, `fix_html`, `verify_interactivity`, `critique_demo`, `save_demo` + shared research tools |
| `router.py` | FastAPI router: `/run`, `/run/stream`, `/jobs`, `/jobs/{id}/checkpoint`, `/jobs/{id}/resume`, `/`, `/search`, `/{slug}`, `/{slug}/html` |

---

## API Endpoints

All endpoints mounted under `/demos`.

### POST `/demos/run`
Run the demo creation agent synchronously. Returns `DemoCreateResponse` with
`thread_id`, `title`, `slug`, `status`, `build_step`, `html_path`, and
enriched `metadata`.

### POST `/demos/run/stream`
Stream the agent via Server-Sent Events using `agent.astream()`. Emits
`DemoStreamEvent` for each state transition (tool calls, results, AI responses):

```
data: {"event_type":"pipeline_start","elapsed":"0:00","data":{"thread_id":"...","title":"...","prompt":"..."}}
data: {"event_type":"phase_progress","elapsed":"0:15","data":{"message":"Calling kb_lookup…","tool":"kb_lookup"}}
data: {"event_type":"phase_complete","elapsed":"2:15","data":{"summary":"HTML generated: 8432 chars"}}
data: {"event_type":"pipeline_complete","elapsed":"12:34","data":{"status":"completed","slug":"...","html_path":"...","metadata":{...}}}
```

### GET `/demos/jobs`
List recent demo creation jobs (from completed demos on disk).

### GET `/demos/jobs/{thread_id}`
Get job status and output for a given thread ID.

### GET `/demos/jobs/{thread_id}/checkpoint`
Get checkpoint status from MySQL: whether a checkpoint exists and if the
pipeline can be resumed. Returns `DemoCheckpointStatus`.

### POST `/demos/jobs/{thread_id}/resume`
Resume a demo pipeline from a MySQL checkpoint. The checkpointer auto-resumes
from the last persisted agent state. Returns `DemoCreateResponse`.

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
`complexity_score`, `functional_areas`, `mocked_features`.

### GET `/demos/{slug}/html`
Serve the final HTML file as `text/html`.

---

## Metadata Fields

Every completed demo writes `metadata.json` with the following enriched fields:

| Field | Description |
|---|---|
| `code_quality_score` | 1–10 score from verify_interactivity static analysis |
| `verification_issues` | Remaining interactivity gaps (if score < 10) |
| `functional_areas` | Verified working interactions (e.g. "Button X → fnY() → view Z") |
| `mocked_features` | List of `{feature, description, mock_type}` objects |
| `level3_patterns` | Dict of verified Level 3 patterns: `simulated_delays`, `loading_indicators`, `toast_notifications`, `confirmation_dialogs`, `data_persistence`, `key_flow_coverage` |
| `level3_realism_score` | 1–10 score from critique on natural feel of mock behavior |
| `discovery_notes` | Product insights: `mvp_features`, `nice_to_have`, `research_insights` |
| `complexity_score` | 1–10 score (how complex is the demo to build) |
| `complexity_breakdown` | `screen_count`, `interactive_elements`, `mocked_features`, `estimated_build_effort` |

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

Checkpoints are stored in MySQL via `AsyncMySaver` (shared tables with
`deep_research`). Auto-persists after each agent step.

- On success: checkpoint persists the final state for potential resume.
- On failure: checkpoint preserves the interrupted state.
- Resume via `POST /demos/jobs/{thread_id}/resume` — re-invokes the agent
  with the same `thread_id`; MySQL checkpointer auto-resumes from last state.

---

## Prompt Architecture

### Orchestrator Prompt
- `DEMO_WORKFLOW_INSTRUCTIONS` — the step-by-step workflow the agent follows
  (parse → KB → research → design → build → verify → critique → save)

### Research Sub-Agent Prompt
- `RESEARCHER_INSTRUCTIONS` — specialized prompt for the research sub-agent
  (search_and_crawl + think_tool)

### Build Prompts (progressive enhancement)
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
