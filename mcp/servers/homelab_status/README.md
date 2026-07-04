# MCP Homelab Status Server

Docker and system monitoring tools. Lists containers, checks service health, reports CPU/memory/disk usage, and retrieves container logs. Runs as an MCP server over streamable-http transport.

## Tools

| Tool | Description | Parameters |
|---|---|---|
| `docker_ps` | List all containers with status, image, ports | _(none)_ |
| `service_status` | Check if a specific container is running/healthy | `service_name` (str) |
| `system_info` | CPU, memory, disk usage | _(none)_ |
| `container_logs` | Last N lines from container logs | `service_name` (str), `tail` (int, default 100) |

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker daemon socket |
| `MCPS_HOST` | `0.0.0.0` | Bind address for streamable-http |

## Safety

- **Read-only access**: Container logs and status only; no container manipulation
- **Log limits**: Max 5000 lines per request
- **Docker socket**: Mounted read-only (`:ro`) in Docker Compose

## Usage

### Docker Compose

Add to `compose/compose.mcp.yml`:

```yaml
mcp_homelab_status:
  build: ../mcp/servers/homelab_status
  ports:
    - "8001:8000"
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

### Local Development

```bash
cd mcp/servers/homelab_status
pip install -e .
python server.py
```

### Python API

```python
from server import docker_ps, service_status, system_info, container_logs

# List all containers
containers = docker_ps()
for c in containers:
    print(f"  {c['name']}: {c['state']}")

# Check a service
status = service_status("portainer")
print(f"  {status['state']}, health: {status['health']}")

# System metrics
info = system_info()
print(f"  CPU: {info['cpu']['percent']}%, Memory: {info['memory']['percent']}%")

# Container logs
logs = container_logs("portainer", tail=50)
for line in logs["logs"][:5]:
    print(f"  {line}")
```

## Architecture

This server is part of the Thor MCP server family. See [mcp/README.md](../README.md) for the overall architecture.
