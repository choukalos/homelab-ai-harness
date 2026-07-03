# MCP Search Server

Read-only web search backed by SearXNG. Runs as an MCP server over stdio transport.

## Tools

| Tool | Description | Parameters |
|---|---|---|
| `search_web` | General web search | `query` (str), `max_results` (int, default 5, cap 20) |
| `search_recent` | Recent results (past N days) | `query` (str), `days` (int, default 7), `max_results` (int, default 5, cap 20) |
| `search_news` | News-specific search | `query` (str), `max_results` (int, default 5, cap 20) |

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG base URL |
| `SEARXNG_TIMEOUT` | `10` | HTTP request timeout in seconds |

For container deployment on the homelab Docker network:
```bash
export SEARXNG_URL=http://searxng:8080
```

For local development from the host:
```bash
export SEARXNG_URL=http://192.168.4.54:8088
```

## Usage

### Direct (stdio)

```bash
# Install dependencies
pip install -e .

# Run server (reads/writes stdin/stdout as JSON-RPC)
python -m server
```

### With an MCP client

Any MCP client that supports stdio transport can connect. For example, with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python -m server
```

### Python API

```python
import asyncio
from server import search_web, search_recent, search_news

async def main():
    results = await search_web("homelab setup", max_results=5)
    for r in results:
        print(f"{r['title']}: {r['url']}")
        print(f"  {r['snippet']}\n")

    recent = await search_recent("AI news", days=7, max_results=3)
    for r in recent:
        print(f"{r['title']}: {r['url']}")

    news = await search_news("technology", max_results=5)
    for r in news:
        print(f"{r['title']}: {r['url']}")

asyncio.run(main())
```

## Result Format

Each result is a compact dict:

```json
{
    "title": "Page title",
    "url": "https://example.com/page",
    "snippet": "First 200 characters of the description…"
}
```

## Safety

- **Read-only**: No writes to SearXNG or any backend
- **No crawling**: Results come from SearXNG aggregators only
- **No browser automation**: Pure HTTP API
- **Timeouts**: 10s default HTTP timeout prevents hangs
- **Result limits**: Capped at 20 results per call
- **Snippet truncation**: Max 200 characters per snippet

## Testing

```bash
pip install -e ".[test]"
pytest tests/ -v
```

Tests use mocked HTTP responses and do not require a running SearXNG instance.

## Architecture

This server is part of the Thor MCP server family. See [mcp/README.md](../README.md) for the overall architecture and [docs/thor_mcp_architecture.md](../../../docs/thor_mcp_architecture.md) for the `mcp_search` specification.
