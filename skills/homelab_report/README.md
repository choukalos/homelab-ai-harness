# Skill: homelab_report

Generate a homelab infrastructure health report by calling MCP tools via
LiteLLM and synthesizing a concise Markdown report through the LLM.

## Inputs

| Parameter | Type   | Required | Default | Description                                      |
|-----------|--------|----------|---------|--------------------------------------------------|
| `scope`   | string | No       | `full`  | `full` (all), `containers` (Docker only), `system` (CPU/RAM/disk) |

## Tools Used

- **mcp_homelab_status** — Docker and system monitoring MCP server
  - `docker_ps()` — List all containers with status, image, ports
  - `system_info()` — CPU, memory, disk usage
  - `container_logs(name, tail)` — Recent logs from unhealthy containers

## Workflow

1. Call `mcp_homelab_status.docker_ps()` and `system_info()` via the
   LiteLLM MCP proxy (streamable-http transport).
2. If scope is `full`, collect logs for unhealthy/exited containers.
3. Format raw data into a plain-text summary.
4. Send the summary to the LLM (`local/qwen-coder`) with a system prompt
   for concise Markdown report generation.
5. Save the report to `/home/chuck/data/media/homelab_reports/`.

## Output

A Markdown report with:
- Health score (✅ / ⚠️ / ❌)
- Container status summary
- System resource usage
- Issue highlights and recent logs

## Usage

### Via Skill Runner API

```bash
curl -X POST http://localhost:8091/skills/homelab_report \
  -H "Content-Type: application/json" \
  -d '{"params": {"scope": "full"}}'
```

### Standalone Test

```bash
python skill.py --scope full          # Mock execution with simulated data
python skill.py --scope containers    # Containers only
python skill.py --dry-run             # Print config without calling anything
```
