# Demo Workflow — Deep Agents Rewrite Plan

## Problem

The current demo_workflow module uses a custom 11-phase coordinator loop
(~670 lines in `service.py`) that:
- Never uses the `create_deep_agent()` it already builds in `get_deep_agent()`
- Writes output to `/data/media/demos/` which doesn't exist → no files are saved
- Passes raw HTML strings (20K+ chars) between phases, eating context
- Has no Deep Agents context management (compression, offloading, subagent isolation)
- The streaming path has no checkpointing at all

Meanwhile `deep_research` uses `create_deep_agent()` + `agent.ainvoke()` with
MySQL checkpointing in ~150 lines and works great.

## Goal

Rewrite demo_workflow to use the **exact same deep agents pattern as deep_research**:
- `create_deep_agent()` with orchestrator + research sub-agent
- `agent.ainvoke()` for sync runs, `agent.astream()` for SSE streaming
- MySQL checkpointing via `AsyncMySaver` (shared tables with deep_research)
- Tool-based workflow: the agent uses tools to build the demo
- Same API hooks for Siri and OpenWebUI

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
1. PLAN: Create TODO list via write_todos (parse prompt, set title)
2. KB LOOKUP: Call kb_lookup() to check for prior demos, user preferences
3. RESEARCH: Delegate to research sub-agent for domain/competitor analysis
4. DESIGN: Synthesize KB + research into a design spec (mental, no file)
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

### Tools Used (all from our existing harness)

| Tool | Source | Purpose |
|------|--------|---------|
| `kb_lookup` | `demo_workflow/service.py` | Search family_kb for prior info |
| `search_and_crawl` | `deep_research/tools.py` | SearXNG + Crawl4AI web research |
| `think_tool` | `deep_research/tools.py` | Strategic reflection between steps |
| `generate_html` | `demo_workflow/tools.py` | LLM call to produce/update demo HTML |
| `validate_html` | `demo_workflow/tools.py` | LLM call to check acceptance criteria |
| `fix_html` | `demo_workflow/tools.py` | LLM call to fix issues in HTML |
| `verify_interactivity` | `demo_workflow/tools.py` | Static JS analysis, score 1-10 |
| `critique_demo` | `demo_workflow/tools.py` | Quality review, score 1-10 |
| `save_demo` | `demo_workflow/tools.py` | Write HTML + metadata.json to disk |

Sub-agent (researcher) gets: `search_and_crawl` + `think_tool` (same as deep_research).

---

## Files to Change

### Session 1: `tools.py` — Fix save_demo + add write_file tool

**Problem**: `save_demo` writes to `/data/media/demos/` which may not exist.

**Changes**:
- Ensure `MEDIA_OUTPUT_DIR/demos/` exists before writing (mkdir with parents=True)
- Add a `write_file` tool (matching deep_research pattern) for the agent to
  write intermediate artifacts like `demo_brief.md` and `design_spec.md` —
  this gives the agent a place to "remember" structured data across iterations
- Keep all existing tools (`generate_html`, `validate_html`, `fix_html`,
  `verify_interactivity`, `critique_demo`, `save_demo`) — they work fine,
  just need `save_demo` to handle missing directories gracefully
- Remove the `@tool` wrappers that call async impls without awaiting
  (the `@tool` decorators are sync but call `await _xxx_impl()` — this
  breaks when the agent dispatches them. Fix: keep the `@tool` wrappers
  as thin sync delegates that run the async via `asyncio.run()` or use
  `@tool` with `coroutine=True`)

### Session 2: `prompts.py` — Rewrite for deep agent workflow

**Changes**:
- Replace `DEMO_WORKFLOW_INSTRUCTIONS` (the old monolithic prompt) with a
  structured workflow instruction matching the deep_research pattern
- Keep `RESEARCHER_INSTRUCTIONS` (reused from current code, same as deep_research)
- Keep `BUILD_STRUCTURE_SYSTEM`, `BUILD_FEATURES_SYSTEM`, `BUILD_POLISH_SYSTEM`
  (used by `generate_html` — these are system prompts passed per-call)
- Remove all phase-specific system prompts that are no longer needed:
  `PHASE_PARSE_SYSTEM`, `PHASE_KB_LOOKUP_SYSTEM`, `PHASE_DESIGN_SYSTEM`,
  `PHASE_PLAN_SYSTEM`, `PHASE_SAVE_SYSTEM`
- The new `DEMO_WORKFLOW_INSTRUCTIONS` tells the agent the step-by-step
  workflow (like `RESEARCH_WORKFLOW_INSTRUCTIONS` in deep_research)

### Session 3: `service.py` — Replace coordinator with deep agent invocation

**Changes**:
- Remove the entire 11-phase coordinator loop (~400 lines)
- Remove `CheckpointManager` class (~100 lines) — MySQL handles checkpointing
- Replace `run_demo()` with ~30 lines matching deep_research pattern:
  ```python
  async def run_demo(req):
      thread_id = req.thread_id or uuid.uuid4()
      agent = get_deep_agent()
      config = {"configurable": {"thread_id": thread_id}}
      result = await agent.ainvoke({"messages": [HumanMessage(content=req.prompt)]}, config)
      return _extract_response(result, req)
  ```
- Add extraction helpers:
  - `_extract_title(messages)` — from write_todos or first AI message
  - `_extract_slug(title)` — same as current `_make_slug()`
  - `_extract_html_path(messages)` — from save_demo tool result
  - `_extract_metadata(messages)` — from save_demo tool result
  - `_extract_build_step(messages)` — track progress from tool call sequence
- Keep `get_deep_agent()` — it already exists and is correct
- Keep `_build_research_subagent()` — it already exists and is correct
- Remove `DemoState` dependency (no longer needed — agent carries state in messages)

### Session 4: `router.py` — Update for streaming + checkpoint endpoints

**Changes**:
- `/run` — unchanged (calls `run_demo(req)` which now uses deep agent)
- `/run/stream` — switch from `_run_demo_with_events()` to
  `agent.astream()` for true real-time agent events
- `/jobs/{thread_id}/checkpoint` — use MySQL checkpointer to check
  if a thread has saved state (query the checkpoint table)
- `/jobs/{thread_id}/resume` — re-invoke with same thread_id
  (MySQL checkpointer auto-resumes from last state)
- `/jobs/{thread_id}/cancel` — best-effort (same as before)
- All other endpoints (`/`, `/search`, `/{slug}`, `/{slug}/html`) — unchanged

### Session 5: `state.py` + `schemas.py` — Simplify

**Changes**:
- Remove `state.py` entirely — DemoState is no longer needed
  (agent state is in LangGraph message history + MySQL)
- Simplify `schemas.py`:
  - Keep `DemoCreateRequest` (unchanged)
  - Keep `DemoCreateResponse` (unchanged)
  - Keep `DemoBuildError` (unchanged)
  - Keep `DemoCheckpointStatus` (unchanged)
  - Remove `DemoResumeResponse` (merge into DemoCreateResponse with status="resumed")
  - Keep `DemoStreamEvent` (unchanged — still needed for SSE)
  - Keep `DemoMetadata` (unchanged — used for metadata.json on disk)

### Session 6: `__init__.py` — Update re-exports

**Changes**:
- Remove `DemoState` re-export (file is deleted)
- Remove `CheckpointManager` re-export (MySQL handles it)
- Keep `ensure_checkpointer_tables` re-export
- Update module docstring

### Session 7: Integration verification

Verify existing hooks still work:
- **Siri**: `siri/service.py` → `POST /demos/run` with `{"title", "prompt"}` →
  returns `{"thread_id", "title", "slug", "status", "html_path", "metadata", "error"}`
  Siri expects this shape — no changes needed
- **OpenWebUI**: `openwebui_tools/harness_tools.py` → `create_demo()` →
  `POST /demos/run` → parses `title`, `slug`, `status`, `html_path`,
  `thread_id`, `error` from response — no changes needed
- **Listing/Search**: `GET /demos/` and `GET /demos/search` read from disk
  (`MEDIA_OUTPUT_DIR/demos/*/metadata.json`) — unchanged since `save_demo`
  still writes the same files

---

## Critical Implementation Details

### A. MySQL Checkpointer (shared with deep_research)
- Reuse `ensure_checkpointer_tables` and `get_checkpointer` from `deep_research/service.py`
  (already done in current code via re-import)
- The `AsyncMySaver` context manager quirk: `from_conn_string()` returns a
  context manager, must enter with `__aenter__()` (already handled in deep_research)

### B. Media Output Directory
- `save_demo` must ensure `MEDIA_OUTPUT_DIR/demos/` exists before writing
- If `MEDIA_OUTPUT_DIR` is `/data/media` and that path doesn't exist,
  we need to either: create it, or use a path that exists (e.g. check
  if `/data` exists, fallback to `~/.ai-harness/media`)
- The `__init__.py` re-exports `ensure_checkpointer_tables` which is called
  from `app.py` startup — this is where we should also ensure the media dir

### C. Tool Async/Sync Compatibility
- The `@tool` wrappers are sync functions but the impls are async
- Deep agents framework dispatches tools — need to ensure the tool
  wrappers properly await the async implementations
- Solution: use `@tool(infer_schema=True)` and have the wrapper call
  `asyncio.run(_xxx_impl(...))` for the sync path, OR convert tools to
  async and let the framework handle it

### D. Streaming with astream()
- `agent.astream()` yields intermediate agent states
- Map these to `DemoStreamEvent` events for SSE
- Each state transition (tool call, tool result, AI response) becomes an event

### E. Output File Guarantee
- The agent MUST call `save_demo` as the last step
- The system prompt workflow explicitly instructs this in step 10
- If the agent errors before save, MySQL checkpoint allows resume

---

## Files Summary

| File | Action |
|------|--------|
| `tools.py` | Fix save_demo mkdir, fix @tool async, add write_file tool |
| `prompts.py` | Rewrite DEMO_WORKFLOW_INSTRUCTIONS, remove unused phase prompts |
| `service.py` | Replace 11-phase coordinator with agent.ainvoke(), add extractors |
| `router.py` | Update streaming to use astream(), simplify checkpoint/resume |
| `state.py` | DELETE — no longer needed |
| `schemas.py` | Simplify — remove DemoResumeResponse |
| `__init__.py` | Update re-exports, update docstring |
| `README.md` | Update after implementation is complete |
