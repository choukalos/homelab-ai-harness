# mcp_kanban — MCP-first operation: read-only web UI, interactive grooming, board status, owner attribution

- slug: tier2-mcp-kanban-mcp-first
- date: 2026-11-21
- status: implemented (2026-11-21: code + tests green, committed; deploy +
  implemented + deployed + verified 2026-11-21 — see Rollout/Status)
- tier: 2
- target user: chuck
- source: pi session 2026-11-21 (UX review of `thor.local:3000`); extends
  `2026-11-21-tier2-mcp-kanban` (the original mcp_kanban deploy)

## What

Make the LiteLLM MCP surface the **primary (and only mutation) interface**
for mcp_kanban, and turn the web UI (`thor.local:3000`) into a **read-only
status view**:

1. **Read-only web UI** — all mutation endpoints/forms removed from the
   Fastify app; the board, project pages, task detail + live log, grooming
   transcript viewer, and reports remain as GET-only status pages.
2. **Interactive grooming via MCP** — new MCP tools let an LLM client drive
   the grooming chat conversationally: the grooming LLM researches (memory,
   KB, web via its session tools), states its assumptions, asks questions,
   and the user steers it from their client of choice before accepting.
   The one-shot `groom_idea` is **removed** (chuck, 2026-11-21: a one-shot
   pass is not appropriate for prepping an idea to be executed on —
   grooming is interactive by design).
3. **`discard_idea` MCP tool** — idea discard (currently UI-only) becomes a
   tool.
4. **`board_status` MCP tool** — board overview focused on
   needs-attention: counts per state, and for each needs-attention task a
   summary + what attention it needs, so a user can resolve items one by
   one in-dialog via the existing `task_status` → `restart_task(
   resolution_note)` loop.
5. **Owner attribution** — every mutation carries the caller's identity
   (LiteLLM key → user name); `owner` columns on projects/ideas/tasks;
   displayed as a tag on the board and project views.

## Why

- **Closes a real gap:** the web UI is unauthenticated (LAN-only, LAN trust)
  and today allows *admin* mutations (create/edit projects, start/stop
  tasks, discard ideas) from any browser on the LAN — bypassing the
  per-key capability scoping (chuck `admin` / dylan `control`) that MCP
  enforces. Read-only UI + MCP-only mutations means every write is
  authenticated and capability-checked.
- **The MCP surface already covers the full workflow** (16 tools); the UI
  is the laggard. This change finishes the inversion instead of maintaining
  two mutation paths.
- **Grooming quality:** interactive grooming (LLM asks, user steers) is the
  intended human-in-the-loop point; it should live where the conversation
  already happens (the user's LLM client), not in a LAN-only browser page.
- **Observability:** "who owns what / who did what" makes the read-only
  board genuinely informative, and the captured owner is the attribution
  data Phase 2 (per-user spend, `todo_mcp_kanban.md` Q2) needs.

## Locked decisions (2026-11-21, chuck)

| # | Decision |
|---|---|
| 1 | Web UI is **read-only**; MCP is the only mutation interface |
| 2 | **Interactive grooming** via MCP tools — the LLM may ask any questions and state assumptions (memory/KB/etc.); the user steers from their client of choice during a normal chat. The one-shot `groom_idea` tool is **removed** (not appropriate for prepping an idea for execution) |
| 3 | **`discard_idea`** gets an MCP tool (control cap) |
| 4 | A **board status** MCP tool: how many jobs need attention + per-job summary + attention needed, so the user can dialog in their client of choice and resolve needs-attention items one by one |
| 5 | **Owner per board item**, derived from the caller key (key → user name); built into the schema and displayed (tag) on the board/web view |

## Design

### 1. Read-only web UI

Remove from `src/http/app.ts` (endpoints, not just buttons — the REST API
is unauthenticated on the LAN, so hidden forms would be cosmetic):

- `POST /projects`, `POST /projects/:id` (create/edit)
- `POST /projects/:id/ideas`
- `POST /ideas/:id/groom/messages|accept|cancel|re-groom|discard`
- `POST /projects/:id/icebox/move`
- `POST /tasks/:id/pause|resume|stop|retry-deploy`
- `POST /tasks/:id/resolve/messages|accept`

Keep (GET): `/` (board), `/tasks/:id` (+ `/log`), `/projects`,
`/projects/:id`, `/ideas/:id/groom` (becomes a **read-only transcript
viewer** — useful for watching a grooming conversation), `/reports`,
`/health`.

- `src/http/templates.ts`: strip all forms/buttons (project create/edit,
  idea form, icebox move, groom chat input + accept/cancel/re-groom/
  discard, task stop/resume/retry-deploy, resolution dialog section).
- Delete `src/agent/resolve.ts` + `src/agent/resolve.test.ts`
  (`ResolutionDialog` is dead code — the MCP equivalent already exists:
  `task_status` supplies failure context, `restart_task(resolution_note)`
  is the accepted plan).
- `src/http/http.test.ts`: update (removed endpoints → 404; owner-tag
  rendering tests).

### 2. MCP: interactive grooming (new tools, `control` cap)

Thin wrappers over the existing `GroomingManager` (`src/agent/grooming.ts`
already has the full state machine: `startGrooming`, `sendGroomMessage`
(blocking), `acceptGrooming`/`postAcceptGrooming`, `cancelGrooming`,
`reGroom`, `transcript`):

| Tool | Args | Behavior |
|---|---|---|
| `start_grooming` | `idea_id` | idea → grooming; runs the seed turn (LLM researches with its session tools, states assumptions, asks questions); returns the idea + the assistant's seed message (the client relays it to the user) |
| `groom_message` | `idea_id, text` | one blocking turn; returns the assistant reply (client relays to user). Turn watchdog (`GROOM_TURN_STALL_MINUTES`) aborts stalled turns → tool error |
| `groom_status` | `idea_id` | `{ ideaId, state, turn: {active, since, label}, messages (tail 5), spec (if icebox) }` — the polling tool; the per-idea "turn in flight" flag comes from `GroomingManager.turnStatus` |
| `groom_accept` | `idea_id` | kicks off the finalize turn **in the background** (same as the old UI path — xhigh finalize can take minutes); returns the idea (state still `grooming`); client polls `groom_status` until `state=icebox` (spec present) |
| `groom_cancel` | `idea_id` | back to idea, chat discarded |
| `groom_re_groom` | `idea_id` | grooming → grooming: fresh session, re-seeded with the idea (awaited re-seed) — for when the conversation went off the rails |

The one-shot `groom_idea` tool and its `groomIdeaOneShot` service path are
**removed** (chuck, 2026-11-21): grooming is interactive by design — the
LLM must be able to ask questions and the user must steer before an idea
is prepped for execution.

### 3. MCP: `board_status` (new tool, `read` cap)

`board_status(project_id?, owner?)` →

```json
{
  "counts": { "backlog": 2, "running": 1, "deploy": 0,
              "done": 5, "needs_attention": 2 },
  "needsAttention": [
    { "taskId": 12, "title": "...", "projectId": 1, "project": "homelab",
      "owner": "dylan", "reason": "watchdog: no activity for 10m",
      "lastActivityAt": 1763827200000, "resolution": null }
  ],
  "running": [
    { "taskId": 13, "title": "...", "projectId": 1, "project": "homelab",
      "owner": "chuck", "paused": false, "cost": 0.42 }
  ]
}
```

Tool description points at the resolution loop: "resolve a
needs_attention task with `task_status(task_id)` (full failure context +
log tail) → dialog with the user → `restart_task(task_id,
resolution_note)`". Backlog/icebox detail stays with `list_ideas` /
`project_status` (no duplication).

### 4. MCP: `discard_idea` (new tool, `control` cap)

`discard_idea(idea_id)` → wraps `GroomingManager.discardIdea` (soft delete:
state `discarded`).

### 5. Owner attribution (key → user)

- **Env:** `MCP_KEY_OWNERS` (container; `.env` var
  `KANBAN_KEY_OWNERS`), format `name:key-suffix;...` — same tail-matching
  style as `MCP_KEY_CAPABILITIES`. Homelab:
  `chuck:faxfoUszvw;dylan:JAS3o6tu0A` (same tails as
  `KANBAN_MCP_KEY_CAPABILITIES`). The kanban service key
  (`LITELLM_API_KEY`) → owner `kanban`. A key present in
  `MCP_KEY_CAPABILITIES` but missing from `MCP_KEY_OWNERS` → `unknown`
  (boot warning).
- **Schema:** new migration `0002_owner` (additive, both drivers):
  `owner TEXT NOT NULL DEFAULT ''` on `projects`, `ideas`, `tasks`
  (+ Drizzle `schema.ts` columns). Legacy rows stay `''` → displayed as
  "—" (no backfill).
- **Semantics:** owner = the creator of the work item. `add_idea` /
  `create_project` stamp the caller's owner; tasks **inherit the idea's
  owner** at `move_to_backlog` (the person who asked for the work owns it,
  regardless of who pushed it forward).
- **Threading:** `src/mcp/http.ts` resolves the owner per request (new
  `resolveMcpOwner(bearer, kanbanKey, map)` in `src/mcp/server.ts`,
  mirroring `resolveMcpCapabilities`); `createKanbanMcpServer(services,
  allowedTools, owner)` passes it into the mutation tool handlers;
  `services.createProject` / `services.addIdea` gain an optional `owner`
  param (default `''`).
- **Display:** owner tag on board cards, project-page idea lists, and task
  detail (board service + templates).
- **Listing:** `list_ideas` (service + MCP tool) excludes `discarded`
  ideas — the soft-delete "disappears from every view" semantics now hold
  for the MCP surface too (state kept for the audit trail).

### Capability matrix (before → after)

| Set | Before | After |
|---|---|---|
| `read` | list_projects, get_project, list_ideas, task_status, project_status | + **board_status** (6) |
| `control` | read + add_idea, groom_idea, move_to_backlog, start_task, pause/resume/stop_task, retry_deploy, restart_task (14) | − groom_idea; + start_grooming, groom_message, groom_status, groom_accept, groom_cancel, groom_re_groom, discard_idea (21) |
| `admin` | control + create_project, update_project (16) | (23) |

Total tools 16 → **23** (chuck 23 / dylan 21).

### Env / config

- `.env`: `KANBAN_KEY_OWNERS=chuck:faxfoUszvw;dylan:JAS3o6tu0A`
  (mcp_kanban block).
- `compose/compose.mcp.yml`: `- MCP_KEY_OWNERS=${KANBAN_KEY_OWNERS}`.
- `src/config.ts`: parse + `resolveMcpOwner`.
- LiteLLM config: **no change** (same `mcp_kanban` entry; tool list is
  dynamic).

## Files touched

App (`mcp/servers/kanban/`):

- `src/db/migrations.ts` (+`0002_owner`), `src/db/schema.ts`
- `src/config.ts` (owner map + resolution)
- `src/mcp/http.ts` (per-request owner), `src/mcp/server.ts` (8 new tools,
  owner param, capability sets, tool descriptions)- `src/services/index.ts` (owner params; `boardStatus`), `src/services/
  board.ts` (owner on cards; board_status data), `src/services/projects.ts`,
  `src/services/ideas.ts`, `src/services/tasks.ts` (owner inheritance)
- `src/agent/grooming.ts` (one-shot `groomIdeaOneShot` + `postGroomMessage`
  removed; `turnStatus` drives the live indicators + `groom_status`)
- `src/http/app.ts` (mutation endpoints removed; groom page read-only),
  `src/http/templates.ts` (forms stripped; owner tags)
- delete `src/agent/resolve.ts`, `src/agent/resolve.test.ts`
- tests: update `src/http/http.test.ts` (MCP surface covered end-to-end
  there: tool list, auth/scoping, interactive grooming, board_status,
  owner stamping, read-only UI), `src/db/db.test.ts`,
  `src/services/services.test.ts`, `src/agent/grooming.test.ts`
- `README.md`, `.env.example`

Homelab:

- `compose/compose.mcp.yml`, `.env` (KANBAN_KEY_OWNERS)
- `mcp/README.md`, `mcp/servers/README.md` (tool counts / description)
- `todo_mcp_kanban.md` (pointer + Phase 2 note)

## Test plan

- `npm test` green (build + node --test):
  - migration `0002_owner` on both drivers (column present, idempotent)
  - `resolveMcpOwner` (kanban key → `kanban`, suffix match, unknown)
  - new MCP tools: happy paths + error paths; capability scoping
    (dylan can't `create_project`; read-only key can't `groom_message`);
    owner stamping on create_project/add_idea; task owner inheritance
  - `board_status` shape + filters (project_id, owner)
  - interactive grooming state machine via mocked session (start →
    message → accept → icebox; cancel; re-groom; turn-active flag)
  - http: removed endpoints 404; owner tag renders (incl. legacy "—")
- E2E through the proxy (post-deploy): new tools visible; **verify no
  bare-name collisions** against the other 94 proxy tools; chuck + dylan
  calls stamp the right owner; unknown key 401.

## Rollout

1. Implement + `npm test` green. Commit.
2. thor: `docker compose -f compose/compose.mcp.yml up -d --build
   mcp_kanban`.
3. Verify: migration `0002_owner` applied (owner column on 3 tables);
   `/health` 200; UI read-only (no forms; owner tags render "—" on legacy
   rows).
4. E2E via proxy (step 2 test plan).
5. Update this proposal → applied; update `todo_mcp_kanban.md` status.

## Risks + rollback

- **Users of the UI write paths** must move to MCP (chuck/dylan keys).
  The UI had no auth, so no one was relying on *authorized* UI writes;
  this is a behavior change, not a permission loss.
- **Bare-name collisions at the proxy** (tools surface unprefixed):
  `board_status`, `start_grooming`, `groom_*`, `discard_idea` checked
  against the 94 existing proxy tools at deploy.
- **Removing `groom_idea`** changes the grooming workflow for any client
  using the one-shot path (none known — the UI used the interactive chat;
  this is the first external MCP consumer).
- **`groom_accept` is async** (background finalize): clients must poll
  `groom_status`; documented in the tool description. Long blocking
  `groom_message` turns are bounded by the turn watchdog; proxy MCP
  timeout is 7200s.
- **Rollback:** git revert + rebuild; migration `0002_owner` is
  additive-only — leaving the (unused) column in on rollback is safe.

## Status

- [x] Implement (slices: schema+owner → MCP tools → read-only UI → docs)
      (2026-11-21: all slices done; `groom_idea` one-shot path removed per
      locked decision 2)
- [x] `npm test` green (172 tests: 171 pass, 1 skip = MySQL w/o test server)
- [x] Commit
- [x] Deploy on thor + verify (migration, UI, E2E via proxy)
- [x] Docs updated (READMEs, .env.example, todo pointer)
- [x] Mark applied

### Verification record (2026-11-21, commit `c45e418`)

- `docker compose -f compose/compose.mcp.yml up -d --build mcp_kanban`
  — clean build, container healthy.
- MySQL: `schema_migrations` = `0001_init` + `0002_owner`; `owner
  varchar(64) NOT NULL` on `projects`, `ideas`, `tasks`.
- UI: board + projects pages 0 forms, read-only hints present;
  `POST /projects` → 404; owner tag `chuck` renders on the projects page.
- Direct MCP (`thor.local:3000/mcp`): kanban key 23 tools; chuck 23;
  dylan 21; unknown key 401. `create_project` as chuck → `owner: "chuck"`
  (test row removed afterwards).
- Proxy (`/mcp` gateway): 117 tools = 94 + 23 kanban (`mcp_kanban-`
  prefixed by the gateway; no duplicates/collisions). `board_status` as
  chuck → correct camelCase payload; `create_project` as dylan → refused
  with the capability message.
