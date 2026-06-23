# Market Research Workflow

An automated, LLM-driven market research pipeline that takes a single market name as input and produces a fully formatted PDF research report. The pipeline discovers competitors, deep-dives into each player, builds a comparison matrix, analyzes market tiers, and assembles everything into a professional report with charts.

## What It Does

Given a market name (e.g. "Smart Home", "Electric Vehicles"), the workflow:

1. **Checks prior knowledge** — queries the Family Knowledge Base for any previous research on this market
2. **Discovers competitors** — runs targeted web searches, then uses an LLM to classify each competitor into tiers (top players, established, new entrants)
3. **Deep-dives each competitor** — crawls every competitor's website, then generates a structured competitive profile via LLM analysis
4. **Extracts comparison vectors** — identifies 8-15 meaningful comparison dimensions (features, pricing, positioning, etc.) across all competitors
5. **Populates a comparison matrix** — fills in a competitors × vectors matrix cell-by-cell using LLM extraction
6. **Analyzes each tier** — generates narrative analysis per tier (collective behaviors, market positioning, value point clustering)
7. **Writes an executive summary** — synthesizes a C-suite-ready summary with key findings
8. **Scouts innovation opportunities** — identifies whitespace opportunities, emerging trends, and divergent strategies
9. **Plans visual layout** — determines where charts, tables, and text blocks go in the final report
10. **Assembles the PDF report** — builds the report using the Layout Engine, generates charts via Plotly, and exports a PDF

## Architecture

```
POST /markets/research
       │
       ▼
┌─────────────────────────────────────────────────┐
│              Workflow Engine                      │
│  (workflows/ — MySQL-backed DAG state machine)     │
│                                                   │
│  workflow_runs  ← run state, status, metadata     │
│  workflow_steps ← per-step status, output, errors  │
│  workflows      ← reusable workflow definitions    │
└──────────┬──────────────────────────────────────┘
           │ dispatches Celery tasks
           ▼
┌──────────────────────────────────────────────┐
│           Celery Worker Pool                  │
│                                                │
│  market_research.run_stage(stage=N, run_id)    │
│       │                                       │
│       ├──► Stage 1:  KB Lookup                │
│       │     └─► family_kb.search_kb()          │
│       │         └─► Qdrant (semantic search)   │
│       │                                       │
│       ├──► Stage 2:  Competitor Discovery      │
│       │     ├─► LLM generates search queries   │
│       │     ├─► SearXNG (web search)           │
│       │     └─► LLM tiers competitors           │
│       │                                       │
│       ├──► Stage 3:  Deep-Dive                 │
│       │     ├─► Crawl4AI (URL crawling)        │
│       │     └─► LLM profiles (per competitor)  │
│       │                                       │
│       ├──► Stage 4:  Vector Identification     │
│       │     └─► LLM extracts comparison dims    │
│       │                                       │
│       ├──► Stage 5:  Data Population           │
│       │     └─► LLM fills matrix cells          │
│       │                                       │
│       ├──► Stage 6:  Tier Analysis             │
│       │     └─► LLM narrative per tier          │
│       │                                       │
│       ├──► Stage 7:  Executive Summary         │
│       │     └─► LLM synthesizes summary         │
│       │                                       │
│       ├──► Stage 8:  Innovation Scouting       │
│       │     └─► LLM finds whitespace/trends     │
│       │                                       │
│       ├──► Stage 9:  Visual Planning           │
│       │     └─► LLM plans report layout         │
│       │                                       │
│       └──► Stage 10: Report Assembly           │
│             ├─► Layout Engine (HTML/CSS)       │
│             ├─► Chart Engine (Plotly/Kaleido)  │
│             └─► WeasyPrint (PDF export)        │
└──────────────────────────────────────────────┘
           │
           ▼
     /data/media/research/{market}/
       ├── stage1_kb_lookup.json
       ├── stage2_competitors.json
       ├── competitor_<name>.md
       ├── stage3_deep_dive.json
       ├── stage4_vectors.json
       ├── stage5_matrix.json
       ├── stage6_tier_analysis.json
       ├── stage7_executive_summary.json
       ├── stage8_innovation.json
       ├── stage9_layout_plan.json
       ├── state_snapshot.json
       ├── {market}_Research_Report_YYYYMMDD.html
       └── {market}_Research_Report_YYYYMMDD.pdf
```

## Pipeline Stages

### Stage 1 — KB Lookup
Queries the Family Knowledge Base (Qdrant-backed semantic search) for prior research on the same market. The LLM synthesizes findings into insights and flags any previously tracked comparison vectors. This helps the pipeline build on existing knowledge rather than starting from scratch each time.

### Stage 2 — Competitor Discovery & Tiering
The LLM generates 5 focused web search queries targeting market overviews, established players, startups, rankings, and recent launches. Each query is executed against SearXNG. Search results are fed back to the LLM which classifies each discovered competitor into one of three tiers:
- **top_player** — Market leaders with >10% estimated share
- **established** — Well-funded companies with significant presence
- **new_entrant** — Startups, recent launches, disruptive newcomers

Target: 5-15 total competitors.

### Stage 3 — Competitor Deep-Dive
For each competitor, the pipeline crawls their primary URL using Crawl4AI, then passes the extracted content to the LLM to generate a structured profile covering:
- Positioning statement
- Value propositions
- Products/services offered
- Pricing tiers
- Key features
- One-paragraph summary

Each profile is written to disk as a markdown file (`competitor_<name>.md`).

### Stage 4 — Vector / Theme Identification
All competitor profiles are analyzed by the LLM to identify 8-15 meaningful comparison dimensions (vectors). These span features, pricing, positioning, services, and differentiators. Vectors are marked as coming from prior KB data or newly discovered. Newly discovered vectors are flagged for potential KB updates.

### Stage 5 — Data Population
For every competitor × vector combination, the LLM extracts a concise value (max 80 chars) from the competitor's raw markdown profile. This builds the comparison matrix that becomes the centerpiece of the report. Missing data is marked "N/A".

### Stage 6 — Tier Analysis
For each of the three tiers, the LLM generates a narrative analysis including:
- Collective behaviors of companies in that tier
- How the tier positions itself in the market
- Value point clustering (what features are common/different)
- A 150-200 word summary paragraph suitable for the report

### Stage 7 — Executive Summary
A C-suite-ready executive summary (200-300 words) is synthesized from all prior stages' outputs, covering market landscape, competitive dynamics, key trends, and strategic implications. Key findings are extracted as bullet points.

### Stage 8 — Innovation & Opportunity Scouting
The LLM analyzes the comparison matrix and competitor profiles to identify:
- Emerging trends
- Untested features (whitespace)
- Pricing divergences
- Unserved customer segments
- A whitespace summary paragraph

### Stage 9 — Visual Planning
The LLM plans the visual layout of the final report, determining where charts, tables, images, and text blocks should be placed across the layout zones.

### Stage 10 — Report Assembly
The final stage uses the Layout Engine to:
1. Create a "magazine" template layout
2. Place the executive summary text
3. Insert the comparison matrix as a styled table
4. Generate a bar chart (feature coverage per competitor) via Plotly
5. Generate a pie chart (tier distribution) via Plotly
6. Add tier analysis sections as text
7. Add innovation & opportunities section
8. Render the full HTML document
9. Export to PDF via WeasyPrint

## How the Pieces Fit Together

### Workflow Engine (`workflows/`)
A generic DAG-based workflow engine backed by MySQL. It tracks:
- **Workflow definitions** — reusable DAGs with step names, dependencies, and Celery task references
- **Runs** — executions of a workflow definition with status, metadata, and timestamps
- **Steps** — individual tasks within a run, with state transitions (pending → running → success/failed)

The market research pipeline registers a 10-step workflow definition at startup with dependency chains. The engine supports parallel execution where dependencies allow (e.g., stages 7 and 8 can theoretically run in parallel after stage 5, though stage 8 also depends on stage 7 in the current config).

### Celery Tasks (`tasks.py`)
A single dispatchable Celery task `market_research.run_stage(stage=N, run_id)` handles all 10 stages. It:
1. Loads the accumulated state from disk (intermediate JSON files)
2. Executes the target stage function
3. Persists the updated state snapshot back to disk
4. Calls the workflow engine to mark the step as complete

State is persisted to disk (not passed through Celery) because intermediate data can be large (competitor profiles, matrix data). Each stage reads what it needs from the shared `MarketResearchState`.

### LLM Integration (`core/llm.py`)
All LLM calls go through LiteLLM, which acts as a proxy layer. The default model is configured via `HARNESS_MODEL` env var (current: `matrix-gemma4-moe`). Each stage uses different temperatures:
- Stage 1 (KB synthesis): 0.2 (deterministic)
- Stage 2 (competitor discovery queries): 0.5 (creative)
- Stage 2 (tiering): 0.2 (deterministic classification)
- Stage 3 (profiling): 0.1 (very deterministic extraction)
- Stage 4 (vectors): 0.2 (deterministic)
- Stage 5 (cell population): 0.0 (fully deterministic)
- Stage 6 (tier analysis): 0.3 (slightly creative narrative)
- Stage 7 (executive summary): 0.2 (deterministic)
- Stage 8 (innovation): 0.4 (creative exploration)
- Stage 9 (visual planning): 0.3 (moderately creative)

### External Dependencies
The pipeline relies on these infrastructure services:
- **SearXNG** — privacy-respecting metasearch engine for web search (stage 2)
- **Crawl4AI** — web content extraction/crawling (stage 3)
- **Qdrant** — vector database for the Family Knowledge Base (stage 1)
- **LiteLLM** — LLM proxy/providing the actual language model
- **MySQL** — workflow state persistence

### Output Artifacts
All intermediate and final outputs are written to `/data/media/research/<market_name>/`:
- `stage1_kb_lookup.json` — KB search results and insights
- `stage2_competitors.json` — discovered competitors with tier classifications
- `competitor_<name>.md` — per-competitor markdown profiles
- `stage3_deep_dive.json` — aggregate deep-dive results
- `stage4_vectors.json` — comparison vectors/themes
- `stage5_matrix.json` — populated comparison matrix
- `stage6_tier_analysis.json` — tier narrative analyses
- `stage7_executive_summary.json` — executive summary
- `stage8_innovation.json` — opportunities and trends
- `stage9_layout_plan.json` — visual layout plan
- `state_snapshot.json` — full pipeline state
- `<market>_Research_Report_YYYYMMDD.html` — final HTML report
- `<market>_Research_Report_YYYYMMDD.pdf` — final PDF report

## APIs

### Start a Research Job
```
POST /markets/research
Content-Type: application/json

{
  "market": "Smart Home",
  "schedule": "on_demand"
}
```
Returns: `{ "run_id": "...", "workflow_id": "...", "market": "Smart Home", "status": "pending", "steps_count": 10 }`

### List Jobs
```
GET /markets/research/jobs?market=Smart+Home&status=pending&limit=20
```

### Get Job Status + Full Output
```
GET /markets/research/jobs/{run_id}
```
Returns complete `WorkflowRunResponse` with all 10 step outputs, timestamps, and status details.

### Cancel a Job
```
POST /markets/research/jobs/{run_id}/cancel
```

### List Intermediate Files
```
GET /markets/research/jobs/{run_id}/files
```

## Configuration

| Environment Variable | Purpose | Default |
|---|---|---|
| `HARNESS_MODEL` | LLM model identifier for LiteLLM | `gemma-moe` |
| `LITELLM_BASE_URL` | LiteLLM proxy endpoint | `http://litellm:4000` |
| `LITELLM_API_KEY` | LiteLLM API key | (from .env) |
| `SEARXNG_BASE_URL` | SearXNG search endpoint | `http://searxng:8080` |
| `CRAWL4AI_BASE_URL` | Crawl4AI crawling endpoint | `http://crawl4ai:11235` |
| `MEDIA_OUTPUT_DIR` | Base directory for all generated media | `/data/media` |
| `INTERNAL_BASE_URL` | Internal URL for artifact URLs | `http://thor.local:8090` |
| `MYSQL_DB_HOST` | MySQL host for workflow state | `host.docker.internal` |
| `AI_DB_NAME` | MySQL database name | `ai_harness` |
| `REDIS_URL` | Redis URL (Celery broker + backend) | `redis://redis:6379/0` |

## Tweaking the Pipeline

### Adding or Removing Stages
Edit `_MARKET_RESEARCH_STEPS` in `router.py` and the `_PIPELINE` list in `service.py`. Keep them in sync — the router defines the DAG for the workflow engine, and the service defines the execution order.

### Changing LLM Temperature per Stage
Each stage function in `service.py` calls `_call_json()` or `chat_completion_sync()` with an explicit `temperature` parameter. Adjust these values to control creativity vs. determinism.

### Changing the Default LLM Model
Set `HARNESS_MODEL` in your environment to any model ID that your LiteLLM proxy supports.

### Adjusting Competitor Count
In `prompts.py`, the `prompt_tier_competitors` template says "Aim for 5-15 total competitors." Change this range to get more or fewer competitors analyzed.

### Adjusting Vector Count
In `prompts.py`, the `prompt_vector_extraction` template says "Include 8-15 vectors." Change this range for more or fewer comparison dimensions.

### Adding New Comparison Vectors to KB
Stage 4 outputs `new_vectors_flagged` — vectors discovered during this run that weren't in prior KB data. You could add a new stage (or extend stage 4) to upsert these back to Qdrant for future runs.

### Changing Report Template
In `stage10_report_assembly()`, the layout is created with `template="magazine"`. Other available templates: `hero`, `grid`, `split`, `gallery`, `cards`, `minimal`, `timeline`, `pitch`, `blank`.

### Changing Chart Types
The charts are generated via `charts/service.py` which supports `line`, `bar`, and `pie` charts via Plotly. Stage 10 currently creates one bar chart and one pie chart. The ChartZoneSpec schema supports full customization of titles, labels, colors, and dimensions.

### Parallel Execution
The workflow engine supports parallel step execution when `depends_on` allows it. Currently the pipeline is mostly sequential, but stage 8 depends on both stage 5 and stage 7 — if you modify stage 8 to only depend on stage 5, it could run in parallel with stage 7.

## Error Handling
- **Failed searches** (stage 2): Logged as warnings, the stage continues with whatever results were obtained
- **Failed crawls** (stage 3): Logged as errors, the competitor is skipped and the URL is recorded in `failed_scrapes`. The pipeline continues
- **Failed LLM calls**: Caught and re-raised, which triggers the workflow engine's step failure. The step is marked FAILED with the error message stored
- **Failed PDF export** (stage 10): Logged as error, the HTML file is still produced. The `pdf_bytes` field will be 0

## Future Improvement Opportunities
1. **Retry logic** — Currently steps fail outright. Could add retry with exponential backoff
2. **Vector KB feedback loop** — Auto-upsert newly discovered vectors back to Qdrant
3. **Caching** — Reuse competitor profiles from recent runs if the market hasn't changed
4. **More chart types** — Add scatter plots, heatmaps for the comparison matrix
5. **Multi-page reports** — Currently single-page layout; extend to multi-page for markets with many competitors
6. **Scheduled runs** — The `schedule` field on the request is captured but not yet wired to the scheduler
