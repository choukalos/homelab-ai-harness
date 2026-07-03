# Skill: deep_research

Multi-source deep research with cited markdown reports and artifact generation.

## Purpose

Execute a structured, repeatable research workflow that searches the web and internal knowledge base, collects and deduplicates sources, optionally crawls pages for deeper content, and synthesizes a fully cited markdown research report.

Designed for:
- Multi-source fact-checking and analysis
- In-depth topic research (2-15 minutes)
- Repeatability — same query produces consistent results
- Cited output — every claim references a source

**NOT** designed for:
- Quick questions (use `siri_ask` instead)
- Write operations or admin tasks
- Unbounded browsing

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | The research topic or question. |
| `depth` | string | No | `comprehensive` | Research depth: `quick`, `comprehensive`, or `exhaustive`. |
| `max_sources` | integer | No | `10` | Maximum number of sources to consult (hard cap: 30). |

### Depth Settings

| Depth | Search Queries | Results/Query | Max Sources | Crawl Top | KB Search |
|---|---|---|---|---|---|
| `quick` | 1 | 5 | 5 | 0 (none) | No |
| `comprehensive` | 3 | 8 | 10 | 3 | Yes |
| `exhaustive` | 5 | 10 | 15 | 5 | Yes |

## Outputs

```json
{
  "summary": "2-3 paragraph executive summary of findings.",
  "report": "Full cited markdown report text...",
  "sources": [
    {"title": "Source title", "url": "https://...", "type": "web|news|kb:collection"}
  ],
  "artifact_path": "/home/chuck/data/media/research_reports/deep_research_2026-07-03T10-30-00_topic.md",
  "model_alias": "local/qwen-coder",
  "depth": "comprehensive"
}
```

### Report Structure

The generated markdown report contains:
1. **Summary** — Concise executive overview (2-3 paragraphs)
2. **Key Findings** — 3-5 bullet points of the most important results
3. **Full Report** — Detailed analysis organized into logical sections
4. **Limitations** — What was not covered or needs further research
5. **Source List** — Numbered list of all sources with title, URL, and type

Every factual claim includes a `[N]` citation referencing the source list.

## Research Workflow

```
                    ┌─────────────┐
   query  ────────► │  Validate   │
   depth            │  & Configure │
   max_sources      └──────┬──────┘
                           │
                   ┌───────▼────────┐
                   │  Phase 1:      │
                   │  Collect Sources│
                   │  - Web search   │
                   │  - KB search    │
                   │  - Deduplicate  │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Phase 2:      │
                   │  Crawl Top N   │
                   │  (if depth     │
                   │  allows)       │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Phase 3:      │
                   │  Synthesize    │
                   │  Report        │
                   │  (via model)   │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Phase 4:      │
                   │  Save Artifact │
                   └────────────────┘
```

## Required Tools

| Tool | Purpose | Backend |
|---|---|---|
| `mcp_search` | Web search | SearXNG (`searxng:8080`) |
| `mcp_crawl` | Page content extraction | Crawl4AI (`crawl4ai:11235`) |
| `mcp_knowledge` | Knowledge base search | Qdrant (`qdrant:6333`) |
| `model_chat` | Report synthesis | LiteLLM (`local/qwen-coder`) |

## Constraints

- **Max runtime:** 900 seconds (15 minutes, hard timeout via signal).
- **Max sources:** 30 absolute cap (depth-specific defaults are lower).
- **Read-only:** No writes, no admin operations, no browser automation.
- **No crawling beyond max_sources.**
- **No sensitive data exposure.**
- **No result caching** — each run is fresh.

## Model

- **Model alias:** `local/qwen-coder` (Qwen 3.6 27B)
- **Temperature:** 0.3 (deterministic, factual)
- **Max tokens:** 8000 (12000 for large source sets)

## Channels

- **CLI** (primary — via `python skill.py --query "..."`)
- **PI** (via skill runner API)
- **n8n** (via skill runner API)

## Runtime Configuration

Environment variables (optional, all have defaults):

| Variable | Default | Description |
|---|---|---|
| `DEEP_RESEARCH_MAX_RUNTIME` | `900` | Max runtime in seconds. |
| `DEEP_RESEARCH_MODEL_ALIAS` | `local/qwen-coder` | Model alias for report synthesis. |
| `DEEP_RESEARCH_ARTIFACT_DIR` | `/home/chuck/data/media/research_reports` | Artifact output directory. |
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM endpoint. |
| `LITELLM_API_KEY` | `""` | LiteLLM API key. |
| `MCP_SEARCH_URL` | `http://localhost:8080` | SearXNG search endpoint. |
| `MCP_CRAWL_URL` | `http://localhost:11235` | Crawl4AI endpoint. |
| `MCP_KNOWLEDGE_URL` | `http://localhost:6333` | Qdrant endpoint. |

## Artifact Storage

Reports are saved as markdown files:
```
/home/chuck/data/media/research_reports/deep_research_{timestamp}_{slug}.md
```

Example: `deep_research_2026-07-03T10-30-00_quantum-computing-2026.md`

Files are **NOT** automatically added to the knowledge base. Chuck manually promotes artifacts when appropriate.

## Usage via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/deep_research \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "query": "Latest developments in quantum computing 2026",
      "depth": "comprehensive",
      "max_sources": 10
    },
    "requester": "chuck",
    "channel": "cli"
  }'
```

Check status:
```bash
curl http://localhost:8091/skills/jobs/{job_id}
```

Retrieve artifact:
```bash
curl http://localhost:8091/skills/jobs/{job_id}/artifact -o report.md
```

## Standalone Testing

```bash
cd skills/deep_research

# Dry run (no network calls)
python skill.py --query "AI trends 2026" --dry-run

# Full run (requires LiteLLM and SearXNG running)
python skill.py --query "Quantum computing breakthroughs"

# With specific depth and source limit
python skill.py --query "Climate change 2026" --depth exhaustive --max-sources 15

# With custom LiteLLM URL
python skill.py --query "Test" --base-url http://localhost:4000 --api-key "sk-test"
```

## Rollback

On failure, the partial or error report is still saved as an artifact (with an error notice). No external state is modified — the skill is read-only. Delete the artifact file if the run should be fully discarded.

## See Also

- [Skill Architecture](../../docs/thor_skill_architecture.md) — Full skill design
- [MCP Architecture](../../docs/thor_mcp_architecture.md) — MCP server specifications
- [Model Alias Registry](../../docs/thor_model_alias_registry.md) — Model alias definitions
- [Artifact Strategy](../../docs/thor_artifact_strategy.md) — Artifact storage rules
- [Skill Runner](../runner/) — Runner API and implementation
