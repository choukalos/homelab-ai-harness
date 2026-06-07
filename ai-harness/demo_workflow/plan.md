# One-Page Clickable Demo Workflow — Plan

> A multi-stage LLM-driven pipeline that researches, designs, builds, validates,
> and saves high-quality single-file HTML demos. Built on the same workflow engine
> pattern as the market research pipeline.

---

## Overview

Given a user prompt (e.g. "Build a demo for a pet adoption app with cat profiles
and a adoption flow"), the workflow:

1. **Parses** the user request into a structured demo brief
2. **Checks the Family KB** for prior relevant material
3. **Searches the web** for competitive/inspirational insights
4. **Synthesizes** requirements + a visual design spec
5. **Produces a build plan** (numbered implementation steps)
6. **Iterates through each build step** — generate code, validate, save
7. **Polishes** with a full-pass self-critique
8. **Embrides notes** and saves the final HTML + writes metadata for discovery

End result: a single self-contained HTML file in `/data/media/demos/` with
embedded HTML-comment notes, plus a `.json` metadata sibling that enables
discovery via Siri and OpenWebUI tools.

---

## Architecture

```
POST /demos/create
         │
         ▼
┌───────────────────────────────────────────────────────┐
│              Workflow Engine                             │
│  (workflows/ — MySQL-backed DAG state machine)            │
│                                                           │
│  workflow_runs  ← run state, status, metadata              │
│  workflow_steps ← per-step status, output, errors          │
│  workflows      ← reusable workflow definitions            │
└─────┬───────────────────────┬─────────────────────────┘
      │ dispatches Celery tasks
      ▼
┌────────────────────────────────────────────────────────┐
│           Celery Worker Pool                             │
│                                                         │
│  demo_workflow.run_stage(stage=N, run_id)               │
│       │                                                │
│       ├──► Stage 1:   Parse Request                     │
│       │                                                │
│       ├──► Stage 2:   KB Lookup                         │
│       │     └─► family_kb.search_kb()                   │
│       │                                                │
│       ├──► Stage 3:   Web Research                      │
│       │     ├─► SearXNG (web search)                    │
│       │     └─► LLM summarizes findings                 │
│       │                                                │
│       ├──► Stage 4:   Requirements & Design Spec        │
│       │     └─► LLM synthesizes brief + KB + web        │
│       │         └─► requirements list, design spec       │
│       │                                                │
│       ├──► Stage 5:   Build Plan                        │
│       │     └─► LLM produces numbered build steps        │
│       │                                                │
│       ├──► Stages 6-N:  Build Loop (dynamic steps)      │
│       │     For each build plan step:                   │
│       │     ├─► LLM generates the HTML incrementally    │
│       │     ├─► LLM validates the step against spec     │
│       │     └─► Save intermediate HTML to disk          │
│       │                                                │
│       ├──► Stage N+1:  Polish & Self-Critique           │
│       │     └─► LLM full-pass critique + fix pass       │
│       │                                                │
│       └──► Stage N+2:  Embed Notes & Save Final         │
│             ├─► Inject requirements/design as comments  │
│             ├─► Save final HTML to /data/media/demos/   │
│             └─► Write metadata JSON for discovery       │
└────────────────────────────────────────────────────────┘
         │
         ▼
   /data/media/demos/{demo_slug}/
     ├── build/
     │     ├── step1.html
     │     ├── step2.html
     │     └── ...
     ├── final_demo.html
     └── metadata.json
```

---

## Pipeline Stages in Detail

### Stage 1 — Parse Request
The user sends `{"title": "...", "prompt": "...", "model": "...?"}`.
The service extracts/structures the request:
- Title (auto-generated if not provided from prompt)
- Description (refined from prompt)
- Target audience (inferred or explicitly stated)
- Key features / screens requested
- Any constraints or style hints

Output: `DemoBrief` stored in pipeline state.

### Stage 2 — KB Lookup
Query the Family Knowledge Base (Qdrant) for any prior material
relevant to the demo topic. This could be:
- Prior market research on the domain
- Family KB notes about the product/company
- Previously saved documents in related categories

The LLM synthesizes any findings into a brief insight summary.
If nothing relevant is found, this is fine — the pipeline continues.

Output: `KbInsights` (list of relevant findings or empty).

### Stage 3 — Web Research
Generate 3-4 focused web search queries targeting:
- Similar products / competitors in the space
- Current design trends for this type of app
- Key features users expect in this category

Execute each query against SearXNG, then have the LLM
summarize the top findings into actionable insights:
- What do competitors do well?
- What UX patterns are common?
- What features should we include or differentiate?

Output: `WebInsights` (structured findings).

### Stage 4 — Requirements & Design Spec
Synthesize Stages 1-3 into two deliverables:

**A. Requirements List** — Detailed, numbered list including:
- Screens / views needed (e.g. "Landing page", "Product list", "Detail view")
- Interactions (e.g. "Clicking a card opens detail view")
- Data models (placeholder data to use)
- Navigation flow between screens

**B. Visual Design Spec** — Guidance for the HTML builder:
- Color palette / theme
- Typography hints
- Layout approach (card-based, sidebar-nav, bottom-tab, etc.)
- Any iconography/visual treatment suggestions (SVG/emoji/unicode only — no external assets)

Output: `RequirementsAndDesignSpec` stored in state.

### Stage 5 — Build Plan
The LLM reads the requirements + design spec and produces a
numbered build plan. Each step is an atomic, testable unit:

Example build plan:
1. Create base HTML with nav structure and CSS reset
2. Build landing/hero screen
3. Build product listing screen with card grid
4. Build product detail screen
5. Build cart/checkout flow
6. Wire up click handlers and screen transitions
7. Add animations and polish CSS

Each step includes:
- Step title
- What to build (description)
- What "done" looks like (acceptance criteria)
- Dependencies on prior steps

Output: `BuildPlan` (list of build steps).

### Stages 6-N — Build Loop (Dynamic Steps)

For each step in the build plan, the pipeline:

1. **Generate**: Feed current HTML + design spec + this build step
   to the LLM. The LLM returns the updated complete HTML.

2. **Validate**: Feed the updated HTML + the step's acceptance
   criteria to the LLM in a separate validation call. The LLM
   reports pass/fail with any issues found.

3. **Retry on failure**: If validation fails, feed the HTML +
   issues back to the LLM for a fix pass (max 2 retries).

4. **Save**: Write the current HTML to `build/step{N}.html` so
   the user can inspect intermediate results.

Each build step is registered as a dynamic workflow step in the
workflow engine (created after Stage 5 completes).

### Stage N+1 — Polish & Self-Critique

After all build steps complete, run the assembled HTML through
an LLM critique pass. The LLM evaluates:
- Overall flow and usability
- Mobile responsiveness
- Visual consistency with design spec
- Missing interactions or broken state transitions
- Accessibility basics (alt text for SVGs, contrast)
- Performance (no unnecessary JS, clean code)

The LLM returns a list of issues. A fix pass is run to address
the top issues (1 fix pass only to avoid over-iteration).

### Stage N+2 — Embed Notes & Save Final

**Inject HTML comments** at the top of the final file:
```html
<!--
  DEMO NOTES
  Title: ...
  Created: 2025-06-06
  Requirements: ...
  Build Steps: ...
  Design Decisions: ...
  Open Questions: ...
-->
```

**Save final HTML** to:
```
/data/media/demos/{demo_slug}/final_demo.html
```

**Write metadata JSON** to:
```
/data/media/demos/{demo_slug}/metadata.json
```

Metadata schema:
```json
{
  "title": "Pet Adoption App Demo",
  "slug": "pet-adoption-app-20250606",
  "description": "Interactive demo of a pet adoption app...",
  "tags": ["pet", "adoption", "mobile", "ecommerce"],
  "created_at": "2025-06-06T...",
  "screens": ["Landing", "Pet Listing", "Pet Detail", "Adoption Flow"],
  "local_url": "/media/files/demos/pet-adoption-app-20250606/final_demo.html",
  "public_url": "https://siri.choukalos.com/media/files/demos/...",
  "requirements_summary": "...",
  "design_decisions": "...",
  "open_questions": ["..."]
}
```

---

## File Map

```
demo_workflow/
  __init__.py              ← register() — creates workflow def at startup
  prompts.py               ← LLM prompt templates per stage
  schemas.py               ← Pydantic models (DemoBrief, BuildPlan, etc.)
  service.py               ← Stage implementations + pipeline orchestration
  router.py                ← FastAPI endpoints at /demos
  tasks.py                 ← Celery task (demo_workflow.run_stage)
  plan.md                  ← ← YOU ARE HERE (this file)
```

Integration points:
```
app.py                     ← register demo_workflow router + tasks
openwebui_tools/harness_tools.py  ← ADD list_demos(), find_demo(), create_demo_workflow()
siri/service.py            ← ADD demo listing/discovery intents
```

---

## APIs

### POST /demos/create

Start a new demo workflow.

```json
{
  "title": "Pet Adoption App",
  "prompt": "Build a one-page clickable demo for a mobile pet adoption app...",
  "model": ""                        // optional, override default model
}
```

Response:
```json
{
  "run_id": "<uuid>",
  "workflow_id": "<uuid>",
  "title": "Pet Adoption App",
  "status": "pending",
  "steps_count": 3                  // initial count (before dynamic steps)
}
```

### GET /demos/jobs

List recent demo creation jobs.

```
GET /demos/jobs?status=success&limit=20
```

### GET /demos/jobs/{run_id}

Get the full run state including all step outputs.

### POST /demos/jobs/{run_id}/cancel

Cancel a running demo creation job.

### GET /demos

**List all demos** (queries the metadata index, not the workflow engine).

```
GET /demos?tag=pet&limit=20
```

Response:
```json
{
  "demos": [
    {
      "title": "Pet Adoption App",
      "slug": "pet-adoption-app-20250606",
      "description": "...",
      "tags": ["pet", "adoption"],
      "created_at": "2025-06-06T...",
      "local_url": "/media/files/demos/...",
      "public_url": "https://..."
    }
  ]
}
```

### GET /demos/search

**Search/filter demos** by query text (matches title, description, tags).

```
GET /demos/search?q=pet+adoption&local_urls=true
```

Returns matching demos with appropriate URLs.

### GET /demos/{slug}

Get a single demo's metadata.

### GET /demos/{slug}/html

Serve the final HTML file for a demo.

---

## OpenWebUI Tool Additions

### `create_demo(title, prompt, model)`
Replaces `create_pm_demo` (or coexists). Triggers the full workflow
instead of a single LLM call. Returns run_id and a link that the
user can follow once complete.

### `list_demos(tags="", limit=20)`
List all created demos with titles, descriptions, and local URLs.

### `find_demo(query)`
Search demos by natural language query. Returns matches with
descriptions and local URLs.

---

## Siri Integration

### New Intent Detection

Add to `_detect_intent()`:
```python
if "list demo" in text or "show demo" in text or "what demo" in text:
    return "list_demos"
if "find demo" in text or "demo about" in text or "demo for" in text:
    return "find_demo"
```

### Response Behavior

- **"list demos"** → Returns list of demos with PUBLIC URLs
- **"find me a demo about pets"** → Searches by query, returns
  best matches with PUBLIC URLs
- **"create a demo of..."** → Starts the workflow pipeline, returns
  run status (Siri cannot wait for long-running workflows, so it
  responds that the demo is being built and will be available shortly.
  The user can then ask "list demos" to find the completed one.)

---

## State Management

### DemoPipelineState (Pydantic model)

```python
class DemoPipelineState(BaseModel):
    run_id: str
    title: str
    prompt: str
    slug: str = ""                  # generated in stage 1
    demo_brief: DemoBrief | None = None
    kb_insights: KbInsights | None = None
    web_insights: WebInsights | None = None
    requirements: RequirementsAndDesignSpec | None = None
    build_plan: BuildPlan | None = None
    current_html: str = ""          # carried across build steps
    build_step_results: list[dict] = []
    polish_result: dict | None = None
    open_questions: list[str] = []
```

State is persisted to disk between stages (same pattern as
market research: JSON files under `/data/media/demos/{slug}/`).

---

## Dynamic Step Registration

Since the build loop has a variable number of steps (determined at
runtime by the build plan in Stage 5), dynamic steps are registered
after Stage 5 completes:

1. Stages 1-5 and N+1, N+2 are defined statically in the workflow
2. After Stage 5, the build plan is read and N dynamic steps are
   injected into the workflow run
3. These dynamic steps depend on Stage 5 and are depended on by
   the Polish step (N+1)

This is handled in `service.py` after stage 5 completes by calling
the workflow engine to add new step rows.

---

## Output Directory Structure

```
/data/media/demos/
  └── {slug}/
      ├── build/
      │     ├── step1.html
      │     ├── step2.html
      │     └── ...
      ├── final_demo.html          ← the finished demo with embedded notes
      ├── metadata.json            ← discovery index entry
      └── state/
            ├── stage1_brief.json
            ├── stage2_kb.json
            ├── stage3_web.json
            ├── stage4_requirements.json
            ├── stage5_build_plan.json
            ├── stage_polish.json
            └── state_snapshot.json
```

---

## LLM Temperature Profile

| Stage | Temperature | Rationale |
|---|---|---|
| 1 — Parse Request | 0.2 | Deterministic extraction |
| 2 — KB synthesis | 0.2 | Deterministic summarization |
| 3 — Web research queries | 0.5 | Creative query generation |
| 3 — Web insights summary | 0.2 | Deterministic summarization |
| 4 — Requirements & Design | 0.4 | Creative but structured |
| 5 — Build Plan | 0.3 | Structured planning |
| 6-N — Build Generate | 0.4 | Creative code generation |
| 6-N — Build Validate | 0.1 | Very deterministic checking |
| 6-N — Build Fix | 0.3 | Corrective but guided |
| N+1 — Polish Critique | 0.2 | Deterministic evaluation |
| N+1 — Polish Fix | 0.3 | Creative fixes |

---

## Build Plan — Implementation Order

### Phase 1: Core Module Files

1. **schemas.py** — All Pydantic models for state, requests, responses
2. **prompts.py** — All LLM prompt templates (one per stage + build/validation)
3. **service.py** — Stage 1-5, N+1, N+2 implementations + state I/O helpers
4. **router.py** — FastAPI endpoints
5. **tasks.py** — Celery task + dynamic step registration
6. **__init__.py** — Task registration

### Phase 2: Integration

7. **app.py** — Register the new router and tasks
8. **openwebui_tools/harness_tools.py** — Add `create_demo()`, `list_demos()`, `find_demo()`
9. **siri/service.py** — Add demo listing/discovery intents
10. **siri/schemas.py** — Update if needed for new intent

### Phase 3: Documentation

11. **README.md** — Full documentation (follows market_research/README.md pattern)
12. Update **plan.md** with any deviations from plan

---

## Testing Strategy

| What | How |
|---|---|
| Schema models | Pydantic validation catches most issues at runtime |
| Stage functions | Manual testing via `POST /demos/create` and checking run state |
| Build loop | Verify `build/step*.html` files are created and improving |
| Final HTML | Open in browser, verify functionality |
| Discovery | `GET /demos` and `GET /demos/search?q=...` |
| Siri | Trigger intents via existing Siri integration |
| OpenWebUI tools | Test new tool functions in OpenWebUI workspace |

No unit tests initially — the market research pipeline also doesn't have them
and the integration via HTTP serves as integration testing.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Build loop too many steps → very long run | Cap build plan at 8 steps. If LLM wants more, consolidate. |
| LLM produces broken HTML on retry | Validation step catches this. After 2 retries, mark step as done with note. |
| Final HTML too large for LLM context | Use incremental approach — LLM always sees the full HTML but we set max_tokens high. If still too large, consider prompting LLM to only output the diff and we merge. |
| Celery worker timeout | Set generous timeouts for build stages (180s) and research stages (120s). |
| Siri waits for long-running workflow | Siri responds immediately that demo is being built. User follows up with "list demos". |

---

## Configuration

| Environment Variable | Purpose | Default |
|---|---|---|
| `HARNESS_MODEL` | LLM model for all LLM calls | `gemma-moe` |
| `MEDIA_OUTPUT_DIR` | Base for generated media | `/data/media` |
| `SEARXNG_BASE_URL` | Web search endpoint | `http://searxng:8080` |

No new env vars needed — all reuse existing configuration.
