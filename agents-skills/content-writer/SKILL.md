---
name: content-writer
description: "Multi-format content generation — produces publish-ready social posts (Twitter/X thread, LinkedIn, short-form), a full blog post (hook -> context -> sections -> CTA), and a video script + visual seeds (shot list), optionally grounded in real research via mcp_search. Output is a Markdown content pack."
---

# Content Writer

Produces publish-ready content in one or more formats for a given topic:

- **social** — Twitter/X thread, LinkedIn post, short-form caption
- **blog** — a full blog post (hook → context → 3-5 sections → CTA)
- **video** — a video script (timecoded VO table) + visual seeds (shot list)
- **all** — all of the above in one content pack

Optionally grounds the content in real research via `mcp_search`.

Design adapted from `langchain-ai/deepagents` `deploy-content-writer` and
`content-builder-agent`.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `content_writer`
- `prompt`: the topic (auto-mapped to the `prompt` input)
- `params`: (optional) `format`, `platform`, `tone`, `brand`, `research`

The call blocks until the skill completes (up to its `max_runtime`, ~300s).
If it's still running when the call returns, you get a `job_id` — retrieve it
with the `get_skill_job` MCP tool.

## Inputs

| Input      | Type    | Required | Default                        | Description                                  |
|------------|---------|----------|--------------------------------|----------------------------------------------|
| prompt     | string  | yes      | —                              | Topic to write about.                        |
| format     | string  | no       | `all`                          | `social`/`blog`/`video`/`all` (or comma-sep).|
| platform   | string  | no       | (per-format defaults)          | Comma-separated target platforms.            |
| tone       | string  | no       | `professional, clear, engaging`| Tone of voice.                               |
| brand      | string  | no       | `neutral, helpful, credible`   | Brand voice.                                 |
| research   | boolean | no       | `true`                         | Ground in web research.                      |
| max_research | integer| no      | `3`                            | Max research searches (0-6).                 |

## Outputs

- `summary` — short summary of the content pack.
- `content` — full content pack in Markdown (all requested formats).
- `artifact_path` — path to the saved `.md` artifact.
- `formats` — list of formats generated.
- `research_count` — number of unique research sources.

## Format details

- **social**: per-platform sections (thread / LinkedIn / short-form) + hashtags.
- **blog**: `# Title`, `## Hook`, `## Context`, `## Section N`, `## Key Takeaways`, `## Call to Action` (600-1000 words).
- **video**: `## Video Concept`, `## Script` (timecoded VO table), `## Visual Seeds` (image-gen prompts).

## Example

```
/skill:content-writer How solar + battery storage cuts home energy bills
```