# Kanban: file intake + spec-path reachability for remote clients

- slug: tier2-kanban-remote-client-file-intake
- date: 2026-11-23
- status: open
- tier: tier2 (new surface: MCP tool + preflight + docs)
- target user: chuck
- target repo: `homelab` → `mcp/servers/kanban/`

## What

Remote clients (chuck's Mac) author kanban task specs with **client-local file
paths** (`~/Code/...`), but the executor runs in the `mcp_kanban` container on
thor and cannot see the client's filesystem. Two additions close the gap:

1. **File intake** — a new MCP tool `stage_file` (or REST
   `POST /api/projects/:id/files`): a remote client pushes input files into a
   container-visible staging area (`/workspace/staging/<project_id>/...`) and
   gets back the container-side path to use in the spec. Clients already talk
   to kanban over MCP/HTTP, so this gives them a first-class way to share
   files with the executor instead of `scp`-ing to a host path by hand.
2. **Spec-path reachability preflight** — at `move_to_backlog` and
   `start_task`, extract local file paths from the task spec and check them
   against the execution environment (mounted roots `/workspace`,
   `/media-store`, `/publish`, `/data`). Unreachable paths return a structured
   warning listing them — fail fast at task creation, not after two QA rounds.
   Advisory by default; strict mode (refuse to start when inputs are
   unreachable) opt-in via env.

Plus a spec-authoring convention in the kanban README / media-film skill:
specs reference execution-environment paths; stage client files first.

## Why (evidence)

PWV2 kickoff (2026-11-22/23): Media-project tasks 1–4 were authored with
`~/Code/media-film/potato-wars-v2/...` paths (chuck's Mac, off-LAN). After the
`.returning()` MySQL fix unblocked the state machine, tasks 1 and 2 started,
did everything right, and stopped at the P0 preflight gate: the frozen /
evolved scripts exist on **no reachable host** (container fs, thor, matrix,
NAS, blog repo, KB, session store, job ledger — exhaustive search logged in
`/home/chuck/workspace/task-1/PREFLIGHT-STOP.md`). QA re-verified (round 2)
and exhausted → both landed in `needs_attention`.

Cost: 2 tasks × 2 QA rounds of LLM spend + operator intervention (manual
`scp` of the folder into `/workspace/potato-wars-v2/`, then `restart_task`
with a resolution note). Task 3 (F2-B) only got through because it could
reconstruct the script from the vision report + session — not a reliable path
for the FROZEN-script control tasks.

The executor and QA behaved exactly as designed (stop gate, no invented
beats, operator-action-required state). The gap is upstream: a remote client
has no way to (a) share input files with the executor, or (b) be told at task
creation that the spec's inputs are unreachable.

## Risk + rollback

- `stage_file`: additive; path-validated, size-capped writes under the
  existing `/workspace` mount (same trust model as the LAN-only GUI; auth via
  the existing MCP key scoping). Rollback: remove the tool.
- Preflight: advisory warning by default — no behavior change for existing
  flows. Strict mode is opt-in. Rollback: remove the check.
- False positives: specs that reference paths created by earlier tasks in the
  same project (shared state dirs) — keep the warning advisory; the executor's
  own P0 gate remains the source of truth.

## Files touched

- `mcp/servers/kanban/src/mcp/server.ts` — `stage_file` tool; preflight hook
  on `move_to_backlog` / `start_task`
- `mcp/servers/kanban/src/services/` — new `files.ts` (staging) +
  `preflight.ts` (path extraction + reachability)
- `mcp/servers/kanban/README.md` — spec-authoring convention
- tests: `stage_file` round-trip + preflight warning/strict paths (SQLite
  driver; the MySQL transition path is already covered by
  `orchestrator-mysql.test.ts`)

---
_Proposed 2026-11-23 during the PWV2 production session (kanban MySQL
`transition()` fix verification). Review via `cli/proposals.sh`; applying is
a human decision._
