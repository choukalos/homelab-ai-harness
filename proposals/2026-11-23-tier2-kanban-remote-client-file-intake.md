# Kanban: durable project file store + intake tool + spec-path preflight for remote clients

- slug: tier2-kanban-remote-client-file-intake
- date: 2026-11-23
- status: open
- tier: tier2 (new surface: MCP tool + storage mount + preflight + docs)
- target user: chuck
- target repo: `homelab` → `mcp/servers/kanban/` + `compose/compose.mcp.yml`

## What

Remote clients (chuck's Mac, off-LAN) author kanban task specs with
**client-local file paths** (`~/Code/...`), but the executor runs in the
`mcp_kanban` container on thor and cannot see the client's filesystem. Three
additions close the gap:

### 1. Durable project file store (the retention design)

A new dedicated, persistent storage area for client-supplied task inputs:

- **Host:** `/home/chuck/data/ai-kanban-files/<project_id>/` — sibling of the
  app-state dir, so it is in the backup scope (staged inputs like FROZEN
  scripts are source-of-truth content and must be backed up) but is NOT
  mixed into app state (`/home/chuck/data/ai-kanban` — migrations, kv, etc.).
- **Container:** new bind mount `- /home/chuck/data/ai-kanban-files:/files`
  → task sessions read `/files/<project_id>/...` directly.
- **Why not `/workspace`:** the workspace is documented transitory scratch
  ("The workspace is transitory — durable results are pushed by the deploy
  stage"), is shared with other consumers (vision, code clones, task repos),
  and carries the 7-day `task-<id>`/`groom-<id>` sweep. A `staging/` subdir
  would survive today's regex (`^(task|groom)-(\d+)$`) only by accident —
  not a design guarantee.
- **Why not the NAS `/media-store`:** that share is for media *outputs* and
  is explicitly outside the backup scope.

**Retention — the load-bearing constraint:** staged files must stay around
for a long time because the work they feed can sit in the **icebox for
months**. Therefore:

- The retention unit is the **project**, not the task. Files live as long as
  the project exists — icebox items are covered by construction.
- Task completion does **not** delete inputs: a `done` task may be restarted
  / retried, and inputs are often shared across a project's ideas.
- Lifecycle GC (cleanup tied to jobs finishing, not a time sweep of live
  inputs):
  - `delete_project` removes `/files/<project_id>/` and its DB rows.
  - Orphan sweep (background job, same pattern as `cleanupWorkspaces`):
    delete `/files/<project_id>/` dirs whose `project_id` no longer exists in
    the `projects` table AND whose files are older than a TTL (default 30
    days) — a safety valve for failed deletions, never for live projects.
  - **GC scope is the durable store only.** NAS references and published
    files are never deleted by kanban: the NAS follows the media pipeline's
    own conventions, and public-drop content is immutable published content.
- A `project_files` table (project_id, path, size, staged_by, staged_at)
  gives the audit trail + the sweep's reference check.

### 2. Intake for remote machines — two modes by input class

**Small inputs (scripts, configs, text — ≤ ~100 MB): push content.**
`stage_file` MCP tool (plus REST `POST /api/projects/:id/files` for
non-MCP clients): a machine remote from the homelab pushes a file into the
project's store and gets back the container-side path to use in specs.

- **Channel:** the existing MCP-over-LiteLLM-proxy path
  (`https://llm.choukalos.com/mcp/mcp_kanban`) — remote clients already talk
  to kanban this way; no new ports, credentials, or network surface.
- **Args:** `project_id`, `path` (relative to the project store; validated —
  no `..`, no absolute paths), `content` (base64; cap ~100 MB). Returns
  `/files/<project_id>/<path>`.
- **Capability:** `control` (project content write), under the existing MCP
  key scoping.

**Media inputs (stills, reference video, audio): reference by location, not
push.** Media belongs on the NAS or in the public drop — not tunneled
through a JSON-RPC tool. The operator/client places the file where media
already lives, and the spec passes a **URL or directory path**:

- **NAS:** the lego media store share (mounted in the container as
  `/media-store/...`; existing pattern — drafts already land there, e.g.
  `/media-store/potato-wars-v2/`). Spec references the container path.
- **Published:** the blog public directory (`/home/chuck/data/media/public`
  → `/publish/...` in the container, served at
  `https://choukalos.com/files/...`). Spec references the public URL.
- **Mechanism:** `stage_ref` MCP tool (REST variant too): registers an
  external reference (URL or NAS path) in `project_files` **without moving
  content**, validating reachability at registration (URL → HTTP HEAD 200;
  NAS path → exists under the mounted root). Registration is optional —
  specs may cite URLs/paths directly — but it gives the preflight + audit
  trail a machine-checkable record.

Spec-authoring convention (README / media-film skill): small inputs →
`stage_file`, use the returned `/files/<project_id>/...` path; media inputs
→ NAS or public drop, cite the URL/path (optionally via `stage_ref`).

### 3. Spec-path reachability preflight

At `move_to_backlog` and `start_task`, extract local file paths **and**
media URLs from the task spec and check each form against the execution
environment: container paths (mounted roots `/files`, `/workspace`,
`/media-store`, `/publish`, `/data`), NAS paths (under the `/media-store`
mount), and URLs (HTTP HEAD → 200, bounded timeout). Unreachable references
return a structured warning listing them — fail fast at task creation, not
after two QA rounds. Advisory by default; strict mode (refuse to start when
inputs are unreachable) opt-in via env.

## Why (evidence)

PWV2 kickoff (2026-11-22/23): Media-project tasks 1–4 were authored with
`~/Code/media-film/potato-wars-v2/...` paths (chuck's Mac, off-LAN). After
the `.returning()` MySQL fix unblocked the state machine, tasks 1 and 2
started, did everything right, and stopped at the P0 preflight gate: the
frozen / evolved scripts exist on **no reachable host** (container fs,
thor, matrix, NAS, blog repo, KB, session store, job ledger — exhaustive
search logged in `/home/chuck/workspace/task-1/PREFLIGHT-STOP.md`). QA
re-verified (round 2) and exhausted → both landed in `needs_attention`.

Cost: 2 tasks × 2 QA rounds of LLM spend + operator intervention (manual
`scp` of the folder into `/workspace/potato-wars-v2/`, then `restart_task`
with a resolution note). Task 3 (F2-B) only got through because it could
reconstruct the script from the vision report + session — not a reliable
path for the FROZEN-script control tasks.

The executor and QA behaved exactly as designed (stop gate, no invented
beats, operator-action-required state). The gap is upstream: a remote client
has no way to (a) share input files with the executor in a durable,
container-visible location, or (b) be told at task creation that the spec's
inputs are unreachable.

## Risk + rollback

- New mount + `project_files` table: additive; rollback = remove the mount
  + tool (data in the store is host-side and untouched).
- `stage_file` / `stage_ref`: path-validated, size-capped writes (same trust
  model as the LAN-only GUI; auth via existing MCP key scoping). `stage_ref`
  is metadata-only — it never touches file content. Rollback: remove the
  tools.
- Preflight: advisory warning by default — no behavior change for existing
  flows. Strict mode is opt-in. Rollback: remove the check.
- False positives: specs that reference paths created by earlier tasks in
  the same project (shared state dirs) — keep the warning advisory; the
  executor's own P0 gate remains the source of truth.
- GC safety: the orphan sweep only touches dirs whose project is gone from
  the DB AND older than the TTL — icebox-retained files of live projects are
  structurally unreachable by it.

## Files touched

- `compose/compose.mcp.yml` — `mcp_kanban` volume:
  `- /home/chuck/data/ai-kanban-files:/files`
- `mcp/servers/kanban/src/mcp/server.ts` — `stage_file` tool; preflight hook
  on `move_to_backlog` / `start_task`
- `mcp/servers/kanban/src/db/schema.ts` — `project_files` table
- `mcp/servers/kanban/src/services/` — new `files.ts` (staging + GC) +
  `preflight.ts` (path extraction + reachability)
- `mcp/servers/kanban/src/orchestrator.ts` — orphan sweep job (pattern:
  `cleanupWorkspaces`)
- `mcp/servers/kanban/README.md` — spec-authoring convention + storage map
- tests: `stage_file` round-trip, `stage_ref` URL/NAS validation, GC
  (project-delete + orphan sweep), preflight warning/strict paths (path +
  URL forms)

---
_Proposed 2026-11-23 during the PWV2 production session (kanban MySQL
`transition()` fix verification); retention design refined 2026-11-23 after
chuck's review (icebox retention constraint — files can't live in the
transitory workspace); media-input mode added 2026-11-23 (media inputs are
NAS/public-drop references — URL or path — not content pushes). Review via
`cli/proposals.sh`; applying is a human decision._
