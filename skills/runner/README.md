# Thor Skill Runner

Lightweight skill orchestration API that runs locally alongside the current AI Harness.
Replaces the monolithic Harness with a modular, manifest-driven skill runner.

## Design

```
Channel → Skill Runner → Workflow (MCP tools + model calls) → Artifact
```

- **Port**: 8091 (development only; never 8090 which is the current Harness)
- **Storage**: In-memory job store for dev (no database)
- **Artifacts**: Written to `/home/chuck/data/media/<skill_dir>/`
- **Logging**: Structured logs to stdout + `/home/chuck/homelab/logs/skill_runner/skill_runner.log`

## Endpoints

### POST /skills/{skill_name}

Launch a skill job.

```json
{
  "params": {"query": "Topic to research", "depth": "comprehensive"},
  "requester": "chuck",
  "channel": "cli",
  "dry_run": false,
  "tool_bundle": "bundle_research",
  "model_alias": "local/qwen-coder"
}
```

### GET /skills/jobs/{job_id}

Get job status. Returns the full job record.

```json
{
  "job_id": "abc123def456",
  "skill": "deep_research",
  "status": "completed",
  "created_at": "2026-07-03T10:00:00Z",
  "completed_at": "2026-07-03T10:05:00Z",
  "summary": "Research completed. Found 8 key sources.",
  "artifact_path": "/home/chuck/data/media/research_reports/deep_research_2026-07-03T10-05-00_topic.md",
  "requester": "chuck",
  "channel": "cli",
  "dry_run": false,
  "tool_bundle": "bundle_research",
  "model_alias": "local/qwen-coder"
}
```

### GET /skills/jobs/{job_id}/artifact

Retrieve the skill's output artifact file. Returns the raw file content with appropriate Content-Type.

### POST /skills/jobs/{job_id}/approve

Approve a job waiting at an approval gate and resume execution.

### POST /skills/jobs/{job_id}/cancel

Cancel a pending or running job.

### GET /health

Health check. Returns status and total job count.

## Job Status Values

| Status | Meaning |
|---|---|
| `pending` | Queued, waiting for worker |
| `running` | Actively executing |
| `completed` | Finished successfully |
| `failed` | Error during execution |
| `awaiting_approval` | Waiting for manual approval gate |
| `cancelled` | Cancelled by user |

## Features

### Dry-Run Mode

Set `dry_run: true` in the launch request. The job is logged and completed without executing any real work. Useful for testing the API shape.

Global dry-run mode can be enabled via environment variable:
```bash
export SKILL_RUNNER_DRY_RUN=true
```

### Approval Gates

Certain skills (e.g. `family_kb_ingest`, `repo_maintenance`) automatically enter `awaiting_approval` status. Use `POST /skills/jobs/{job_id}/approve` to resume them.

### Tool Bundle Declaration

Jobs can declare which tool bundle they need via the `tool_bundle` field. In Phase 10, this maps to LiteLLM tool bundles.

### Model Alias Declaration

Jobs declare which model alias to use via the `model_alias` field (e.g. `local/qwen-coder`, `local/qwen-long`).

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `SKILL_RUNNER_PORT` | `8091` | HTTP listen port |
| `SKILL_RUNNER_HOST` | `0.0.0.0` | HTTP bind address |
| `ARTIFACT_ROOT` | `/home/chuck/data/media` | Root for artifact storage |
| `SKILL_RUNNER_LOG_DIR` | `/home/chuck/homelab/logs/skill_runner` | Log file directory |
| `SKILL_RUNNER_DRY_RUN` | `false` | Global dry-run mode |

## Running

```bash
cd skills/runner

# With uv + venv
uv venv
source .venv/bin/activate
uv pip install -e .

# Run directly with uvicorn
uvicorn main:app --host 0.0.0.0 --port 8091

# Or use the project entry point
python -m main
```

## Known Skills

Skills live in sibling directories under `skills/`. Each skill has a manifest and implementation module.

| Skill | Purpose | Artifact Directory |
|---|---|---|
| `siri_ask` | Quick Q&A for Siri | `siri_outputs/` |
| `deep_research` | Multi-source research | `research_reports/` |
| `investment_brief` | Investment analysis | `investment_briefs/` |
| `presentation_build` | Presentation generation | `presentations/` |
| `code_review` | Code review reports | `code_reviews/` |
| `repo_maintenance` | Repository hygiene | `code_reviews/` |
| `family_kb_ingest` | KB ingestion (requires approval) | None (Qdrant) |
| `morning_brief` | Daily briefing | `homelab_reports/` |
| `homelab_report` | Homelab health report | `homelab_reports/` |

## Testing

```bash
# Quick smoke test
curl http://localhost:8091/health

# Launch a dry-run job
curl -X POST http://localhost:8091/skills/deep_research \
  -H 'Content-Type: application/json' \
  -d '{"params":{"query":"test"},"dry_run":true}'

# Check job status
curl http://localhost:8091/skills/jobs/<job_id>
```

## Rules

- **Do not** bind to production port 8090.
- **Do not** replace the current AI Harness.
- **Do not** update Caddy or Cloudflare configuration.
- **Do not** touch production services or data.
- New runner lives in a separate directory until proven through local testing.
- See `docs/thor_ai_harness_rebuild.md` for the migration strategy.
