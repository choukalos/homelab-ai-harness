# AI Harness

Unified API and tool layer for the homelab AI ecosystem. Every AI capability — whether consumed by OpenWebUI, Siri, agents, or future integrations — flows through the harness as the single source of truth.

## Quick Start

```bash
# Build and start
docker compose -f ../compose/compose.ai-harness.yml build
docker compose -f ../compose/compose.ai-harness.yml up -d

# Health check
curl http://thor.local:8090/health
```

## Directory Structure

```
ai-harness/
├── app.py                 # FastAPI application entrypoint
├── STRATEGY.md            # Organization strategy & design principles
├── architecture.md        # (→ see STRATEGY.md)
├── family_kb_watch.py     # File-system watcher for KB ingestion
├── requirements.txt
├── Dockerfile
│
├── infra/                 # Internal platform plumbing
│   ├── core/              # config, llm client, celery_app, cache, security
│   ├── tasks/             # Celery task queue
│   ├── scheduler/         # Celery Beat + RedBeat scheduling
│   └── workflows/         # Multi-step stateful workflow engine
│
├── research/              # Discover information from the web
│   ├── web_search/        # Web search (SearXNG + Crawl4AI)
│   ├── deep_research/     # Multi-step deep research
│   └── market_research/   # Market trend analysis
│
├── knowledge/             # Store and search family knowledge
│   └── family_kb/         # Qdrant-backed knowledge base
│
├── creative/              # Generate documents, slides, visualizations
│   ├── presentation/      # AI-powered presentations (via Presenton)
│   ├── charts/            # Plotly chart generation
│   └── layout/            # Document/layout generation
│
├── media/                 # ComfyUI image/video generation
│
├── apps/                  # Build runnable demos and prototypes
│   ├── pm_demo/           # Product Manager demo builder
│   └── demo_workflow/     # Multi-step demo generation
│
├── filetools/             # Document and file manipulation
│
├── channels/              # Consumer adapters (zero business logic)
│   ├── openwebui/         # OpenWebUI tool files
│   │   ├── harness_base.py
│   │   ├── research_tools.py
│   │   ├── knowledge_tools.py
│   │   ├── creative_tools.py
│   │   ├── media_tools.py
│   │   ├── apps_tools.py
│   │   ├── filetools_tools.py
│   │   └── scheduler_tools.py
│   └── siri/              # Siri shortcut definitions, CarPlay configs
│
└── tests/                 # Test suite
    ├── harness-smoke-test.sh    # Master orchestrator (runs all)
    ├── cleanup_presentations.sh # Presentation cleanup utility
    ├── smoke/                 # Smoke tests per group
    │   ├── test_infra.sh
    │   ├── test_research.sh
    │   ├── test_knowledge.sh
    │   ├── test_creative.sh
    │   ├── test_media.sh
    │   ├── test_apps.sh
    │   └── test_filetools.sh
    └── channels/              # Channel-specific tests
        └── test_siri.sh
```

## Services

The compose stack runs:

| Service | Description |
|---|---|
| `ai-harness` | FastAPI web app (port 8090) |
| `ai-harness-worker-1/2` | Celery workers (4 concurrent each) |
| `ai-harness-beat` | Celery Beat scheduler (RedBeat) |
| `ai-kb-watcher` | File-system watcher for KB ingestion |

## API

Browse the OpenAPI docs at `http://thor.local:8090/docs`

## Testing

```bash
# Run all smoke tests
./tests/harness-smoke-test.sh

# Include slower media tests
RUN_MEDIA_TESTS=1 ./tests/harness-smoke-test.sh

# Include Siri channel tests
RUN_CHANNEL_TESTS=1 ./tests/harness-smoke-test.sh
```

## Adding a New Feature

1. Create the module under the appropriate group (or create a new group)
2. Follow the standard module shape (`router.py`, `schemas.py`, `service.py`, ...)
3. Register the router in `app.py`
4. Add a corresponding OpenWebUI tool file under `channels/openwebui/`
5. Add a smoke test under `tests/smoke/`

See **[STRATEGY.md](./STRATEGY.md)** for full details on design principles and extension patterns.
