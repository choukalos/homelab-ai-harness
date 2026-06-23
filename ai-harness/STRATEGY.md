# AI Harness — Organization Strategy

## Purpose

The AI Harness is the unified API and tool layer for our homelab AI ecosystem. Every AI capability — whether consumed by OpenWebUI, Siri, a future messaging bot, or an autonomous agent — flows through the harness as the single source of truth.

This document captures **what belongs in the harness, what doesn't, and how we organize it** as the system grows.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│                       CONSUMERS                             │
│                                                             │
│  OpenWebUI   Siri   Telegram   iMessage   Agents   Pi ...  │
│     │           │         │          │          │           │
│     └──────┬────┴────┬────┴──────────┴──────────┘           │
│            │         │                                      │
│            ▼         ▼                                      │
│  ┌─────────────────────────────────────────────────┐        │
│  │                 ai-harness                       │        │
│  │                                                  │        │
│  │  infra/       research/  knowledge/              │        │
│  │  (core,       (web,      (family KB,             │        │
│  │   tasks,      deep,       semantic search)       │        │
│  │   scheduler,  market)                             │        │
│  │   workflows)                                        │        │
│  │                                                  │        │
│  │  creative/    media/       apps/     filetools/   │        │
│  │  (present,   (comfyui     (pm_demo,  (document    │        │
│  │   charts,    images/      demos)    manipulation) │        │
│  │   layout)    video)                                  │        │
│  │                                                  │        │
│  └─────────────────────────────────────────────────┘        │
│            │         │                                      │
│            ▼         ▼                                      │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐          │
│  │ LiteLLM  │ │ Qdrant   │ │ SearXNG │ │ MySQL  │          │
│  └──────────┘ └──────────┘ └─────────┘ └────────┘          │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

### Three Tiers

The harness is organized into **three tiers** with clear boundaries:

### 1. `infra/` — Internal Platform Plumbing

Services that enable features but are **never called directly by consumers**.

```
infra/
├── core/          # config, llm client, cache, security
├── tasks/         # Celery task queue (prompt, chain, python execution)
├── scheduler/     # Celery Beat + RedBeat (durable scheduling)
└── workflows/     # Workflow engine (multi-step stateful pipelines)
```

**Decision:** These stay internal. No OpenWebUI tool file is generated for infra. Consumers interact with features, not infrastructure.

### 2. Feature Modules — User-Facing Capabilities

Each feature module is a self-contained domain with a standard structure:

```
feature_name/
├── __init__.py
├── router.py      # FastAPI endpoints
├── schemas.py     # Pydantic request/response models
├── service.py     # Core business logic
├── prompts.py     # LLM prompts (if applicable)
├── tasks.py       # Celery tasks (if applicable)
└── tools.py       # Internal tool definitions (if applicable)
```

**Grouped by domain:**

| Group | Modules | What it does |
|---|---|---|
| **research/** | `web_search`, `deep_research`, `market_research` | Discover information from the web |
| **knowledge/** | `family_kb` | Store and search family knowledge (Qdrant) |
| **creative/** | `presentation`, `charts`, `layout` | Generate documents, slides, visualizations |
| **media/** | `media` | ComfyUI image/video generation (GPU-bound) |
| **apps/** | `pm_demo`, `demo_workflow` | Build runnable demos and prototypes |
| **filetools/** | `filetools` | Document and file manipulation |

**Decision:** Grouping is semantic, not arbitrary. Modules in the same group share conceptual purpose and often share underlying dependencies. A consumer that wants "research capabilities" gets everything under `research/`.

### 3. `channels/` — Consumer Adapters

How people talk to the harness. **Zero business logic** — just routing and format translation.

```
channels/
├── openwebui/     # OpenWebUI tool files (Python)
├── siri/          # Siri shortcut definitions, CarPlay configs
└── ...            # Future: telegram/, imessage/, etc.
```

**Decision:** Channels are read-only from the harness perspective. You don't modify harness code to add a channel — you write a new adapter that calls existing harness APIs.

---

## Agents — Separate Containers

Agents are **autonomous orchestrators** that combine multiple harness features into multi-step workflows. Examples:

- **GTM Agent** — researches trends, generates content, schedules publishing
- **Content Writer** — drafts, revises, and publishes content across platforms
- **Road Trip Planner** — researches destinations, books, creates itineraries

### Why Separate Containers?

| Concern | Inside Harness | Separate Container |
|---|---|---|
| **Fault isolation** | Agent crash takes down everything | Agent crash is contained |
| **Resource allocation** | Competes with family tools for GPU/CPU | Own GPU/memory budget |
| **Scaling** | Can't scale independently | Spin up replicas during heavy work |
| **Deployment** | Restart agent → restart everything | Update agent independently |
| **Lifecycle** | Tied to harness uptime | Can run on its own schedule/cadence |

### How Agents Work

```
┌──────────────┐    HTTP API     ┌──────────────┐
│  Agent       │ ──────────────► │  ai-harness  │
│  Container   │                  │  (port 8090) │
│  (port 8091) │ ◄────────────── │              │
│              │   results       │  /research   │
│              │                  │  /creative   │
│  Internally: │                  │  /knowledge  │
│  - Planning  │                  │  /media      │
│  - Draft mgmt│                  │  /schedules  │
│  - Review    │                  └──────────────┘
│  - Publishing│
└──────────────┘
```

- Agent calls harness APIs like any other consumer
- Agent has its own lightweight FastAPI or Celery-only process
- Agent gets its own compose service with independent resource controls
- Agent can be scheduled by the harness scheduler OR have its own internal scheduler
- Agent containers are added to `compose.ai-harness.yml` as siblings to the main harness

### Agent Development Pattern

1. Prototype the agent logic as a harness module first (same container)
2. Prove the workflow end-to-end
3. Extract into its own container once the workflow is solid
4. Agent communicates with harness exclusively over HTTP — no shared imports

---

## What Belongs in the Harness vs. What Doesn't

### In the Harness

- Any capability that needs LLM access through LiteLLM
- Any capability that needs to be called from multiple consumers (OpenWebUI, Siri, agents)
- Any capability with shared infrastructure dependencies (Qdrant, SearXNG, ComfyUI)
- Any capability that produces artifacts family members might need (documents, images, research)

### Not in the Harness

- **Consumer UI** — OpenWebUI handles its own UI; harness is API-only
- **Platform-specific protocol logic** — Telegram bot handling, iMessage Shortcuts logic belongs in `channels/`, not as harness features
- **Raw infrastructure** — Qdrant, Redis, LiteLLM, ComfyUI are separate services; harness calls them, doesn't contain them
- **Long-running daemons unrelated to AI** — monitoring, backups, etc. stay in their own compose files

---

## OpenWebUI Tool Distribution

Tools are split into **per-group files** so family members can pick what they need:

```
channels/openwebui/
├── harness_base.py           # Shared base class (Valves, _headers, _post, etc.)
├── research_tools.py         # Web search, deep research, market research
├── knowledge_tools.py        # KB search, ingestion status
├── creative_tools.py         # Presentations, charts, layouts
├── media_tools.py            # ComfyUI images/video
├── apps_tools.py             # Demos, prototypes
├── filetools_tools.py        # Document manipulation
└── scheduler_tools.py        # Schedule management (optional)
```

**Provisioning strategy:** Admin workspace in OpenWebUI gets all tools installed globally. Each tool file is independent — adding a new group doesn't require editing existing files.

---

## Test Organization

Tests mirror the feature grouping:

```
tests/
├── smoke/                    # End-to-end smoke tests per group
│   ├── test_research.sh
│   ├── test_knowledge.sh
│   ├── test_creative.sh
│   ├── test_media.sh
│   ├── test_apps.sh
│   └── test_infra.sh
├── channels/                 # Channel-specific tests
│   ├── test_siri.sh
│   └── test_openwebui.sh
└── harness-smoke-test.sh    # Master smoke test (runs all groups)
```

---

## Future-Proofing

### Adding a New Feature

1. Create the module under the appropriate group (or create a new group if it doesn't fit)
2. Follow the standard module shape (`router.py`, `schemas.py`, `service.py`, etc.)
3. Register the router in `app.py`
4. Add corresponding OpenWebUI tool file under `channels/openwebui/`
5. Add smoke test under `tests/smoke/`

### Adding a New Channel

1. Create `channels/channel_name/`
2. Implement the adapter against existing harness APIs
3. No harness code changes needed

### Adding a New Agent

1. Prototype as a harness module to prove the workflow
2. Extract to `agents/agent_name/` as its own Docker service
3. Agent calls harness HTTP APIs
4. Add to compose file with independent resource controls

---

## Design Principles

1. **Single source of truth** — Logic lives in the harness. Channels and agents are thin wrappers.
2. **Modular by default** — New capabilities are additive, not invasive. No editing existing code.
3. **Platform-agnostic** — The harness doesn't care if you're coming from OpenWebUI, Siri, or Telegram.
4. **Fault isolation** — Heavy or risky workloads (agents, media) run in separate containers.
5. **Family-friendly distribution** — Tools are pick-and-choose. No forced monoliths.
6. **Evolution over revolution** — Prototype inside the harness, extract when proven.
