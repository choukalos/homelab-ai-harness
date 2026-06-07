# One-Page Clickable Demo Workflow

An automated, LLM-driven pipeline that researches, designs, builds, validates,
and saves high-quality single-file HTML demos. Built on the same workflow
engine pattern as the market research pipeline.

## What It Does

Given a demo request (e.g. "Build a demo for a pet adoption app with cat
profiles and an adoption flow"), the workflow:

1. **Parses the request** — extracts a structured demo brief (title, audience,
   features, screens, style hints, constraints)
2. **Checks prior knowledge** — queries the Family Knowledge Base for any
   previous research or notes relevant to the demo topic
3. **Researches the web** — runs targeted searches via SearXNG to find
   competitor patterns, UX conventions, and feature recommendations
4. **Creates requirements + design spec** — synthesizes all research into a
   detailed requirements list and visual design spec (colors, typography,
   layout, interactions)
5. **Generates a build plan** — produces a numbered step-by-step implementation
   plan with acceptance criteria per step
6. **Builders loop step-by-step** — for each build step, generates HTML,
   validates it against acceptance criteria, retries fixes if needed (max 2),
   and saves intermediate results
7. **Polishes with self-critique** — runs the assembled HTML through a full-pass
   LLM critique, then executes one fix pass for the highest-priority issues
8. **Embeds notes & saves** — injects requirements/build notes as HTML comments,
   saves the final HTML, writes metadata for discovery

## Architecture

```
POST /demos/create
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│              Workflow                                        │
│  (workflows/ — MySQL-backed DAG state machine)               │
│                                                              │
│  1. Parse Request            → structured demo brief         │
│  2. KB Lookup               → prior knowledge                │
│  3. Web Research             → competitive insights           │
│  4. Requirements & Design   → specs + design guidance        │
│  5. Build Plan               → numbered build steps           │
│  6. Build Loop               → generate → validate → fix      │
│  7. Polish                  → critique + fix pass             │
│  8. Embed Notes & Save      → final HTML + metadata          │
└────────┬───────────────────────────────┬───────────────────┘
         │ dispatches Celery tasks
         ▼
┌────────────────────────────────────┐       │
│ Celery Worker Pool                 │       │
│                                    │       │
│ demo_workflow/run_stage(stage=N)   │       │
│                                    │       │
│ Stage 1-5, 7-8: LLM + helpers      │       │
│ Stage 6:      build loop            │       │
│  (generate + validate per step)     │       │
└───────┬─────────────────────┬───────┘       │
        │                     │               │
        ▼                     ▼               │
  /demos/pet-app-20250606/     Qdiant (KB)     │
    final_demo.html                 │           │
    metadata.json                   │           │
    build/step{N}.html              │           │
    state/{stage}.json             SearXNG      │
```

## Pipeline Stages

### Stage 1 — Parse Request
Extracts a structured demo brief from the user's free-text request. The LLM
identifies the target audience, key features, requested screens, style hints,
and constraints. A filesystem-safe slug is auto-generated from the title.

**Output:** `DemoBrief` with title, description, target_audience,
key_features, screens_requested, style_hints, constraints.

### Stage 2 — KB Lookup
Queries the Family Knowledge Base (Qdrant) for any prior material relevant to
the demo topic. The LLM synthesizes findings into actionable insights. If
nothing relevant is found, the stage passes through cleanly.

**Output:** `KbInsights` with has_prior_data flag, insight summary, and
key excerpts.

### Stage 3 — Web Research
Generates 3-4 focused web search queries targeting:
- Similar products and competitors
- Current design patterns for this product category
- Features users expect

Each query is executed against SearXNG. The LLM then summarizes all findings
into actionable insights: competitor patterns, UX conventions, feature
recommendations.

**Output:** `WebInsights` with queries used, source links, competitor patterns,
UX patterns, feature recommendations, and a summary.

### Stage 4 — Requirements & Design Spec
Synthesizes stages 1-3 into two deliverables:

**A. Requirements** — Detailed list including:
- Specific screens needed (expanded from initial request)
- Navigation flow between screens
- What placeholder data to use
- Specific interactions to implement

**B. Visual Design Spec** — Guidance for the HTML builder:
- Color palette with hex values
- Typography approach (system fonts only)
- Layout approach (card-based, sidebar, bottom-tab, etc.)
- Visual treatment (shadows, gradients, borders)

**Output:** `RequirementsAndDesignSpec` with requirements, screens,
navigation flow, interactions, color palette, typography, layout, visual
treatment, and design notes.

### Stage 5 — Build Plan
The LLM reads the requirements + design spec and produces a numbered build
plan. Each step is atomic with acceptance criteria:

Example progression:
1. Base HTML with nav structure, CSS reset, design tokens
2. Landing/hero screen
3. Product listing screen
4. Detail screen(s)
5. Interaction wiring (click handlers, transitions)
6. Polish (animations, responsive adjustments)

Capped at 8 steps maximum.

**Output:** `BuildPlan` with steps (numbered, titled, described, acceptance
criteria) and overall notes.

### Stage 6 — Build Loop
For each step in the build plan, the pipeline:

1. **Generates** — Feeds current HTML + design spec + step description to
   the LLM. LLM returns the complete updated HTML.
2. **Validates** — Feeds the HTML + acceptance criteria to a separate LLM
   validation call. Reports pass/fail with issues.
3. **Fixes if needed** — If validation fails, feeds HTML + issues back for
   a fix pass (max 2 retries).
4. **Saves** — Writes current HTML to `build/step{N}.html`.

Each build step is executed within a single Celery task (stage 6), tracked
in the workflow engine as one step that internally iterates the sub-steps.

**Output:** Per-step results with status, validation summary, retries used,
and any remaining issues.

### Stage 7 — Polish & Self-Critique
After all build steps complete, the assembled HTML runs through:

1. **Critique** — LLM evaluates the complete demo on: overall quality,
   navigation flow, visual consistency, mobile responsiveness, interactions,
   content quality, accessibility, and code quality. Returns an overall score
   (1-10) and prioritized list of issues.
2. **Fix pass** — One fix pass addressing the top 8 issues.

**Output:** `PolishResult` with critique text, issues found, overall score,
issues fixed.

### Stage 8 — Embed Notes & Save Final
1. **Generates notes** — LLM creates a build summary note covering:
   requirements, build approach, design decisions, open questions, demo tips
2. **Embeds as HTML comments** — Notes injected at the top of the final HTML
   file (invisible during presentation)
3. **Saves final HTML** — to `/data/media/demos/{slug}/final_demo.html`
4. **Writes metadata.json** — with title, description, tags, screens,
   creation date, local URL, public URL

**Output:** Final HTML file with embedded notes, metadata.json for discovery.

## How Pieces Fit Together

### Workflow Engine (`workflows/`)
The workflow engine tracks the full DAG with 8 steps, dependency chains,
and per-step status/output metadata. The demo pipeline registers its workflow
definition at FastAPI startup (same pattern as market research).

### Celery Tasks (`demo_workflow/tasks.py`)
A single dispatchable Celery task `demo_workflow.run_stage(stage=NAME, run_id)` handles
all stages. For stages 1-5, 7-8 it delegates to the corresponding stage function.
For stage 6 (build loop) it internally iterates all build steps with the
generate-validate-fix cycle.

State is persisted to disk between stages (not passed through Celery) because
HTML content can be large. Each stage reads accumulated state, mutates it,
and writes it back.

### LLM Integration (`core/llm.py`)
All LLM calls go through LiteLLM. Each stage uses different temperatures:

| Stage | Temperature | Rationale |
|---|---|---|
| 1 — Parse Request | 0.2 | Deterministic extraction |
| 2 — KB synthesis | 0.2 | Deterministic summarization |
| 3 — Web queries | 0.5 | Creative query generation |
| 3 — Web insights | 0.2 | Deterministic summarization |
| 4 — Requirements & Design | 0.4 | Creative but structured |
| 5 — Build Plan | 0.3 | Structured planning |
| 6 — Build Generate | 0.4 | Creative code generation |
| 6 — Build Validate | 0.1 | Deterministic checking |
| 6 — Build Fix | 0.3 | Corrective but guided |
| 7 — Polish Critique | 0.2 | Deterministic evaluation |
| 7 — Polish Fix | 0.3 | Creative fixes |
| 8 — Notes | 0.2 | Deterministic generation |

### External Dependencies
- **Family KB (Qdrant)** — Semantic search for prior knowledge (stage 2)
- **SearXNG** — Web search for competitive research (stage 3)
- **LiteLLM** — LLM proxy providing actual models (all stages)
- **MySQL** — Workflow state persistence

### Output Artifacts
All outputs are written to `/data/media/demos/{slug}/`:
- `build/step1.html`, `step2.html`, ... — Intermediate build results
- `state/stage_{N}.json` — Per-stage output data
- `state/state_snapshot.json` — Full accumulated state
- `final_demo.html` — The finished demo with embedded notes
- `metadata.json` — Discovery index entry

## APIs

### Start a Demo Job
```
POST /demos/create
Content-Type: application/json

{
  "title": "Pet Adoption App",
  "prompt": "Build a one-page clickable demo for a mobile pet adoption app...",
  "model": ""                // optional, override default model
}
```

Returns: `{ "run_id": "<uuid>", "workflow_id": "<uuid>",
"title": "Pet Adoption App", "status": "pending", "steps_count": 8 }`

### List Jobs
```
GET /demos/jobs?status=success&limit=20
```

Returns recent demo creation jobs with status, title, timestamps.

### Get Job Status + Full Output
```
GET /demos/jobs/{run_id}
```

Returns complete `WorkflowRunResponse` with all 8 step outputs, timestamps,
and status details.

### Cancel a Job
```
POST /demos/jobs/{run_id}/cancel
```

### List All Demos (metadata index)
```
GET /demos?tag=pet&limit=50
```

Returns all completed demos from the metadata index, optionally filtered by tag.

### Search Demos
```
GET /demos/search?q=pet+adoption&local_urls=true&limit=10
```

Returns matching demos with descriptions and URLs.
- `local_urls=true` (default) — returns internal URLs (`thor.local:8090`)
- `local_urls=false` — returns public URLs (`siri.choukalos.com`)

### Get Single Demo Metadata
```
GET /demos/{slug}
```

### Serve Demo HTML
```
GET /demos/{slug}/html
```

Serves the complete final HTML file with embedded notes.

## Configuration

| Environment Variable | Purpose | Default |
|---|---|---|
| `HARNESS_MODEL` | LLM model for all LLM calls | `gemma-moe` |
| `MEDIA_OUTPUT_DIR` | Base for generated media | `/data/media` |
| `SEARXNG_BASE_URL` | Web search endpoint | `http://searxng:8080` |
| `INTERNAL_BASE_URL` | Internal URL for artifact URLs | `http://thor.local:8090` |
| `PUBLIC_BASE_URL` | Public URL for Siri responses | `https://siri.choukalos.com` |

No new environment variables needed — all reuse existing configuration.

## OpenWebUI Tools

Three new tool functions are available in OpenWebUI:

### `create_demo(title, prompt, model)`
Starts the full workflow pipeline (research → build → polish → save).
Returns the run ID immediately. The demo takes 2-5 minutes to complete.
Follow up with `list_demos` to find the completed demo.

### `list_demos(tags, limit)`
Lists all created demos with titles, descriptions, tags, creation dates,
and local URLs. Optional tag filter.

### `find_demo(query, limit)`
Searches demos by natural language query (matches title, description,
tags). Returns matches with local URLs.

## Siri Integration

The Siri handler routes demo-related intents:

| Siri Phrase | Handler | Behavior |
|---|---|---|
| "list demos" / "my demos" | `_handle_list_demos` | Lists demos with PUBLIC URLs |
| "find demo about pets" | `_handle_find_demo` | Searches by query, returns PUBLIC URLs |
| "create a demo of..." | `_handle_demo` | Starts the old simple pipeline (instant) |

For the full research-backed workflow, Siri users should go through OpenWebUI
tools or the API directly (the workflow takes 2-5 minutes which Siri cannot
wait for).

## Tweaking the Pipeline

### Adding or Removing Build Steps
The build plan (stage 5) is generated by the LLM and typically produces 6-8 steps.
Cap is enforced at 8 in the build loop. Change the cap in `service.py`
`stage6_build_loop()`.

### Changing LLM Temperature per Stage
Adjust temperatures in each stage's `_call_llm()` or `_call_json()` calls in
`service.py`. See the temperature table above.

### Changing the Default Model
Set `HARNESS_MODEL` environment variable, or pass `model` in the
`POST /demos/create` body.

### Adjusting Retry Count
Change `MAX_BUILD_RETRIES` in `service.py` (default: 2).

### Adjusting Web Search Queries
Stage 3 generates queries via LLM. Change the LLM max_tokens or the
number of queries in `stage3_web_research()`.

### Changing Output Directory
Set `MEDIA_OUTPUT_DIR` — demos are saved under `{MEDIA_OUTPUT_DIR}/demos/`.

### Changing the Polish Critique Depth
Adjust the number of issues sent to the fix pass in `stage_polish()`
(currently top 8 issues).

## Error Handling
- **Failed KB lookups**: Logged as warnings, stage passes through with empty insights
- **Failed web searches**: Logged as warnings, stage continues with whatever results obtained
- **Failed LLM calls**: Caught and re-raised, workflow engine marks step as FAILED
- **Failed build steps**: Retried up to MAX_BUILD_RETRIES times, continues with issues noted
- **Failed polish fixes**: Logged, stage passes through with critique preserved
- **Failed final save**: Logged with error, intermediate files preserved in build/ and state/

## Future Improvements
1. **Test framework** — Add unit tests for stage functions and helpers
2. **Scheduled runs** — Wire up the `schedule` field for periodic demo generation
3. **More validation checks** — Add a browser-based HTML validator step
4. **Demo versioning** — Allow multiple versions of the same demo with diffs
5. **Shared component library** — Cache common UI patterns across demos
6. **Parallel build steps** — Build independent sections concurrently
7. **Mobile-specific testing** — Run through a mobile viewport validator
8. **Demo analytics** — Track which demos get opened most often
9. **Demo sharing** — Allow embedding demos in external pages
