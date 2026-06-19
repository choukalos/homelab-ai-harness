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
          ↳  write_file / read_file → deepagents built-in (artifact I/O)
          ↳  verify_interactivity → LLM call for static JS analysis
          ↳  critique_demo     → LLM call for quality review
          ↳  fix_html          → LLM call to fix issues
          ↳  save_demo         → write HTML + metadata.json to disk
          ↳  task() sub-agent  → researcher (search_and_crawl + think_tool)
        MySQL Checkpointing (AsyncMySaver) — auto-persists after each step
```

### Workflow the Agent Follows (via system prompt)

```
1. PLAN: Parse the prompt, create /demo_brief.md via write_file
2. KB LOOKUP: Call kb_lookup() to check for prior demos, user preferences
3. RESEARCH: Delegate to research sub-agent for domain/competitor analysis
4. BUILD: Synthesize brief + KB + research → write complete demo HTML
   to /final_demo.html via write_file (single pass, all features included)
5. VERIFY & SAVE:
   a. read_file → verify_interactivity() → fix_html() if score < 7
   b. critique_demo() → fix_html() if score < 8
   c. read_file → save_demo(title, html, metadata) → final files on disk
```

The agent uses `write_file` for large artifacts so the full HTML never
accumulates in the conversation history, keeping the workflow within a
70K context window.

The deep agents framework handles:
- Context window management (compresses history, offloads large tool results)
- MySQL checkpointing (resume after interruption via thread_id)
- Sub-agent isolation (researcher has separate context)

### Tools Used

| Tool | Source | Purpose |
|------|--------|---------|
| `kb_lookup` | `demo_workflow/tools.py` | Search family_kb for prior info |
| `search_and_crawl` | `deep_research/tools.py` | SearXNG + Crawl4AI web research |
| `think_tool` | `deep_research/tools.py` | Strategic reflection between steps |
| `write_file` / `read_file` | deepagents framework (built-in) | Save/load artifacts to avoid HTML in args |
| `verify_interactivity` | `demo_workflow/tools.py` | Static JS analysis, score 1-10 |
| `fix_html` | `demo_workflow/tools.py` | LLM call to fix issues in HTML |
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

### Session 2: `prompts.py` — Rewrite for single-pass workflow (COMPLETED)

**Changes**:
- `DEMO_WORKFLOW_INSTRUCTIONS` rewritten: 11 steps → 5 steps (~3K chars)
- `RESEARCHER_INSTRUCTIONS` simplified
- Single `BUILD_GENERATE_SYSTEM` replaces 3 progressive build prompts
- Removed `BUILD_STRUCTURE_SYSTEM`, `BUILD_FEATURES_SYSTEM`, `BUILD_POLISH_SYSTEM`, `MOCK_BEHAVIOR_LEVEL3_SYSTEM`
- `VERIFY_INTERACTIVITY_SYSTEM` and `CRITIQUE_SYSTEM` simplified
- Total `prompts.py` reduced from ~35K chars to ~9K chars (~75% reduction)

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

## Known Issues

### 1. Checkpointer Not Initialized (FIXED)
**Problem:** `demo_workflow` had its own separate checkpointer globals that were never initialized at startup (only `deep_research` was initialized in `app.py`).

**Fix:** Modified `app.py` to import and call `ensure_checkpointer_tables` from `demo_workflow.service` at startup.

**Status:** ✅ Fixed

### 2. Context Window Overflow (FIXED)
**Problem:** `matrix-coder` (qwen3.6-27b via vLLM) has a 70K context window limit. The multi-step HTML generation workflow (11 phases with system prompt + HTML tool results + research findings) accumulated ~70K+ tokens and triggered `ContextWindowExceededError`.

**Fix applied:**
1. **Trimmed system prompt** — `DEMO_WORKFLOW_INSTRUCTIONS` reduced from ~5K chars to ~3K chars (11 steps → 5 steps)
2. **Single-pass build** — Instead of 3 `generate_html` passes each passing full HTML as a tool argument, the agent now writes HTML to `/final_demo.html` via `write_file` (tiny "saved" result) and reads it back via `read_file` for verification, avoiding HTML accumulation in the conversation history.
3. **Simplified all prompts** — `prompts.py` reduced from ~35K chars to ~9K chars total (~75% reduction). Removed `BUILD_STRUCTURE_SYSTEM`, `BUILD_FEATURES_SYSTEM`, `BUILD_POLISH_SYSTEM`, `MOCK_BEHAVIOR_LEVEL3_SYSTEM`.

**Status:** ✅ Fixed — workflow now fits comfortably within 70K context window.

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
- The system prompt workflow explicitly instructs this in step 5
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
