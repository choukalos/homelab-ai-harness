# Skill: research_brief

Lightweight web research with sub-query generation and summarization.

## Overview

The `research_brief` skill provides a fast, focused research workflow ideal for voice-first interfaces and quick lookups. It:

1. **Generates sub-queries** — Uses an LLM (via LiteLLM) to break a research topic into 2-3 targeted search sub-queries.
2. **Searches the web** — Queries SearXNG via MCP `mcp_search` (through LiteLLM) or directly via HTTP, with optional news search.
3. **Summarizes findings** — Uses the LLM to synthesize search results into a concise, cited summary.

This is a lighter alternative to `deep_research` — no crawling, no knowledge base search, no artifact files. Designed for quick factual queries and trending topics.

## Workflow

```
User: "Brief me on the latest Pi SDK release"
  │
  ├─► 1. LLM generates 2-3 sub-queries from the topic:
  │     e.g. "Pi SDK 2026 release", "Pi SDK new features", "Pi SDK changelog"
  │
  ├─► 2. Search each sub-query via MCP mcp_search (or SearXNG directly):
  │     collect top results (title, url, snippet) per query
  │
  ├─► 3. Deduplicate and cap results
  │
  └─► 4. LLM summarizes results into a concise brief
         (cited with source URLs)
```

## Usage

### Via Skill Runner (POST /api/chat)

```bash
curl -X POST http://localhost:8091/api/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Brief me on the latest Pi SDK release", "skill": "research_brief"}'
```

### Standalone CLI

```bash
cd skills/research_brief
python skill.py --topic "Pi SDK 2026 release"
python skill.py --topic "homelab container orchestration" --num-sub-queries 2 --include-news
python skill.py --topic "test" --dry-run
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM proxy endpoint |
| `LITELLM_API_KEY` | *(empty)* | LiteLLM API key |
| `SEARXNG_URL` | `http://searxng:8080` | Direct SearXNG URL (fallback) |
| `RESEARCH_BRIEF_MODEL_ALIAS` | `local/qwen-coder` | Model for sub-query gen and summarization |
| `RESEARCH_BRIEF_MAX_RUNTIME` | `120` | Total max runtime (seconds) |

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | Yes | — | Research topic or question |
| `num_sub_queries` | int | No | 3 | Number of sub-queries (1-5) |
| `max_results_per_query` | int | No | 5 | Results per sub-query (cap 10) |
| `include_news` | bool | No | false | Also search news sources |

## Outputs

| Field | Description |
|---|---|
| `summary` | Concise summarized brief |
| `sub_queries` | List of generated sub-queries |
| `search_results` | List of top search results with source info |
| `total_results` | Total number of results collected |
| `model_alias` | Model used for LLM calls |
| `error` | Error message (if any) |

## Differences from `deep_research`

| Feature | research_brief | deep_research |
|---|---|---|
| Max runtime | 120s | 900s |
| Max sources | 30 (3×10) | 15 |
| Crawling | No | Yes |
| Knowledge base | No | Yes |
| Artifacts | No | Yes |
| Sub-query generation | Yes (LLM) | No (static variants) |
| Complexity | Lightweight | Heavy |

## Search Backend

The skill uses two search paths (in priority order):

1. **MCP mcp_search via LiteLLM** — Calls `search_web` (and optionally `search_news`) through the LiteLLM MCP gateway. This is the primary path when running through the skill runner.
2. **Direct SearXNG** — Falls back to querying SearXNG directly via HTTP if the LiteLLM MCP path is unavailable. This is useful for standalone/CLI use.

## Error Handling

- **No results**: Returns a summary stating no results found.
- **MCP unavailable**: Falls back to direct SearXNG.
- **SearXNG unavailable**: Returns error with available sub-queries.
- **LLM failure**: Falls back to listing raw search results without summarization.
- **Timeout**: Returns partial results collected so far.

## Security

- **Read-only**: No writes, no admin operations.
- **Timeout enforcement**: Hard timeout prevents runaway processes.
- **Result limits**: Hard caps on results per query.
- **No sensitive data**: The skill itself doesn't introduce sensitive data.

## File Structure

```
skills/research_brief/
├── README.md       ← This file
├── skill.yml       ← Skill manifest
└── skill.py        ← Implementation
```

## References

- [deep_research Skill](../deep_research/README.md) — Heavier research with crawling and artifacts
- [MCP Search Server](../../mcp/servers/search/README.md) — SearXNG-backed search
- [Thor Skill Architecture](../../docs/thor_skill_architecture.md) — Skill manifest format