# Skill Runner & Skills

## Runner

The skill runner is the new AI Harness foundation — a skill orchestration API that sits beside the current harness.

See [runner/](runner/) for implementation.

**Durable job index (MySQL, 2026-08-29):** job state is backed by MySQL `homelab.skill_jobs`
(not in-memory-only) — jobs survive skill-runner restarts; a job still `running`/`pending`
at restart is marked `interrupted`. Best-effort: degrades to in-memory-only if MySQL is
unreachable. See [Cross-Client Skills](../docs/thor_cross_client_skills.md).

**Cross-client access:** the `mcp_skills` MCP server (3 meta-tools: `list_skills`,
`run_skill`, `get_skill_job`) wraps this API so any MCP client can list + run skills
through LiteLLM. See [Cross-Client Skills](../docs/thor_cross_client_skills.md).

## Skills

12 skills are launchable (exposed via `GET /skills`); `code_review` and
`repo_maintenance` are TODO placeholders (no `skill.py`/`skill.yml`).

| Skill | Status | Notes |
|---|---|---|
| [siri_ask](siri_ask/) | ✅ Live | Short mobile answers, safe status lookups |
| [deep_research](deep_research/) | ✅ Live | Cited markdown research reports |
| [investment_brief](investment_brief/) | ✅ Live | Stock/investment analysis |
| [code_review](code_review/) | 📋 TODO | Code review on PRs/files (placeholder) |
| [repo_maintenance](repo_maintenance/) | 📋 TODO | Repository health, cleanup (placeholder) |
| [presentation_build](presentation_build/) | ✅ Live | Presenton integration |
| [presentation_update](presentation_update/) | ✅ Live | Update existing presentations |
| [morning_brief](morning_brief/) | ✅ Live | Daily summary (weather, news, status) |
| [homelab_report](homelab_report/) | ✅ Live | Homelab health report |
| [siri_chat](siri_chat/) | ✅ Live | Enhanced chat with MCP tool access |
| [demo_browse](demo_browse/) | ✅ Live | Search/browse demos by keyword |
| [demo_workflow](demo_workflow/) | ✅ Live | Full demo pipeline (research→build→verify) |
| [research_brief](research_brief/) | ✅ Live | Lightweight web research + summarization |

## API

```
GET  /skills                          — List skills (name, description, inputs, max_runtime, channels)
POST /skills/{skill_name}             — Launch a skill job (synchronous: blocks until terminal or approval gate)
GET  /skills/jobs/{job_id}            — Get job status (durable: survives restarts)
GET  /skills/jobs/{job_id}/artifact   — Get job artifact
POST /skills/jobs/{job_id}/approve    — Approve a job at an approval gate
POST /skills/jobs/{job_id}/cancel     — Cancel a job
```

**Job statuses:** `pending`, `running`, `completed`, `failed`, `awaiting_approval`,
`cancelled`, `interrupted`. Terminal: `completed`, `failed`, `cancelled`, `interrupted`.

## Rules

- Skills are manifest-driven
- Approval gates enforced for sensitive operations
- Artifacts saved to `/home/chuck/data/media/` by type
- Skills compose MCP tools; MCP servers remain stateless
