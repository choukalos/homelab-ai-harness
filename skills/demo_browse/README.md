# demo_browse Skill

Scan the demos directory and keyword-match demos by title, description, and tags.

## Overview

This skill scans a configurable demos directory (default: `/home/chuck/data/media/demos/`) for interactive demo artifacts. It handles two types of demo files:

- **Workflow directories** — subdirectories containing `metadata.json` with rich metadata (title, description, tags, scores, URLs)
- **Flat HTML files** — standalone `.html` files from which title and metadata are extracted from `<title>` and `<meta>` tags

Results are ranked by a scoring algorithm that weights title matches highest, followed by tag and description matches.

## Inputs

| Parameter | Type     | Required | Description                                          |
|-----------|----------|----------|------------------------------------------------------|
| query     | string   | yes      | Search keywords to match against demos.              |
| demo_dir  | string   | no       | Root demos directory (default: `/home/chuck/data/media/demos/`). |
| limit     | integer  | no       | Max results to return (default: 20).                 |

## Output

Returns a JSON object with:

- `query` — The search query
- `demo_dir` — The directory scanned
- `total_demos` — Total number of demos found
- `matched_count` — Number of demos matching the query
- `limit` — Result limit applied
- `results` — Array of matched demo objects, each containing:
  - `title` — Demo title
  - `description` — Description text
  - `tags` — Array of tags
  - `path` — Filesystem path
  - `type` — `workflow_dir` or `flat_html`
  - `match_score` — Numeric match score
  - `matched_keywords` — Which keywords matched
  - Additional fields from metadata.json (slug, urls, scores, etc.)

## Usage

### Via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/demo_browse/run \
  -H "Content-Type: application/json" \
  -d '{"query": "todo app"}'
```

### Standalone (CLI)

```bash
cd /home/chuck/homelab/skills/demo_browse
python3 skill.py --query "todo"
python3 skill.py --query "notes app" --limit 5
python3 skill.py --query "demo" --demo-dir /home/chuck/data/media/demos
python3 skill.py --query "test" --dry-run
```

## Scoring Algorithm

Each keyword in the query is scored against every demo:

| Match Location | Points |
|----------------|--------|
| Title          | 10     |
| Tag            | 8      |
| Description    | 4      |

Results are sorted by total score (highest first).

## Configuration

| Environment Variable     | Default                        | Description                    |
|--------------------------|--------------------------------|--------------------------------|
| DEMO_BROWSE_DEMO_DIR     | `/home/chuck/data/media/demos` | Demos directory to scan        |
| DEMO_BROWSE_DEFAULT_LIMIT| `20`                           | Default result limit           |
| DEMO_BROWSE_MAX_RUNTIME  | `30`                           | Max runtime in seconds         |

## Constraints

- **Max runtime:** 30 seconds (local file scanning only)
- **No MCP tools:** Local filesystem access only
- **Stateless:** No side effects