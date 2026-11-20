# media-film skill: use the gateway's dash-form tool names

- slug: tier1-media-film-tool-names
- date: 2026-11-19
- status: applied
- tier: 1
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (A3b)
- reviewed: 2026-11-19 (pi, thor) — implemented with a corrected fix. Live verification
  overturned the premise: in a thor pi 1.3.0 session the **underscore form works**
  (`mcp__litellm__mcp_media_media_list_jobs` → live response) and the **dash form
  fails** ("does not exist") — the opposite of the 2026-11-17 Mac observation. pi's
  codemode MCP layer names gateway tools per pi/host version; raw gateway names
  (`/v1/mcp/tools`) are dash-form. Fix = auto-detect the working form (cheap
  `media_list_jobs` probe, both forms tried) in the templates + document both forms
  in SKILL.md / pipeline-contract.md. Verified: detection resolves the underscore
  form on thor; templates pass syntax check as codemode async bodies.

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
