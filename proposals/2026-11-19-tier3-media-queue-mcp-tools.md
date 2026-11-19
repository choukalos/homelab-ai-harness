# mcp_media: queue-visibility + kill tools (thor-side, depends on matrix endpoints)

- slug: tier3-media-queue-mcp-tools
- date: 2026-11-19
- status: open
- tier: 3
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (A4 — thor-side half)

## What
Add MCP tools in `mcp/servers/media/server.py` (thin clients over the new matrix pipeline endpoints from `tier2-matrix-media-pipeline-improvements` M2/M3):
1. **`media_kill_job(job_id)`** — client-scoped, idempotent; reaps superseded/orphaned **queued** jobs so they stop burning queue slots.
2. **`media_queue_status()`** — counts by status, oldest queued job, estimated wait (global occupancy, other clients included).
3. Document that per-ID `media_job_result` polling is the authoritative path (or land matrix M4 first and drop the caveat).

## Why (evidence)
- The 25-tool media toolset has **no cancel/kill/abort tool**: two orphaned keyframe jobs (superseded by fix-forward) sat in the global FIFO and burned 2 of 6 queue slots (~33% capacity) until they finished naturally (2026-11-16/17 film run).
- "1 running + 5 queued" is documented but there's no cheap way to see global occupancy — children had to guess when slots freed.
- `media_list_jobs(status=running)` under-reports (showed 1–2 of 6 in-flight).

## Risk + rollback
Low — thin client over new endpoints; no change to existing tools. Depends on the matrix-side endpoints (M2/M3) landing first. Rollback = remove the tools.

## Files touched
- `mcp/servers/media/server.py`
- `agents-skills/media-film/references/pipeline-contract.md` (tool table rows)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
