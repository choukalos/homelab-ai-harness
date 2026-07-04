# demo_workflow Skill

One-page clickable demo via deep agents. Takes a prompt, researches, builds, and verifies an interactive HTML demo.

## Overview

This skill is a thin wrapper around the AI Harness demo endpoint. It sends the prompt to the Harness, which orchestrates deep agents to research, build, and verify an interactive HTML page — then returns the result metadata.

## Inputs

| Parameter | Type     | Required | Description                        |
|-----------|----------|----------|------------------------------------|
| prompt    | string   | yes      | The demo topic or description.     |

## Output

Returns the AI Harness response, typically including:

- `thread_id` — Unique thread identifier for the demo run
- `title` — Generated title for the demo
- `slug` — URL-safe slug
- `status` — Current status (e.g., `running`, `completed`)
- `html_path` — Path to the generated HTML file
- `artifact_path` — Path to the saved metadata JSON
- `prompt` — The original prompt

## Usage

### Via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/demo_workflow/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Build a solar system simulator with orbiting planets"}'
```

### Standalone (CLI)

```bash
cd /home/chuck/homelab/skills/demo_workflow
python skill.py --prompt "Build a solar system simulator"
python skill.py --prompt "Build a solar system simulator" --dry-run
python skill.py --prompt "Build a solar system simulator" --harness-url http://localhost:8090
```

## Configuration

| Environment Variable          | Default                        | Description                     |
|-------------------------------|--------------------------------|---------------------------------|
| DEMO_WORKFLOW_HARNESS_URL     | `http://ai-harness:8090`       | AI Harness base URL             |
| DEMO_WORKFLOW_MAX_RUNTIME     | `600`                          | Max runtime in seconds          |
| DEMO_WORKFLOW_ARTIFACT_DIR    | `/home/chuck/data/media/presentations` | Artifact output directory |

## Artifact

Metadata is saved as JSON to the artifact directory with filename pattern:
`demo_{timestamp}_{slug}.json`

## Constraints

- **Max runtime:** 600 seconds (10 minutes)
- **No MCP tools:** Direct HTTP call to AI Harness only
- **Stateless:** No rollback or cleanup needed
