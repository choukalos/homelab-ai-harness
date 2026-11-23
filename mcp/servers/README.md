# MCP Servers

Standalone MCP server implementations. Each server runs in its own container with SSE transport.

## Servers

- `search/` — Web search via SearXNG
- `knowledge/` — Curated KB retrieval via Qdrant
- `crawl/` — Web page crawling via Crawl4AI
- `filesystem_readonly/` — Read-only filesystem access
- `kanban/` — LLM task queue + grooming + execution (stateful self-contained service; **MCP is the only mutation interface — 27 tools incl. interactive grooming, board_status (task + idea pipeline), owner attribution via USER_KEYS, file intake (`stage_file`/`stage_ref`) + spec-path preflight (2026-11-23)**; Fastify web UI = read-only status view, LAN-only at `thor.local:3000`; streamable-HTTP MCP at `POST /mcp`; MySQL on Thor; per-key tool scoping — 2026-11-21)

See [`docs/thor_mcp_architecture.md`](../../docs/thor_mcp_architecture.md) for architecture details.
