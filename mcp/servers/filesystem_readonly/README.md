# mcp_filesystem_readonly

Read-only file system access MCP server with path allowlisting and size limits.

## Tools

| Tool | Description |
|---|---|
| `read_file(path)` | Read a file's contents (max 1 MB) |
| `list_directory(path)` | List directory contents with metadata |
| `search_files(pattern, path?)` | Glob-based file search in allowed dirs |

## Security

- **Path allowlisting**: Only paths under configured allowed roots are accessible.
  Default: `/home/chuck/workspace`, `/home/chuck/data/media`
- **Path traversal protection**: `..` segments are rejected in paths and patterns.
- **Size limits**: Files exceeding 1 MB (configurable) are rejected.
- **Read-only**: No writes, deletes, or modifications.
- **Result limits**: Search results capped at 200 (configurable).

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `ALLOWED_PATHS` | `/home/chuck/workspace,/home/chuck/data/media` | Comma-separated allowed root paths |
| `MAX_FILE_SIZE` | `1048576` | Maximum file size in bytes (default 1 MB) |
| `MAX_SEARCH_RESULTS` | `200` | Maximum search results returned |
| `SEARCH_GLOB_LIMIT` | `1000` | Max matches per root before stopping |
| `MCPS_HOST` | `0.0.0.0` | Bind address for SSE transport |

## Transport

SSE (Server-Sent Events) on `0.0.0.0:8000`.

## Deployment

### Docker Compose

The service is defined in `compose/compose.mcp.yml` with volume mounts for both
allowed paths. Volume mounts map the host paths into the container at the same
absolute paths so the allowlist checks work correctly.

```yaml
mcp_filesystem_readonly:
  build:
    context: ../mcp/servers/filesystem_readonly
  container_name: mcp_filesystem_readonly
  volumes:
    - /home/chuck/workspace:/home/chuck/workspace:ro
    - /home/chuck/data/media:/home/chuck/data/media:ro
  restart: unless-stopped
  networks:
    - ai-net
```

### LiteLLM Registration

Registered in `litellm/draft/config.phase15.yml` with SSE transport:

```yaml
mcp_filesystem_readonly:
  url: http://mcp_filesystem_readonly:8000/sse
  transport: sse
  allow_all_keys: true
```

## Architecture

See [mcp/README.md](../README.md) for the MCP server architecture overview.
