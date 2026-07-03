# Thor MCP Architecture

> Phase 4.5 — Define the MCP server architecture for the new platform.
> Date: 2026-07-03
> Status: Documentation only. Do not implement yet. Do not register tools with live LiteLLM.

---

## Principle

MCP servers are discrete, independently deployable tool providers. Each one exposes a specific set of tools with clear permissions, paths, and channel exposure.

```
Channel → Skill Runner → MCP Servers → Backend Services
```

Skills compose multiple MCP tools. MCP servers do not know about skills or channels.

---

## Recommended MCP Servers

| Server | Purpose | Backend |
|---|---|---|
| `mcp_search` | Web search via SearXNG | `searxng:8080` |
| `mcp_crawl` | Page fetching and content extraction | `crawl4ai:11235` |
| `mcp_knowledge` | Knowledge base read/write via Qdrant | `qdrant:6333` |
| `mcp_filesystem_readonly` | Read-only file access to workspace and media | `/home/chuck/workspace`, `/home/chuck/data/media` |
| `mcp_stocks` | Stock market data and financial lookups | External APIs |
| `mcp_homelab_status` | Homelab health, metrics, Docker state | `docker`, `victoria-metrics` |
| `mcp_media` | Media operations: image gen via ComfyUI, file operations | `${MATRIX_IP}:8188` |
| `mcp_home` | Home automation status (future, read-only) | Homebridge on Lego |

### Deferred

| Server | Reason |
|---|---|
| `mcp_code` | Coding workflows are complex with security implications. Revisit after other MCP servers are stable. |

---

## Server Specifications

### 1. `mcp_search`

| Field | Value |
|---|---|
| **Purpose** | Web search via SearXNG |
| **Tools** | `search(query, max_results?, categories?, language?)` |
| **Inputs** | Query string, optional filters |
| **Outputs** | List of results (title, URL, snippet, source) |
| **Read/write** | Read-only (queries SearXNG) |
| **Allowed paths** | `http://searxng:8080/search` |
| **Context impact** | Low — returns compact result summaries |
| **Channel exposure** | CLI, PI, Open WebUI (via skill runner) |
| **Security** | Read-only. No auth needed (internal network). Rate-limit at SearXNG. |

---

### 2. `mcp_crawl`

| Field | Value |
|---|---|
| **Purpose** | Fetch and extract content from web pages |
| **Tools** | `crawl(url, max_chars?, format?)` |
| **Inputs** | URL, optional max characters and output format |
| **Outputs** | Extracted text/markdown from the page |
| **Read/write** | Read-only (fetches external URLs) |
| **Allowed paths** | `http://crawl4ai:11235` |
| **Context impact** | Medium — page content can be large; enforce max_chars |
| **Channel exposure** | CLI, PI (via skill runner) |
| **Security** | Read-only. Crawl4AI runs in container. Rate-limit to avoid abuse. Block internal IPs from being crawled. |

---

### 3. `mcp_knowledge`

| Field | Value |
|---|---|
| **Purpose** | Knowledge base query and curated ingestion via Qdrant |
| **Tools** | `search(query, collection, top_k?)`, `ingest(file_path, collection)`, `delete(collection, filter)` |
| **Inputs** | Query string or file path, collection name |
| **Outputs** | Matching documents with scores, or ingestion confirmation |
| **Read/write** | Read (search) + Write (ingest/delete, curated only) |
| **Allowed paths** | `http://qdrant:6333` |
| **Context impact** | Low-Medium — returns compact document chunks |
| **Channel exposure** | CLI (full), Open WebUI (read-only), n8n (ingest-only) |
| **Security** | Collection-level permissions enforced by skill runner. Ingestion requires manual approval or curated-only flag. Delete requires admin channel. |

---

### 4. `mcp_filesystem_readonly`

| Field | Value |
|---|---|
| **Purpose** | Read-only file system access for workspace and media |
| **Tools** | `read_file(path)`, `list_directory(path)`, `search_files(pattern, path?)` |
| **Inputs** | File path, glob pattern |
| **Outputs** | File contents, directory listing, search results |
| **Read/write** | Read-only |
| **Allowed paths** | `/home/chuck/workspace/**`, `/home/chuck/data/media/**` |
| **Context impact** | Low-Medium — file contents can be large; enforce size limits |
| **Channel exposure** | CLI, PI, Claude Code (via skill runner or direct) |
| **Security** | Strict read-only. Path validation prevents escape from allowed directories. No symlink following. Size limits per read. |

---

### 5. `mcp_stocks`

| Field | Value |
|---|---|
| **Purpose** | Stock market data, prices, financial lookups |
| **Tools** | `get_price(ticker)`, `get_historical(ticker, period?)`, `get_news(ticker)`, `get_financials(ticker)` |
| **Inputs** | Ticker symbol, optional period |
| **Outputs** | Price data, historical series, news snippets, financial statements |
| **Read/write** | Read-only (external APIs) |
| **Allowed paths** | External APIs (Yahoo Finance, Alpha Vantage, or similar) |
| **Context impact** | Low — returns compact structured data |
| **Channel exposure** | CLI, n8n, PI (via skill runner) |
| **Security** | Read-only. API keys stored in environment. Rate-limit per external provider limits. |

---

### 6. `mcp_homelab_status`

| Field | Value |
|---|---|
| **Purpose** | Homelab health monitoring, Docker state, service status |
| **Tools** | `docker_ps()`, `service_status(service_name)`, `get_metrics(query?)`, `get_logs(service, tail?)` |
| **Inputs** | Service name, optional query or tail count |
| **Outputs** | Container status, metrics data, log lines |
| **Read/write** | Read-only |
| **Allowed paths** | Docker socket (read-only), Victoria Metrics |
| **Context impact** | Low — returns compact status data |
| **Channel exposure** | CLI (full), n8n (status checks) |
| **Security** | Read-only Docker inspection. No container control. Metrics query limited to pre-approved Victoria Metrics endpoints. |

---

### 7. `mcp_media`

| Field | Value |
|---|---|
| **Purpose** | Media operations: image generation, file serving |
| **Tools** | `generate_image(prompt, width?, height?, steps?)`, `get_media_file(path)`, `list_media(directory?)` |
| **Inputs** | Prompt, dimensions, file path |
| **Outputs** | Generated image file, media file, directory listing |
| **Read/write** | Read (get/list) + Write (generate to `/data/media`) |
| **Allowed paths** | `${MATRIX_IP}:8188` (ComfyUI), `/home/chuck/data/media/**` |
| **Context impact** | Medium — image generation is async; returns job ID or file path |
| **Channel exposure** | Open WebUI, CLI, n8n (via skill runner) |
| **Security** | ComfyUI accessed over LAN. Output directory is write-scoped to `/data/media`. Prompt sanitized. Rate-limit generation. |

---

### 8. `mcp_home`

| Field | Value |
|---|---|
| **Purpose** | Home automation status (read-only) |
| **Tools** | `get_device_status(device_id?)`, `get_all_devices()`, `get_scene_status(scene_name?)` |
| **Inputs** | Optional device ID or scene name |
| **Outputs** | Device states, scene states |
| **Read/write** | Read-only (no device control yet) |
| **Allowed paths** | Homebridge on Lego (`192.168.4.x:8581`) |
| **Context impact** | Low — compact status data |
| **Channel exposure** | CLI, Portal (future) |
| **Security** | Read-only. No device control. Future write access requires explicit approval. Homebridge stays on Lego. |

---

## Channel → MCP Exposure Matrix

| MCP Server | CLI | PI | Open WebUI | Siri | n8n | llm.choukalos.com | Portal |
|---|---|---|---|---|---|---|---|
| `mcp_search` | ✅ | ✅ | ✅ | — | ✅ | — | — |
| `mcp_crawl` | ✅ | ✅ | — | — | ✅ | — | — |
| `mcp_knowledge` | ✅ | ✅ | Read | — | Ingest | — | Read |
| `mcp_filesystem_readonly` | ✅ | ✅ | — | — | ✅ | — | — |
| `mcp_stocks` | ✅ | — | — | — | ✅ | — | — |
| `mcp_homelab_status` | ✅ | — | — | — | ✅ | — | — |
| `mcp_media` | ✅ | — | ✅ | — | ✅ | — | — |
| `mcp_home` | ✅ | — | — | — | — | — | Read (future) |

---

## Rules

- **Documentation only.** Do not implement yet.
- **Do not register tools with live LiteLLM.**
- MCP servers run as separate processes or containers on Thor.
- Each server has its own manifest defining tools, permissions, and allowed paths.
- The skill runner composes MCP tools into workflows — MCP servers do not know about skills.
- `mcp_code` is deferred to future exploration.
