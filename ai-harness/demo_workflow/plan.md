# Demo Workflow Migration to Deep Agents — Implementation Plan

> **Goal**: Replace the custom workflow engine + Celery architecture with the
> proven `deepagents` framework (same pattern as deep_research). The LLM
> orchestrator decides what to do at each step instead of following hard-coded
> stage transitions through Celery tasks and JSON file state.

---

## Part A — The Queue Question: Direct Invocation, No Celery

**Decision: Remove Celery. Use direct deep agents invocation. Offer sync + streaming endpoints.**

### Rationale

The current Celery + workflow engine created a slew of problems:
- Race conditions in state persistence (JSON files written/read across processes)
- Timeout handling (threading hacks for KB lookup, hard deadlines)
- Auto-dispatch failures (next step not starting, orphaned pending steps)
- Complex error handling (skip remaining steps, mark terminal)
- Hard to debug (task state in MySQL, state in JSON files, Celery logs)
- The 60s threading timeout for KB lookup was a hack born from Celery constraints

With deep agents, the entire pipeline runs in a single `ainvoke()` call. The
agent decides what to do next based on its system prompt and available tools.
State flows naturally through LangGraph's message history, checkpointed in MySQL.

### What about callers waiting 2-5 minutes?

| Caller | Solution |
|---|---|
| **OpenWebUI** | Use the new `/run/stream` SSE endpoint. OpenWebUI can stream agent progress live. |
| **Siri** | Use `asyncio.create_task()` to fire-and-forget. Siri responds immediately that the demo is being built. Same as deep_research. |
| **Direct API** | POST `/run` waits synchronously. Client gets result when done. If too slow, use `/run/stream`. |

This is exactly what deep_research does and it works fine.

---

## Part B — Architecture: Deep Agents Mapping

The 8-stage pipeline maps to deep agents as follows:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR AGENT                             │
│                                                                     │
│  System Prompt: 8-phase demo creation workflow                      │
│                                                                     │
│  Own Tools:                                                         │
│    • write_todos          — plan/manage the pipeline                 │
│    • write_file / read_file — intermediate artifacts (specs, HTML)   │
│    • think                — reflection between phases                │
│    • generate_html        — generate/transform HTML from spec+step   │
│    • validate_html        — validate HTML against acceptance criteria│
│    • fix_html             — fix validation issues in HTML            │
│    • critique_demo        — full-pass quality review                 │
│    • save_demo            — embed notes, write final HTML + metadata │
│                                                                     │
│  Sub-Agents:                                                        │
│    • research-agent       — search_and_crawl + think (from deep_research)│
│      Used for: KB lookup + web research (phases 2-3)                │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase mapping (old stages → agent behavior)

| Old Stage | New Agent Behavior | Mechanism |
|---|---|---|
| 1. Parse Request | Orchestrator uses structured output from prompt | Direct LLM call via system prompt guidance |
| 2. KB Lookup | Orchestrator delegates to research-agent | `task()` to sub-agent, then reads findings |
| 3. Web Research | Orchestrator delegates to research-agent | `task()` to sub-agent with specific queries |
| 4. Requirements & Design | Orchestrator writes design spec via `write_file` | Direct tool call, writes to `/design_spec.md` |
| 5. Build Plan | Orchestrator writes build plan via `write_file` | Direct tool call, writes to `/build_plan.md` |
| 6. Build Loop | Orchestrator iterates: generate → validate → fix | `generate_html`, `validate_html`, `fix_html` tools |
| 7. Polish | Orchestrator critiques then fixes | `critique_demo` + `fix_html` tools |
| 8. Save Final | Orchestrator saves everything | `save_demo` tool writes to disk |

### Key difference from old approach

The old approach hard-coded each stage as a Celery task with JSON state files.
The new approach lets the LLM follow its instructions and call tools as needed.
The `write_file` tool acts as implicit state — the agent reads/writes files
between phases, similar to how deep_research uses `/final_report.md`.

---

## Part C — File Structure (After Migration)

```
demo_workflow/
  __init__.py              ← module docstring + checkpointer init
  schemas.py               ← DemoCreateRequest, DemoCreateResponse, DemoMetadata
  prompts.py               ← Orchestrator system prompt + research sub-agent prompt
  tools.py                 ← generate_html, validate_html, fix_html,
                           critique_demo, save_demo
  service.py               ← Agent factory + run_demo() + extraction helpers
  router.py                ← FastAPI router: /run, /run/stream, /jobs,
                           /jobs/{id}, /jobs/{id}/cancel, /, /search,
                           /{slug}, /{slug}/html

  plan.md                  ← This file (implementation plan)
  README.md                ← Updated documentation
```

**Files to DELETE** (no longer needed):
- `tasks.py` — Celery tasks (replaced by direct agent invocation)
- `workflows/` — NOT deleted (still used by market_research), but demo_workflow
  no longer depends on it. The router's `_ensure_workflow()` and step dispatch
  code goes away.

**Files to UPDATE** in other modules:
- `app.py` — Remove `register_demo_tasks()`, add `ensure_checkpointer_tables()` call
- `openwebui_tools/harness_tools.py` — Update `create_demo()` to use `/run` or `/run/stream`
- `siri/service.py` — Update to use sync `/run` with `asyncio.create_task()` fire-and-forget

---

## Part D — Implementation Plan (Multiple Chat Sessions)

Implement in this order. Each part is self-contained and testable.

### Session 1: Core Agent Framework + Research Sub-Agent

**Goal**: Get the agent factory working with MySQL checkpointing and the
research sub-agent. Verify it can run a simple demo creation that at least
parses the request and does research.

**Files to create/rewrite**:
1. `service.py` (new) — Agent factory pattern, copy structure from deep_research:
   - `ensure_checkpointer_tables()` (same MySQL init as deep_research)
   - `get_deep_agent()` — creates orchestrator with sub-agents + tools
   - `run_demo()` — main entrypoint, ainvoke → extract result
   - `_extract_html()`, `_extract_metadata()` — parse agent output

2. `prompts.py` (new) — Two prompt blocks:
   - `DEMO_WORKFLOW_INSTRUCTIONS` — the full 8-phase workflow prompt for the
     orchestrator. Describes the full pipeline, file conventions, and what to
     produce at each phase. Includes build loop guidance (generate→validate→fix).
   - `RESEARCHER_INSTRUCTIONS` — system prompt for research sub-agent. Can
     adapt from deep_research's researcher with adjustments for demo research
     (competitor patterns, UX conventions, feature recommendations).

3. `schemas.py` (update) — Keep `DemoCreateRequest`, `DemoCreateResponse`,
   `DemoMetadata`. Remove all stage-specific Pydantic models (DemoBrief,
   KbInsights, WebInsights, RequirementsAndDesignSpec, BuildPlan, BuildStep,
   BuildStepResult, PolishResult, FinalSaveResult, DemoPipelineState) since
   the agent handles structure internally via its message history.

4. `__init__.py` (update) — Just import and expose `ensure_checkpointer_tables`.

5. `app.py` (update) — Add `from demo_workflow.service import ensure_checkpointer_tables`,
   add to startup event. Remove `register_demo_tasks()`.

**Reusing from deep_research**:
- The `search_and_crawl` tool can be shared (import from deep_research.tools)
   or re-created with the same implementation
- The `think_tool` can be shared or re-created
- The MySQL checkpointer init is identical

**Acceptance criteria**:
- `POST /run` with a simple demo request returns a valid response
- Research sub-agent successfully searches and returns findings
- MySQL checkpoint tables work (no errors on startup)
- Agent produces a `/demo_brief.md` file via write_file

### Session 2: Build Tools (Generate, Validate, Fix HTML)

**Goal**: Add the three core build tools so the orchestrator can iteratively
build the demo HTML.

**Files to create/rewrite**:
1. `tools.py` (new) — Three LangChain `@tool` functions:

   - `generate_html(spec: str, step_description: str, current_html: str) -> str`
     Takes the design spec and a build step description, plus current HTML,
     and generates the complete updated HTML. The tool calls LiteLLM with
     appropriate system prompt and returns the HTML.

   - `validate_html(acceptance_criteria: str, html: str) -> str`
     Validates HTML against acceptance criteria. Calls LiteLLM with validator
     prompt. Returns pass/fail with issues.

   - `fix_html(issues: str, html: str) -> str`
     Takes issues from validation and current HTML, fixes them. Calls LiteLLM
     with fix prompt. Returns corrected HTML.

   Each tool function is essentially a wrapper around `_call_llm()` with a
   specific system prompt. This keeps the tool contract simple (string I/O).

2. `prompts.py` (update) — Add build-related prompt templates that the
   tools will use:
   - `BUILD_GENERATE_SYSTEM` — System prompt for HTML generation
   - `BUILD_VALIDATE_SYSTEM` — System prompt for validation
   - `BUILD_FIX_SYSTEM` — System prompt for fixes

3. `service.py` (update) — Register the new tools on the orchestrator agent.

**Acceptance criteria**:
- Agent can call generate_html and get valid HTML back
- Agent can call validate_html and get pass/fail with issues
- Agent can call fix_html and get corrected HTML
- Build loop works: generate → validate → (fix → validate) → done

### Session 3: Polish + Save + Router Rewrite

**Goal**: Complete the pipeline with critique/save tools and rewrite the router.

**Files to create/rewrite**:

1. `tools.py` (update) — Add two more tools:

   - `critique_demo(design_spec: str, html: str) -> str`
     Full-pass quality review. Returns score (1-10) and prioritized issues.

   - `save_demo(title: str, html: str, design_spec: str, notes: str) -> str`
     Embeds notes as HTML comments, writes final_demo.html to disk,
     writes metadata.json. Returns local_url and public_url.

2. `router.py` (rewrite) — Pattern after deep_research/router.py:

   ```
   POST /run                    — Sync demo creation (DemoCreateRequest → DemoCreateResponse)
   POST /run/stream             — SSE streaming (same as deep_research)
   GET  /jobs                   — List recent demo jobs (from MySQL checkpoints)
   GET  /jobs/{thread_id}       — Get job status + output
   POST /jobs/{thread_id}/cancel — Cancel (mark thread as done)
   GET  /                       — List all demos (scan metadata.json files)
   GET  /search                 — Search demos
   GET  /{slug}                 — Get demo metadata
   GET  /{slug}/html            — Serve final HTML
   ```

   The `/run` endpoint calls `run_demo(req)` and extracts HTML + metadata.
   The `/jobs` endpoints query MySQL checkpoint data (or scan demo directories).

3. `service.py` (update) — Add extraction functions:
   - `_extract_final_html(messages)` — Find write_file targeting final_demo.html
   - `_extract_demo_metadata(messages)` — Extract metadata from save_demo output
   - Update `run_demo()` to return structured response with answer, html_path, metadata

**Acceptance criteria**:
- Full pipeline runs end-to-end: request → research → design → build → polish → save
- Final HTML file exists on disk with embedded notes
- metadata.json written correctly
- `/run` returns proper response with URL to the demo
- `/run/stream` works for SSE
- Discovery endpoints (/, /search, /{slug}, /{slug}/html) all work

### Session 4: Siri + OpenWebUI Integration + Cleanup

**Goal**: Wire up the callers and remove dead code.

**Files to update**:

1. `openwebui_tools/harness_tools.py`:
   - `create_demo()`: POST to `/demos/run` (sync) or use streaming.
     Since OpenWebUI can handle streaming, prefer `/run/stream` for live progress.
   - `list_demos()`: Unchanged (reads metadata.json from disk)
   - `find_demo()`: Unchanged (reads metadata.json from disk)

2. `siri/service.py`:
   - `_handle_create_demo_workflow()`: Use `asyncio.create_task()` to fire
     the request to `/demos/run` without blocking. Same pattern as deep_research.
     Siri responds immediately: "I've started building your demo..."

3. `app.py`:
   - Confirm demo_workflow router is mounted at `/demos`
   - Confirm `ensure_checkpointer_tables()` is in startup
   - Remove `register_demo_tasks()`

4. Delete `demo_workflow/tasks.py`

5. Update `demo_workflow/__init__.py` — Remove tasks import

6. `README.md` — Rewrite following deep_research/README.md pattern

**Acceptance criteria**:
- OpenWebUI `create_demo` tool works and returns demo URL
- Siri "build a demo of X" works and responds immediately
- `list_demos` and `find_demo` still work
- No imports of deleted `tasks.py`
- Clean startup with no errors

---

## Part E — Design Decisions & Tradeoffs

### 1. File-based intermediate state (write_file) vs in-memory state

**Decision**: Use `write_file` tool for intermediate artifacts (design spec,
build plan, HTML). The orchestrator reads/writes files as it progresses.

This mirrors deep_research's `/final_report.md` and `/research_request.md`.
The agent can `write_file` then `read_file` between phases. This is natural
for LLM agents and avoids complex state models.

**Tradeoff**: Slightly more tokens (reading files) but much simpler code.
No more DemoPipelineState, save_state(), load_state() functions.

### 2. Build loop: tool vs sub-agent

**Decision**: Keep build loop (generate → validate → fix) as direct tools on
the orchestrator, NOT a sub-agent.

The build loop is a tight iterative cycle. Making it a sub-agent would add
overhead of task() delegation and context switching. As tools, the
orchestrator stays in control and can see each iteration's results directly.

**Tradeoff**: The orchestrator handles more tool calls directly, but this is
fine since it already manages the workflow.

### 3. Research sub-agent: shared or separate?

**Decision**: The research sub-agent uses the same `search_and_crawl` and
`think_tool` as deep_research. We import them from deep_research.tools or
duplicating them. Since both modules are in the same harness, importing is clean.

The sub-agent's system prompt is customized for demo research (competitor
patterns, UX conventions) but the tools are identical.

### 4. No Celery = what about timeouts?

**Decision**: Let the HTTP client timeout handle it. The `/run` endpoint has
a generous timeout (5 min). If the agent takes longer, the client gets a
timeout error. This is acceptable for an async operation — use streaming
for better UX.

For Siri specifically, `asyncio.create_task()` means the server handles the
full execution in the background — no client-side timeout at all.

### 5. What about the workflow engine?

**Decision**: Keep the workflow engine (`workflows/` module) intact. Market
research still uses it. Demo workflow just stops using it.

### 6. KB lookup (Qdrant) integration

**Decision**: Add a `kb_lookup` tool that calls `family_kb.search_kb()`
directly. The orchestrator can call this in phase 2. Simple string I/O tool
like the build tools.

---

## Part F — Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent doesn't follow the 8-phase workflow | Strong system prompt with explicit numbered phases and file conventions. The deep_research agent follows its workflow reliably. |
| Build loop gets stuck in infinite fix cycle | Tool includes retry counter. System prompt caps at 2 retries per step. |
| HTML too large for context window | generate_html/validate_html tools use truncation (last 8000-12000 chars) like the current implementation. |
| Agent skips phases | System prompt uses write_todos pattern — agent must mark phases complete via file writes before proceeding. |
| Siri/OpenWebUI break during migration | Implement in phases. Keep old router endpoints working until new ones are verified. |
| KB lookup slow (embedding download) | kb_lookup tool has a 30s timeout. Falls back gracefully with "KB unavailable" message. |

---

## Part G — Testing Strategy

| What | How |
|---|---|
| Agent initialization | `POST /run` with simple request, verify no errors |
| Research sub-agent | Check that search_and_crawl returns results |
| Build loop | Verify HTML improves across iterations |
| Final output | Open final_demo.html in browser, verify functionality |
| Streaming | Use `curl` on `/run/stream`, verify SSE events |
| Discovery | `GET /demos/` returns list, `GET /demos/{slug}/html` serves HTML |
| Siri | "build a demo of X" responds immediately, demo appears in list later |
| OpenWebUI | `create_demo` tool works, `list_demos` shows completed demos |

No unit tests initially (same as deep_research and market_research).
Integration via HTTP serves as testing.
