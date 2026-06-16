# Deep Research

> **Status:** Skeleton proof-of-concept — single-search-node to validate the Deep Agents + MySQL checkpointing flow.

LangChain [Deep Agents](https://docs.langchain.com/oss/python/deepagents) harness wired into the ai-harness with MySQL-backed state persistence, a SearXNG web-search tool, and endpoints for both OpenWebUI and the Siri interface.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ai-harness (FastAPI)                         │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  router.py   │───>│  service.py  │───>│  Deep Agent Graph    │  │
│  │              │    │              │    │  (create_deep_agent) │  │
│  │  /run        │    │  get_deep_   │    │                      │  │
│  │  /run/stream │    │  _agent()    │    │  ┌────────────────┐  │  │
│  └──────────────┘    └──────────────┘    │  │ search_web     │  │  │
│                                          │  │ (SearXNG)      │  │  │
│                                          │  │ checkpointer   │  │  │
│                                          │  │ (MySQL)        │  │  │
│                                          │  └────────────────┘  │  │
│                                          └──────────────────────┘  │
│                                                                     │
│  Integrations:                                                     │
│  ┌──────────────────┐  ┌──────────────────┐                       │
│  │ Siri (siri/     │  │ OpenWebUI        │                       │
│  │  service.py)     │  │ (openwebui_tools/│                       │
│  │                  │  │  harness_tools.py│                       │
│  └──────────────────┘  └──────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
   ┌────────────┐                   ┌────────────┐
   │ MySQL (AI  │                   │ SearXNG    │
   │ Harness)   │                   │ (web search)│
   └────────────┘                   └────────────┘
```

### Key Components

| File | Role |
|------|------|
| `__init__.py` | Package marker |
| `schemas.py` | Pydantic request/response models |
| `service.py` | MySQL checkpointer, `search_web` tool, agent factory, execution entrypoint, result extraction helpers |
| `router.py` | FastAPI routes — sync `/run` and streaming `/run/stream` (SSE) |

---

## Current Skeleton Functionality

### 1. Agent

Built via `create_deep_agent()` with:
- **Model:** `HARNESS_MODEL` env var, auto-prefixed with `openai:` if no colon present (routes through LiteLLM)
- **Tools:** `search_web` (SearXNG)
- **Checkpointer:** `AsyncMySaver` → MySQL using existing `AI_DB_*` env vars
- **System prompt:** Deep research assistant instructions (search → synthesize → cite)
- **Singleton:** Agent is built once on first call via `get_deep_agent()`

### 2. MySQL Checkpointing

- Uses `langgraph-checkpoint-mysql[asyncmy]` with `AsyncMySaver`
- Reuses env vars: `MYSQL_DB_HOST`, `MYSQL_DB_PORT`, `AI_DB_USER`, `AI_DB_PASS`, `AI_DB_NAME`
- Tables auto-created on app startup via `ensure_checkpointer_tables()` → `cp.asetup()`
- **Thread ID:** Each run gets a `thread_id` (from request or auto-generated UUID). This is the LangGraph checkpoint key — resuming a prior run uses the same `thread_id`.
- Checkpoint tables: `checkpoint_writes`, `checkpoints` (auto-created by `.setup()`)

### 3. Tools (Current)

| Tool | Source | Notes |
|------|--------|-------|
| `search_web` | SearXNG (`SEARXNG_BASE_URL`) | Returns title/url/content/engine. Sync httpx call inside the tool. |

### 4. Endpoints

| Endpoint | Auth | Behavior |
|----------|------|----------|
| `POST /workflows/deep-research/run` | `require_auth` | Sync — invokes the agent, waits for completion, returns `DeepResearchResponse` |
| `POST /workflows/deep-research/run/stream` | `require_auth` | SSE — streams `start → update... → done` events via `agent.astream(stream_mode="updates")` |

### 5. Integrations

| Interface | How it connects |
|-----------|----------------|
| **Siri** | `_handle_deep_research()` in `siri/service.py` — intent `deep_research` triggered by "deep research [topic]" — POSTs to `/deep-research/run` |
| **OpenWebUI** | `deep_research()` method in `openwebui_tools/harness_tools.py` — POSTs to `/deep-research/run`, formats answer + steps + sources |

---

## Request / Response Schema

### `DeepResearchRequest`

```json
{
  "query": "What are the latest developments in quantum computing?",
  "thread_id": null,       // optional, auto-generated UUID if omitted
  "model": null            // optional, overrides HARNESS_MODEL
}
```

### `DeepResearchResponse`

```json
{
  "thread_id": "abc-123-...",
  "query": "What are the latest developments in quantum computing?",
  "answer": "Research answer synthesized by the agent...",
  "sources": [
    {"tool_result": "..."}
  ],
  "steps": [
    {"action": "search_web", "args": {"query": "..."}},
    {"result_preview": "..."}
  ],
  "error": null
}
```

---

## Dependencies (requirements.txt)

```
deepagents                          # LangChain Deep Agents SDK
langgraph-checkpoint-mysql[asyncmy] # MySQL Async checkpointer
langchain-openai                    # OpenAI-compatible model backend (via LiteLLM)
```

---

## Environment Variables

| Var | Used By | Default |
|-----|---------|---------|
| `HARNESS_MODEL` | Agent model selection | `gemma-moe` |
| `LITELLM_BASE_URL` | LiteLLM proxy (via `create_deep_agent` auto-config) | `http://litellm:4000` |
| `SEARXNG_BASE_URL` | `search_web` tool | `http://searxng:8080` |
| `MYSQL_DB_HOST` | Checkpointer | `host.docker.internal` |
| `MYSQL_DB_PORT` | Checkpointer | `3306` |
| `AI_DB_USER` | Checkpointer | `root` |
| `AI_DB_PASS` | Checkpointer | `""` |
| `AI_DB_NAME` | Checkpointer | `ai_harness` |

---

## Planned Expansion

### Phase 1 — Multi-step Research Pipeline

| Feature | Description |
|---------|-------------|
| **crawl_web** | Tool using Crawl4AI (`CRAWL4AI_BASE_URL`) for full-page content extraction |
| **query generation** | LLM step to decompose the user's question into multiple focused search queries |
| **synthesize** | Dedicated LLM step to merge all search/crawl results into a structured research report |
| **subagents** | Declarative subagents (per Deep Agents docs) for parallel research tasks |

### Phase 2 — Context & Memory

| Feature | Description |
|---------|-------------|
| **memory files** | `memory=["./AGENTS.md"]` for domain-specific research instructions |
| **skills** | `skills=["./skills/"]` for on-demand knowledge retrieval |
| **state_schema** | Custom `DeepAgentState` with structured channels for sources, draft sections, etc. |
| **long-term store** | LangGraph `BaseStore` (also via MySQL) for cross-thread knowledge accumulation |

### Phase 3 — Async & Long-Running

| Feature | Description |
|---------|-------------|
| **Celery dispatch** | Offload long research runs to Celery (matching the `demo_workflow` pattern) |
| **progress polling** | `GET /deep-research/{thread_id}/status` endpoint |
| **human-in-the-loop** | `interrupt_on` for source approval before synthesis |

### Phase 4 — Quality & Observability

| Feature | Description |
|---------|-------------|
| **structured output** | `response_format` with typed `DeepResearchResponse` schema |
| **todo middleware** | Explicit todo list tracking for multi-step plans |
| **summarization** | Automatic context compression for long runs |
| **LangSmith tracing** | Opt-in via `LANGSMITH_API_KEY` when ready |

---

## Testing

```bash
# Sync endpoint (single line to avoid shell line-continuation issues)
curl -X POST http://thor.local:8090/workflows/deep-research/run -H "Content-Type: application/json" -H "X-API-Key: <HARNESS_API_KEY>" -d '{"query": "What are the latest developments in quantum computing?"}'

# Streaming endpoint
curl -N -X POST http://thor.local:8090/workflows/deep-research/run/stream -H "Content-Type: application/json" -H "X-API-Key: <HARNESS_API_KEY>" -d '{"query": "latest quantum computing news"}'

# Siri voice
# "deep research what are the latest AI regulations in Europe"
```
