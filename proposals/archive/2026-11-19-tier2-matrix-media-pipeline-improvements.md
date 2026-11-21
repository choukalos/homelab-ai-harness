# Matrix media pipeline: assemble duration semantics, job kill, queue status, progress

- slug: tier2-matrix-media-pipeline-improvements
- date: 2026-11-19
- status: applied
- applied: 2026-11-21 — M1–M5 all landed. Matrix shipped the pipeline side on
  2026-11-19 (`media-pipeline/qa_m1_m5.py` accepted on the GPU host); `/health`
  advertises all four features (`assemble-duration-hold`, `job-kill`,
  `queue-summary`, `job-progress`) with job IDs + FIFO details in the queue
  block (M3/M4). M1 duration is now ENFORCED (frame-hold / trim, loud
  `duration_adjustments`, never silent ignore). Thor-side client layer + live
  acceptance in commit `7f2d0d3` (`test_m1m5_client.py` 24/24 + MCP E2E
  through the proxy — `docs/thor_validation_log.md` part 12, 2026-11-21).
  `agents-skills/media-film/references/pipeline-contract.md` updated with the
  new semantics. (Supersedes the "awaiting matrix session" state of the
  2026-11-19 handoff.)
- tier: 2
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (C14 root cause, C13 progress, A4) + workspace/harness-repo-recovery/improve_mediapipeline_todo.md

## ⚠️ Work host: MATRIX (192.168.4.55), not thor
The pipeline server (API `:8189`) source lives on matrix (under `/home/chuck/data/comfyui/` — **exact path TBD, verify first**); it is not in this repo. `mcp_media` on thor is a thin proxy to matrix:8189. Items here are pipeline-server changes; the thor-side companions are `tier2-media-film-production-lessons` (contract/docs) and `tier3-media-queue-mcp-tools` (MCP tools wrapping M2/M3).

## What
- **M1 (P1 — C14 root cause): assemble duration semantics.** `media_assemble` silently ignores `shots[].duration` as a frame-hold — it concatenates each clip at its natural length (verified in production: 36 × 5.042 s = 181.5 s output against a 226 s plan; the `duration` field is accepted but has no effect). Either (a) implement frame-hold (extend/hold each clip to the requested duration, `tpad stop_mode=clone` semantics) or (b) at minimum **fail loudly / warn** when a requested duration exceeds the clip's natural length. Silent acceptance caused a 44.5 s-short published film (missing closing VO + end card) and one wasted 4.5 h upscale render.
- **M2 (P2 — A4): job kill/abort endpoint.** Client-scoped, idempotent; at minimum reap **queued** (not running) jobs. Superseded/orphaned jobs currently sit in the global FIFO and burn slots (two orphaned keyframe jobs held 2 of 6 queue slots — ~33% capacity — in the film run).
- **M3 (P2 — A4): queue status/summary.** Global occupancy: counts by status, oldest queued job, estimated wait. The health shape already exposes `running`/`queued`/`pending` — extend with job IDs + a summary so clients stop guessing when slots free.
- **M4 (P2 — A4): fix `status=running` under-reporting** in the jobs list (showed 1–2 of 6 in-flight in the film run; per-ID `media_job_result` polling is the only authoritative check today).
- **M5 (P2 — C13): job progress field** for long assembles (e.g. `shot_i/36`). The ledger's `outputs` array already lists completed per-shot artifacts (counting `upNN` gives real progress — 20/36 at ~253 min was how stall detection worked in the film run); an explicit progress field makes it first-class.

## Why (evidence)
- 2026-11-16/17 SW Holiday Spoof run (published 15:04Z after ~16 h, 30 production attempts): C14 defect caught only after the full upscale render; orphaned jobs burned 33% of queue capacity; children had to guess queue occupancy; no stall signal on the 3+ h assemble.
- Companion evidence: `improve_mediapipeline_todo.md` (2026-11-02 peanut run) — job IDs logged nowhere, ephemeral registry (since fixed by the durable ledger).

## Risk + rollback
Medium — this is the GPU-host service and queue semantics. Land M1 first and test with a 2-shot assemble where requested duration > clip length (expect hold or loud warning, never silent ignore); M2 must only touch queued jobs (never kill running GPU work). Rollback = revert the pipeline server on matrix (keep the running version's image/config until the new one is verified).

## Files touched
- Pipeline server source on matrix (TBD — verify location under `/home/chuck/data/comfyui/`)
- `agents-skills/media-film/references/pipeline-contract.md` (thor-side, after the changes land — document the new semantics)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
