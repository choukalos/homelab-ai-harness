# Skill Runner & Skills

## Runner

The skill runner is the new AI Harness foundation — a skill orchestration API that sits beside the current harness.

See [runner/](runner/) for implementation.

## Skills

| Skill | Status | Notes |
|---|---|---|
| [siri_ask](siri_ask/) | | Short mobile answers, safe status lookups |
| [deep_research](deep_research/) | | Cited markdown research reports |
| [investment_brief](investment_brief/) | | Stock/investment analysis |
| [code_review](code_review/) | | Code review on PRs/files |
| [repo_maintenance](repo_maintenance/) | | Repository health, cleanup |
| [family_kb_ingest](family_kb_ingest/) | | Curated KB ingestion (approval gate) |
| [presentation_build](presentation_build/) | | Presenton integration |
| [presentation_update](presentation_update/) | | Update existing presentations |
| [morning_brief](morning_brief/) | | Daily summary (weather, news, status) |
| [homelab_report](homelab_report/) | | Homelab health report |
| [siri_chat](siri_chat/) | | Enhanced chat with MCP tool access |
| [demo_browse](demo_browse/) | | Search/browse demos by keyword |
| [demo_workflow](demo_workflow/) | | Full demo pipeline (research→build→verify) |
| [research_brief](research_brief/) | | Lightweight web research + summarization |

## API

```
POST /skills/{skill_name}      — Launch a skill job
GET  /skills/jobs/{job_id}     — Get job status
GET  /skills/jobs/{job_id}/artifact  — Get job artifact
```

## Rules

- Skills are manifest-driven
- Approval gates enforced for sensitive operations
- Artifacts saved to `/home/chuck/data/media/` by type
- Skills compose MCP tools; MCP servers remain stateless
