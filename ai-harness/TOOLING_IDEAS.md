# AI Harness — Additional Tooling Ideas

Brainstorming and recommendations for new capabilities beyond the current feature set.

---

## 1. Road Trip Planner

### What It Does

Help the family plan road trips: route optimization, points of interest, hotel/accommodation search, itinerary generation, and maybe even real-time adjustments during the trip.

### Capabilities Breakdown

| Capability | Description | Integration |
|---|---|---|
| **Route planning** | Multi-stop route optimization, driving times, alternative routes | Google Maps Directions API or OSRM (self-hosted, free) |
| **Points of interest** | "Find cool things near Exit 42" — restaurants, attractions, rest stops | Google Places API or OpenStreetMap Nominatim (free, self-hostable) |
| **Hotel/accommodation search** | Hotels, campgrounds, Airbnbs along the route | Google Hotels API, Booking.com API, or Kamai (OpenStreetMap-based) |
| **Weather along route** | Forecast at key stops | OpenWeatherMap or self-hosted OWM proxy |
| **Itinerary generation** | LLM-assembled day-by-day plan with times, distances, highlights | Harness LLM + research module |
| **Real-time adjustments** | "We're running late, skip the next stop" — re-plan on the fly | Same APIs, triggered from Siri/OpenWebUI |
| **Cost estimation** | Gas, tolls, lodging budget | Google Maps + LLM estimation |

### Architecture Options

**Option A — Feature Module (inside harness)**

```
research/trip_planner/   # or its own top-level group: trips/
├── router.py
├── schemas.py
├── service.py
├── prompts.py
└── providers/
    ├── maps.py          # Google Maps / OSRM abstraction
    ├── places.py        # Google Places / Nominatim abstraction
    ├── hotels.py        # Booking.com / Google Hotels abstraction
    └── weather.py       # OpenWeatherMap abstraction
```

- Pros: Unified with other research features, family can use from OpenWebUI/Siri
- Cons: External API keys to manage, rate limits to respect

**Option B — Separate Service with Harness Integration**

Road trip planning is inherently stateful (a trip has a lifecycle) and might benefit from being its own module that *calls* the harness for LLM itinerary generation while handling maps/hotels independently.

- Pros: Clean separation of map APIs from general harness
- Cons: More infrastructure overhead

### My Recommendation

**Start as a feature module under `research/` or as a standalone `trips/` group.** The itinerary generation is primarily an LLM orchestration task (perfect for the harness). The map/hotel/POI lookups are API calls that wrap neatly into provider classes.

**For the map provider specifically:** If you want to avoid Google Maps billing (it can get expensive), consider **OSRM** (self-hosted routing engine) + **OpenStreetMap Nominatim** (free geocoding/POI). You'd run them as Docker containers alongside the harness. The trade-off is slightly less polish than Google Maps, but for family road trips it's more than sufficient.

**Siri use case is killer here:** "Hey Siri, plan a road trip from Chicago to Denver with stops every 3 hours and find kid-friendly attractions along the way." → Siri → harness → route + POIs + itinerary.

### OpenWebUI Tool Surface

```python
# In channels/openwebui/trip_tools.py

plan_trip(origin, destination, stops=None, pace="moderate")
  → Multi-stop route with POIs, estimated times, highlights

find_nearby(location, category, radius_miles)
  → Restaurants, attractions, gas stations near a point

estimate_cost(route)
  → Gas + tolls + suggested lodging budget

adjust_trip(trip_id, instruction)
  → "Skip the next stop" or "Add a stop in Springfield"
```

---

## 2. Multi-Phase Coding Agent

### The Problem

You want to feed the AI a plan document with multiple phases (like the `plan.md` we just wrote) and have it execute phases one at a time while you're at work — each with a clean context, working in a sandbox, with Git integration for checkpointing.

### Capabilities Breakdown

| Capability | Description | Why It Matters |
|---|---|---|
| **Plan ingestion** | Read a markdown plan doc with numbered phases/steps | Natural interface — you write the plan, AI executes it |
| **Phase isolation** | Each phase gets a fresh context window; no bleed between phases | Prevents context pollution, keeps each phase focused |
| **Sandboxed workspace** | Each phase works in its own temp directory or container | Safe experimentation, easy rollback |
| **Git checkpointing** | After each phase: commit with descriptive message, optionally push | You can review progress, revert, or branch |
| **Status reporting** | After each phase: summary of what was done, any blockers | You check in later and see progress |
| **Human-in-the-loop gates** | Optional: pause after each phase for your review before continuing | Safety valve for destructive changes |
| **Failure recovery** | If a phase fails, report the error and wait or retry | Don't silently corrupt things |

### Architecture

This is a natural fit for the **separate-container agent** pattern:

```
┌──────────────────────────────────────────────┐
│           coder-agent                        │
│                                              │
│  POST /coder/start  ── ingest plan.md ──────│
│    {                                          │
│      "plan": "...",                           │
│      "repo": "git@github.com:...",            │
│      "branch": "feat/reorg-2024",             │
│      "auto_push": false,                      │
│      "gate_after_phase": true                 │
│    }                                          │
│                                              │
│  GET  /coder/status   ── current phase ──────│
│  GET  /coder/log      ── phase output ────────│
│  POST /coder/approve   ── continue to next ──│
│  POST /coder/abort     ── stop ──────────────│
│                                              │
│  Internally:                                  │
│  1. Clone repo into /workspace/{job_id}      │
│  2. Parse plan.md into phases                │
│  3. For each phase:                           │
│     a. Spin fresh LLM conversation            │
│     b. Feed phase instructions + current     │
│        file state                             │
│     c. Execute edits (read/write/edit)        │
│     d. Run tests/linting                      │
│     e. git add/commit "Phase N: ..."          │
│     f. If gate_after_phase: pause             │
│  4. If auto_push: git push ──────────────────│
└──────────────────────────────────────────────┘
```

### How It Works in Practice

**You write a plan before leaving for work:**

```markdown
# Reorg Plan

## Phase 1: Create infra folder
- Move core/, tasks/, scheduler/, workflows/ under infra/
- Update all imports from `from core.X` to `from infra.core.X`
- Update compose Celery worker command

## Phase 2: Create feature group folders
- Move web_search, deep_research, market_research under research/
- Move family_kb under knowledge/
- etc.
```

**You kick it off:**

```
POST /coder/start
{
  "plan_file": "/workspace/reorg-plan.md",
  "target_repo": "/home/chuck/homelab/ai-harness",
  "branch": "feat/reorg-2024",
  "gate_after_phase": true,
  "auto_push": false
}
```

**Later, you check in:**

```
GET /coder/status
→ { "current_phase": 2, "total_phases": 6,
    "completed": ["Phase 1: infra folder"],
    "status": "waiting_for_approval",
    "last_commit": "a1b2c3d - Phase 1: Create infra folder" }
```

**You review the Git diff on your phone, approve, and it continues.**

### Technical Considerations

- **Sandbox approach:** The agent clones the repo into a temporary workspace directory inside its container. Each phase's work is committed to the branch before moving on. No changes touch the original until you merge.
- **Context management:** Each phase gets its own LLM conversation. The agent feeds it: (a) the phase instructions, (b) a file tree of current state, (c) relevant file contents. No prior phase context bleeds in.
- **Tool access:** The agent needs `bash`, `git`, and file read/write — essentially the same toolset Pi coder already has. It could even *be* a Pi coder agent running in a container.
- **Safety:** `gate_after_phase: true` means you always approve before the next phase. `auto_push: false` means commits stay local until you decide to push.

### Relationship to Existing Infrastructure

- The **harness scheduler** could trigger the coder agent at a specific time
- The **harness tasks** (Celery) could handle the long-running execution
- Or the coder agent could be a **fully separate container** that manages its own execution loop

### My Recommendation

Build this as a **separate container agent** (following the agent pattern from STRATEGY.md). It's heavy (runs for hours, needs isolated context, needs Git access) and benefits enormously from fault isolation. You don't want this hanging and taking down the family KB search.

The coder agent calls the harness's LLM endpoint (`/tasks/prompt` or `/tasks/chain`) for each phase's LLM work, keeping the actual AI inference in the shared harness infrastructure.

---

## 3. MySQL / Data Analysis Tooling

### What It Does

Connect to a MySQL database, understand its schema, and answer natural language questions. Use cases:

- **Family spend data** — "How much did we spend on groceries last month?" "What's our biggest spending category?"
- **Loaded datasets** — "Analyze this CSV I uploaded and find correlations"
- **Operational data** — "How many API calls did the harness make this week?"

### Capabilities Breakdown

| Capability | Description | Implementation |
|---|---|---|
| **Schema discovery** | Auto-read database schema, table relationships, column types | `SHOW CREATE TABLE`, `INFORMATION_SCHEMA` queries |
| **Text-to-SQL** | Convert natural language to SQL queries | LLM with schema context + SQL dialect knowledge |
| **Query execution** | Safely execute generated SELECT queries | Read-only DB user, query timeout, row limit |
| **Result interpretation** | Explain results in plain language, suggest follow-ups | LLM summarization |
| **Chart generation** | "Show me spending by category as a bar chart" | Integrate with `creative/charts` module |
| **Data upload** | Load CSV/Excel into new tables for analysis | Python `pandas` → `mysql-connector` |
| **Multi-database support** | Family finances, homelab metrics, custom datasets | Configurable connection strings per "data source" |

### Architecture

This fits cleanly as a feature module:

```
data/
├── router.py              # /data/query, /data/upload, /data/schema, /data/chart
├── schemas.py             # QueryRequest, QueryResult, SchemaInfo
├── service.py             # Text-to-SQL pipeline, query execution, result interpretation
├── prompts.py             # Text-to-SQL prompt templates
└── connectors/
    ├── mysql.py           # MySQL connector with read-only enforcement
    └── base.py            # Abstract connector interface (for future PostgreSQL, etc.)
```

### Security Considerations

This is the trickiest module from a safety standpoint:

1. **Read-only database user** — The harness connects to MySQL with a user that can only do `SELECT`. No `INSERT`, `UPDATE`, `DELETE`, `DROP`. Period.
2. **Query validation** — Before executing any LLM-generated SQL, validate it only contains `SELECT` (parse the AST or do a regex check as a belt-and-suspenders approach).
3. **Row limits** — Enforce a maximum row return (e.g., 10,000 rows) to prevent OOM.
4. **Query timeout** — Kill queries that run longer than 30 seconds.
5. **No file system access** — The SQL connection has no `LOAD DATA` or file access permissions.

### Text-to-SQL Flow

```
User: "How much did we spend on dining out in March?"

1. Schema discovery (cached):
   → "Tables: transactions (id, date, category, amount, merchant, notes)"

2. Text-to-SQL prompt:
   → "Given this schema, write a MySQL query to find total dining spending in March"
   → LLM returns: SELECT SUM(amount) FROM transactions WHERE category='dining' AND MONTH(date)=3

3. Validation:
   → Parse SQL, confirm it's SELECT-only, add LIMIT 10000

4. Execution:
   → Run against MySQL with read-only user
   → Result: { "total": 1247.53 }

5. Interpretation:
   → "You spent $1,247.53 on dining out in March. Want me to break it down by week or compare to February?"
```

### Integration with Creative Module

Once you have query results, the user might want to visualize them:

```
User: "Show me spending by category as a bar chart"

1. /data/query → returns category breakdown
2. /chart/create → generates the bar chart
3. User sees the chart in OpenWebUI
```

This is a nice cross-module workflow that showcases the harness's modular design.

### OpenWebUI Tool Surface

```python
# In channels/openwebui/data_tools.py

query_database(question, data_source="default")
  → Natural language → SQL → results + explanation

upload_data(file_path, table_name, format="csv")
  → Load a dataset into a new table for analysis

describe_schema(data_source="default")
  → Show what tables/columns are available

chart_query(question, chart_type="bar")
  → Query + generate chart in one step
```

### My Recommendation

Build this as a **first-class feature module** under `data/` (or `analytics/`). It's genuinely useful for family use cases and demonstrates the power of the harness architecture (combining LLM + data + visualization). Start with MySQL + read-only access, keep it simple, and add data sources over time.

If you already have a MySQL instance running for something (or can spin one up in Docker for this purpose), the path is straightforward.

---

## Priority & Effort Assessment

| Tool | Effort | Family Value | Complexity |
|---|---|---|---|
| **MySQL / Data Analysis** | Medium (2–3 days) | High (family spend, any dataset) | Medium (security is the main concern) |
| **Road Trip Planner** | Medium-High (3–5 days) | High (family vacations) | Medium (external API dependencies) |
| **Multi-Phase Coding Agent** | High (1–2 weeks) | Medium-High (your productivity) | High (context management, Git integration, safety) |

### Suggested Order

1. **Data Analysis** — Highest family value, straightforward architecture, no external API dependencies. Builds confidence in the harness pattern.
2. **Road Trip Planner** — High value, fun to build, good test of the harness + Siri integration. External APIs add some complexity.
3. **Coding Agent** — Most complex, but most rewarding for your own workflow. Benefits from patterns established by the first two.

---

## Cross-Cutting Observations

### LiteLLM is the common thread

All three tooling ideas are fundamentally **LLM + X** where X is a domain:
- Road trip = LLM + map APIs + itinerary generation
- Coding agent = LLM + file system + Git + test execution
- Data analysis = LLM + SQL + visualization

The harness's existing `core/llm.py` and `infra/tasks/` (Celery for long-running prompts) are the foundation all three build on. The pattern is:

```
User input → harness endpoint → LLM prompt chain → external service calls → LLM interpretation → response
```

### Agents vs. Features

- **Data analysis** is clearly a feature (stateless, request/response)
- **Road trip planner** could be either — a feature for "plan this trip" or an agent for "plan and manage this trip over several days"
- **Coding agent** is clearly an agent (stateful, multi-phase, autonomous execution)

The harness should support both patterns, and the STRATEGY.md document establishes how.

### Future: n8n Integration?

You already have `compose.n8n.yml` in your compose directory. n8n could be a bridge for some of these — especially the road trip planner (n8n has Google Maps, Booking.com, and many other integrations built in) and the coding agent (n8n could orchestrate the multi-phase workflow). Worth keeping in mind as an alternative to building everything from scratch in the harness.
