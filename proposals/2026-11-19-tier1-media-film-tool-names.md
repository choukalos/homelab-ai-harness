# media-film skill: use the gateway's dash-form tool names

- slug: tier1-media-film-tool-names
- date: 2026-11-19
- status: open
- tier: 1
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (A3b)

## What
Update `agents-skills/media-film/SKILL.md` (and any template that references tool names) to the names the gateway actually serves — **dash-form** (`mcp_media-media_list_jobs`, `mcp_vision-vision_analyze_image`, …) instead of the underscore form `mcp__litellm__mcp_media_*`. Add a one-line "tool names verified against `tools/list` 2026-11-19" note.

Current offending references (verified 2026-11-19): SKILL.md line 36 (MCP gateway row), line 70 (tool list), line 81 (retry-wrapper example).

## Why (evidence)
- 2026-11-17 attempt 8: `tools.mcp__litellm__mcp_media_*` names return **`Tool not found`** on the gateway; only dash-form names are registered (fresh `tools/list`).
- Every production child in the SW Holiday Spoof run had to re-discover this, and the skill's own examples use the broken form.

## Risk + rollback
Trivial doc change; no runtime effect. (Alternative — registering both name forms on the gateway — was rejected as more moving parts for the same benefit.)

## Files touched
- `agents-skills/media-film/SKILL.md`
- `agents-skills/media-film/templates/` (if they reference tool names)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
