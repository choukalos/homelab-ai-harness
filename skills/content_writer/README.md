# content_writer — Multi-Format Content Generation Skill

Produces publish-ready content in one or more formats for a given topic:

- **social** — Twitter/X thread, LinkedIn post, and/or short-form caption
- **blog** — a full blog post (hook → context → 3-5 sections → key takeaways → CTA)
- **video** — a video script (timecoded VO table) plus visual seeds (image-gen shot list)
- **all** — all of the above in one content pack

Optionally grounds the content in real research via the `mcp_search` MCP server.

Design adapted from [langchain-ai/deepagents `deploy-content-writer`](https://github.com/langchain-ai/deepagents/tree/main/examples/deploy-content-writer)
and [`content-builder-agent`](https://github.com/langchain-ai/deepagents/tree/main/examples/content-builder-agent) —
brand-voice guidance plus per-format skill prompts.

## How it works

```
topic ──► [Phase 1] (Optional) research grounding (mcp_search.search_web)
              │
              ▼
        [Phase 2] LLM generation per format (matrix-coder via LiteLLM)
              │   - social: thread / LinkedIn / short-form
              │   - blog:   hook -> context -> sections -> CTA
              │   - video:  script + visual seeds
              ▼
        [Phase 3] Save Markdown content pack
              └─► /home/chuck/data/media/content/content_*.md
```

## Inputs

| Parameter        | Type     | Required | Description                                          |
|------------------|----------|----------|------------------------------------------------------|
| `prompt`         | string   | **yes**  | Topic to write about.                                |
| `format`         | string   | no       | `social` \| `blog` \| `video` \| `all` (or comma-separated). Default `all`. |
| `platform`       | string   | no       | Comma-separated target platforms.                    |
| `tone`           | string   | no       | Tone of voice. Default `professional, clear, engaging`. |
| `brand`          | string   | no       | Brand voice. Default `neutral, helpful, credible`.   |
| `research`       | boolean  | no       | Ground in web research. Default `true`.              |
| `max_research`   | integer  | no       | Max research searches (0-6). Default `3`.            |

## Outputs

| Field             | Type     | Description                                   |
|-------------------|----------|-----------------------------------------------|
| `summary`         | string   | Short summary of the content pack.             |
| `content`         | string   | Full content pack in Markdown.                 |
| `artifact_path`   | string   | Path to the saved `.md` artifact.              |
| `formats`         | array    | Formats generated.                             |
| `research_count`  | integer  | Number of unique research sources.             |
| `model_alias`     | string   | LLM alias used.                                |

## Format details

### social
Per-platform sections. Twitter/X gets a 5-7 tweet thread; LinkedIn gets a
120-180 word post; short-form gets a punchy 1-2 sentence caption. Each ends
with 3-5 hashtags.

### blog
A 600-1000 word post with these headings:
`# Title`, `## Hook`, `## Context`, `## Section N` (3-5), `## Key Takeaways`,
`## Call to Action`.

### video
- **Video Concept** — 2-3 sentence concept + target length.
- **Script** — table `| # | Timecode | Narration (VO) | On-screen text |` (8-12 beats, under 2 min).
- **Visual Seeds** — numbered list of 8-12 self-contained image-generation
  prompts (scene, subject, style, lighting, camera angle) ready to feed an
  image/video model.

## Usage

### Via the skill runner (n8n / MCP)

```
run_skill(name="content_writer",
          prompt="How solar + battery storage cuts home energy bills",
          params={"format": "all", "platform": "Twitter/X, LinkedIn, YouTube",
                  "tone": "friendly, practical"})
```

### Standalone CLI

```bash
# Dry run
python3 skills/content_writer/skill.py \
  --prompt "How solar + battery storage cuts home energy bills" \
  --format all --dry-run

# Full run, blog only, no research
python3 skills/content_writer/skill.py \
  --prompt "How solar + battery storage cuts home energy bills" \
  --format blog --no-research
```

## Configuration

| Env var                      | Default                            |
|------------------------------|------------------------------------|
| `CONTENT_WRITER_MODEL_ALIAS` | `matrix-coder`                     |
| `CONTENT_WRITER_MAX_RUNTIME` | `300` (seconds)                    |
| `CONTENT_WRITER_ARTIFACT_DIR`| `/home/chuck/data/media/content`   |
| `LITELLM_BASE_URL`           | `http://localhost:4000`            |
| `LITELLM_API_KEY`            | (empty)                            |

## Constraints

- Max runtime: 300 seconds.
- Read-only: no writes outside the artifact dir.
- All MCP/LLM calls go through LiteLLM — never direct MCP server access.
- Output format: Markdown.
- Never invents statistics without a source; grounds claims in research.