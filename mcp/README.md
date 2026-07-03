# MCP Servers

MCP (Model Context Protocol) servers provide reusable, read-mostly tools that skills and channels can compose.

## Servers

| Server | Status | Notes |
|---|---|---|
| [search](servers/search/) | | SearXNG-backed web search |
| [crawl](servers/crawl/) | | Crawl4AI-backed page extraction |
| [knowledge](servers/knowledge/) | | Qdrant KB retrieval (read-only) |
| [filesystem_readonly](servers/filesystem_readonly/) | | Safe file/directory reading on allowed paths |
| [stocks](servers/stocks/) | | Financial data, market lookups |
| [homelab_status](servers/homelab_status/) | | Homelab infrastructure health and metrics |
| [media](servers/media/) | | Media asset lookup (LAN-only) |
| [home](servers/home/) | | Home automation/status (LAN-only) |

## Deferred

- `mcp_code` — coding workflows (repo listing, code search, git). Revisit after other servers are stable.

## Shared

Code shared across MCP servers lives in [shared/](shared/).

## Rules

- MCP servers are stateless and isolated
- Read-only by default; writes require explicit approval gates
- Skills compose MCP tools; MCP servers do not know about skills
- No direct public exposure — always routed through skills or LiteLLM tool bundles
