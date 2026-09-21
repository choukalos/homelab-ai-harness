# mcp_filesystem

Read/write file system access MCP server scoped to `/home/chuck/workspace`.

## Tools

| Tool | Description |
|---|---|
| `read_file(path)` | Read a file's contents (max 1 MB) |
| `write_file(path, content)` | Write content to a file (creates or overwrites, max 5 MB) |
| `create_directory(path)` | Create a directory (parents created if needed) |
| `delete_file(path)` | Delete a file (directories are refused) |
| `list_directory(path)` | List directory contents with metadata |

## Security

- **Path scoping**: Only paths under `/home/chuck/workspace` are accessible.
  Configurable via `SCOPE_PATH` environment variable.
- **Path traversal protection**: `..` segments are rejected in all paths.
- **Size limits**: Files read exceed 1 MB (configurable) are rejected.
  Writes exceed 5 MB (configurable) are rejected.
- **Delete protection**: Only files can be deleted; directory deletion is refused.
- **Resolved path verification**: All paths are resolved to real absolute paths
  before validation to prevent symlink-based escapes.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `SCOPE_PATH` | `/home/chuck/workspace` | Single scoped root directory for all operations |
| `MAX_FILE_SIZE` | `1048576` | Maximum file size for reads in bytes (default 1 MB) |
| `MAX_WRITE_SIZE` | `5242880` | Maximum file size for writes in bytes (default 5 MB) |
| `MCPS_HOST` | `0.0.0.0` | Bind address for SSE transport |

## Transport

SSE (HTTP) on `0.0.0.0:8000`, path `/sse`.

## Deployment

### Docker Compose

The service is defined in `compose/compose.mcp.yml` with a volume mount for
the scoped path. The volume maps the host path into the container at the same
absolute path so the scoping checks work correctly.

```yaml
mcp_filesystem:
  build:
    context: ../mcp/servers/filesystem
  container_name: mcp_filesystem
  volumes:
    - /home/chuck/workspace:/home/chuck/workspace
  environment:
    - SCOPE_PATH=/home/chuck/workspace
  restart: unless-stopped
  networks:
    - ai-net
```

### LiteLLM Registration

Registered in `litellm/config.yml` under `mcp_servers:` with SSE transport:

```yaml
mcp_filesystem:
  url: http://mcp_filesystem:8000/sse
  transport: sse
  allow_all_keys: true
```

## Architecture

See [mcp/README.md](../README.md) for the MCP server architecture overview.