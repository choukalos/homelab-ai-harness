# mcp_crawl

Fetch and extract web page content via Crawl4AI. Runs as an MCP server over SSE transport.

## Tools

| Tool | Description | Parameters |
|---|---|---|
| `crawl_page` | Fetch and extract a web page | `url` (str, required), `format` (str, optional, default `"markdown"`), `max_chars` (int, optional, default 50000) |

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `CRAWL4AI_URL` | `http://crawl4ai:11235` | Crawl4AI base URL |
| `CRAWL_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `CRAWL_MAX_CONCURRENT` | `10` | Maximum concurrent crawls |
| `CRAWL_MAX_CHARS` | `50000` | Maximum characters returned per crawl |

For container deployment on the homelab Docker network:
```bash
export CRAWL4AI_URL=http://crawl4ai:11235
```

## Usage

### Container (SSE)

```bash
docker compose -f compose/compose.mcp.yml up -d mcp_crawl
```

The server listens on `0.0.0.0:8000` with SSE transport.

### Direct (SSE)

```bash
# Install dependencies
pip install -e .

# Run server
python -m server
```

## Result Format

Each crawl returns a dict:

```json
{
    "url": "https://example.com/page",
    "format": "markdown",
    "content": "# Page Title\n\nExtracted content…",
    "chars": 4520,
    "truncated": false
}
```

## Safety

- **Internal IP blocking**: Refuses to crawl private IP ranges (192.168.x.x, 10.x.x.x, 172.16-31.x.x, localhost)
- **Rate limiting**: Maximum 10 concurrent crawls (enforced via async semaphore)
- **Content truncation**: Output capped at 50000 characters, truncated at word boundary
- **URL validation**: Only `http://` and `https://` URLs accepted
- **Timeout protection**: 30 second default HTTP timeout prevents hangs

## Architecture

```
Client (LiteLLM / Skill Runner) → MCP (SSE) → Crawl4AI (http)
                                   ↓
                              IP blocking + rate limiting
```

- Uses the MCP Python SDK (`mcp` package) with SSE transport
- Communicates with Crawl4AI via `httpx` async client
- Stateless: creates a new httpx client per tool call
- Rate limited with `asyncio.Semaphore` for concurrent access control

## Testing

```bash
pip install -e ".[test]"
pytest tests/ -v
```
