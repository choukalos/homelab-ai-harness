# mcp_knowledge

Read-only Qdrant knowledge base retrieval MCP server.

## Overview

This MCP server provides read-only access to curated knowledge base collections stored in Qdrant. It enforces a collection allowlist, supports compact snippet search, full document retrieval, and metadata-based change scanning.

## Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `kb_search` | Vector/keyword search in a curated collection | `query`, `top_k` (default 5, cap 20), `collection` (default `homelab_curated`) |
| `kb_get_document` | Retrieve full document by ID | `doc_id` |
| `kb_list_collections` | List available curated collections | *(none)* |
| `kb_recent_changes` | Show recent changes via metadata scan | `days` (default 7) |

## Collection Allowlist

Only the following collections are accessible:

- **family_curated** — Family knowledge: recipes, events, notes
- **homelab_curated** — Homelab documentation, runbooks, config notes
- **coding_curated** — Project architecture, API docs, coding standards

The following collections are **NOT** accessible by default:

- `private_curated` — Sensitive data (never exposed to non-admin channels)
- `finance_curated` — Financial data (requires explicit approval)

The allowlist is hardcoded in `server.py` and enforced on every request.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant endpoint URL |
| `QDRANT_TIMEOUT` | `15` | HTTP timeout in seconds |

### Running in Docker (internal network)

```bash
QDRANT_URL=http://qdrant:6333 python -m server
```

### Running from host

```bash
QDRANT_URL=http://192.168.4.54:6333 python -m server
```

### Running with pipx / uv

```bash
# Install dependencies
uv sync

# Run directly
python -m server
```

## Security

- **Read-only**: No write, update, delete, or reindex operations are exposed.
- **Collection allowlist**: Every request validates the collection against a hardcoded allowlist.
- **Compact snippets**: Search results return truncated snippets (max 300 chars) to minimize context impact.
- **Full docs only by doc_id**: Full document content is available only through `kb_get_document` with a specific ID.
- **No arbitrary file access**: All data access goes through Qdrant API calls only.

## Architecture

```
Client (LiteLLM / Skill Runner) → MCP (stdio) → Qdrant (http)
                                   ↓
                              Collection allowlist enforcement
```

- Uses the MCP Python SDK (`mcp` package) with stdio transport
- Communicates with Qdrant via `qdrant-client` async client
- Stateless: creates a new client per tool call

## Testing

```bash
# Install test dependencies
uv sync --extra test

# Run tests (all mocked, no Qdrant required)
pytest tests/test_knowledge.py -v
```

## Limitations

- Search is payload-based (keyword matching on `content`, `text`, `body`, `title`, `summary` fields)
- Vector similarity search requires pre-embedded vectors in Qdrant
- `kb_recent_changes` relies on `ingested_at`/`updated_at` metadata fields existing in payloads
- Collections not yet created in Qdrant will show as "not_found" in `kb_list_collections`
