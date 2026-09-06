# MCP Servers

Standalone MCP server implementations. Each server runs in its own container with SSE transport.

## Servers

- `search/` — Web search via SearXNG
- `knowledge/` — Curated KB retrieval via Qdrant
- `crawl/` — Web page crawling via Crawl4AI
- `filesystem_readonly/` — Read-only filesystem access

See [`docs/thor_mcp_architecture.md`](../../docs/thor_mcp_architecture.md) for architecture details.
