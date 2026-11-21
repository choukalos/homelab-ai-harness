# mcp_kanban — improvement batch: cleanup hardening, project/idea lifecycle tools, spend-by-role, owner-map simplification

- slug: tier2-mcp-kanban-improvements
- date: 2026-11-21
- status: applied (2026-11-21)
- tier: 2
- target user: chuck
- follows: `2026-11-21-tier2-mcp-kanban` (deploy), `-mcp-first` (read-only UI,
  owner attribution), `-phase2-user-spend` (per-user spend)

## Decisions (locked 2026-11-21, chuck)

- **No push notifications** — LLM-centric operation; humans refresh the web
  page. (Dropped from the candidate list.)
- **No cost guardrails for now** — deferred (per-task cost cap or LiteLLM
  key budgets can be revisited; `board_status` already surfaces running
  task cost).
- **Workspace is transitory — 7-day sweep.** `/workspace` dirs are scratch:
  if the work is not pushed back to GitHub or published somewhere, it is not
  needed. Every project's durable results live in pushed branches /
  published locations (backed-up permanent storage), **not** in the
  workspace. The existing 7-day sweep is kept and hardened (below).
- **No re-groom from icebox** — once an idea is in the icebox it is ready to
  go to the backlog and be worked; `groom_re_groom` stays grooming→grooming
  only (when a conversation went off the rails).
- The "nice-to-haves" from the gap audit are in: `edit_idea`, cost-by-role
  on `/reports`, and deriving the owner map from `USER_KEYS` (one less env
  var to keep in sync on key rotation).

## Scope

### 1. Workspace cleanup hardening (the 7-day sweep)

The orchestrator already sweeps `/workspace/task-<id>` dirs older than 7
days (skipping in-flight `running`/`deploy` tasks; safe for all other
states because `prepareWorkspace` re-materializes a missing workspace —
fresh clone + `checkout last_commit` on restart). Gaps closed:

- **`groom-<ideaId>` scratch dirs are never swept** (the sweep regex only
  matches `task-<id>`). Extend the sweep: `groom-<id>` dirs older than the
  age are deleted unless the idea is actively `grooming` (the persisted
  transcript lives in `/data/sessions/groom-<id>.jsonl`, so the scratch dir
  is disposable).
- **Age not configurable**: add `WORKSPACE_CLEANUP_DAYS` env (default 7).
- **Project deletion orphans dirs until the sweep**: `delete_project`
  (item 2) deletes the project's `task-<id>` / `groom-<id>` dirs
  immediately.
- **Document the principle** in the README: workspace = transitory scratch;
  durable copies = pushed/published locations. Repo-less projects are for
  publish-type work (media/blog) where the publish target is the durable
  copy.

### 2. `delete_project` MCP tool (admin)

No project deletion exists anywhere (the UI is read-only; the test project
cleanup had to be done via raw SQL). New admin-only tool:

- 404 unknown project; 409 while any task is `running`/`deploy` (live work
  — pause/stop first).
- Deletes the project row; FK cascades remove ideas/tasks/task_events/usage.
- Immediately removes the project's `task-<id>` + `groom-<id>` workspace
  dirs (durable results are already pushed/published for `done` tasks;
  other states are re-materializable or abandoned with the project).
- Returns the deleted project + the workspace dirs removed.

### 3. `edit_idea` MCP tool (control)

Fix idea text before grooming (typos, scope tweaks). Gated:

- 404 unknown idea; 409 unless state is `idea` (grooming → the spec is
  being generated from the text; icebox → the spec is final; moved → has a
  task; discarded → soft-deleted).
- Only `text` is editable (spec/depends_on are LLM-generated at grooming).
- Returns the updated idea (with project name, like `add_idea`).

### 4. `board_status`: idea pipeline counts

`board_status` is tasks-only today; "what's in the pipeline" needs a second
`list_ideas` call. Add `ideaCounts` — per-state counts of visible ideas
(`idea`/`grooming`/`icebox`; `moved`/`discarded` excluded, same visibility
as `list_ideas`) — honoring the existing `project_id` + `owner` filters
(ideas carry both columns).

### 5. `/reports`: spend by role

Where the money goes: cost (and tokens) per usage role
(`groom`/`task`/`qa`/`summary`/`resolve`) over the same rolling-12-months
window as the other sections, sorted by cost. New "By role — rolling 12
months" table on `/reports`. (Per-project/total/per-user sections unchanged
— all-keys, per the Phase 2 decision.)

### 6. Owner map derived from `USER_KEYS` (drop `MCP_KEY_OWNERS`)

`MCP_KEY_OWNERS` (key-suffix → name) duplicates information `USER_KEYS`
(name → full key) already carries, and key rotation means updating both.
New resolution:

- bearer key === `LITELLM_API_KEY` → `kanban` (unchanged);
- bearer key === a `USER_KEYS` value (full-key match — no suffix
  ambiguity) → that user name;
- anything else → `unknown` (unchanged).

`MCP_KEY_OWNERS` / `KANBAN_MCP_KEY_OWNERS` are removed (compose, .env,
README, .env.example). Rotation = update `USER_KEYS` +
`MCP_KEY_CAPABILITIES` only. Capability sets are unchanged; `delete_project`
joins `admin`, `edit_idea` joins `control`. **Tool count: 23 → 25.**

### 7. Backup coverage (machine-local)

`scripts/backup-hosts/thor.json` (not in the repo): add a weekly
`mysql/ai_kanban` dump (env vars `KANBAN_DB_USER`/`KANBAN_DB_PASS`/
`MYSQL_DB_HOST`, same pattern as `mysql/homelab`) and
`/home/chuck/data/ai-kanban` to the `misc` tar (session files, per-user
agent dirs, specs). Board state + session history become backup-covered.

## Explicitly out of scope (locked)

- Push notifications (LLM-centric + web refresh)
- Cost guardrails (deferred — see decisions)
- Re-groom from icebox (icebox = ready to work)
- `/data` retention policy beyond the workspace sweep (session files +
  agent dirs are small and re-creatable; revisit if they grow)

## Files touched

| File | Change |
|---|---|
| `src/orchestrator.ts` | sweep `groom-<id>` dirs; `cleanupAgeMs` from config; `cleanupProjectWorkspaces(projectId)` |
| `src/config.ts` (+test) | `WORKSPACE_CLEANUP_DAYS` (default 7) |
| `src/services/projects.ts` (+tests) | `deleteProject` (state guard + cascade + dir cleanup) |
| `src/services/ideas.ts` (+tests) | `editIdea` (state-gated text edit) |
| `src/services/board.ts` (+tests) | `BoardStatus.ideaCounts` |
| `src/services/reports.ts` (+tests) | `spendByRole` (rolling 12 mo) |
| `src/services/index.ts` | facade: `deleteProject`, `editIdea`, `ReportsData.roles` |
| `src/mcp/server.ts` (+tests) | `delete_project` + `edit_idea` tools; owner resolution from `USER_KEYS` (drop `parseMcpKeyOwners`) |
| `src/mcp/http.ts` | owner map from `cfg.userKeys` (drop `MCP_KEY_OWNERS`) |
| `src/http/templates.ts` (+tests) | by-role spend section |
| `src/main.ts` | wire `cleanupAgeMs` |
| tests | services / mcp / orchestrator / http / config |
| `README.md`, `.env.example` | 25 tools, cleanup section, `WORKSPACE_CLEANUP_DAYS`, drop `MCP_KEY_OWNERS` |
| `compose/compose.mcp.yml` | drop `MCP_KEY_OWNERS`; add `WORKSPACE_CLEANUP_DAYS` passthrough (default) |
| `mcp/README.md`, `mcp/servers/README.md` | 25 tools |
| `scripts/backup-hosts/thor.json` | `mysql/ai_kanban` + data dir in `misc` (machine-local) |

## Rollout

- [x] Implement + `npm test` green (190 tests: 189 pass, 1 skip = MySQL CI)
- [x] Commit + push
- [x] Deploy on thor + verify (delete_project E2E incl. workspace dirs,
      edit_idea state gate, board_status ideaCounts, /reports by-role,
      owner resolution via USER_KEYS, tool counts 25)
- [x] Backup items added + verified
- [x] Docs updated; mark applied

## Verification (live, thor, 2026-11-21)

- Container healthy; config line shows `cleanupDays=7 userKeys=chuck,dylan`.
- MCP `tools/list` (kanban key): **25 tools** incl. `delete_project` + `edit_idea`;
  dylan (control): 22 (no `delete_project`); LiteLLM proxy: 119 total tools
  (25 `mcp_kanban-*`).
- E2E as chuck (full-key match via USER_KEYS): `create_project` →
  `owner: "chuck"`; `add_idea` → `owner: "chuck"`; `edit_idea` updated text
  (state `idea`); `board_status` → `ideaCounts: {idea:1, grooming:0, icebox:0}`;
  `delete_project` → `{project, removedDirs: []}`; `get_project` after →
  "not found". Throwaway project cascade-deleted.
- `/reports` renders the "By role — rolling 12 months" section (groom/task/qa/
  summary rows present from prior E2E usage).
- Backups: `mysql/ai_kanban` weekly dump + `/home/chuck/data/ai-kanban` in the
  `misc` tar — verified via `backup-nas.sh weekly --dry-run` (dump stored 1.8K).
  Dry run also surfaced + fixed two pre-existing issues:
  - `MYSQL_DB_HOST=thor.local` resolves IPv6-only on the host (no A record)
    while MySQL binds `192.168.4.54:3306` → all three MySQL dumps failed
    (homelab/investorhub/ai_kanban). Fixed: `MYSQL_DB_HOST=192.168.4.54`
    (reachable from host + containers, verified); dumps now store.
  - `KANBAN_MCP_KEY_CAPABILITIES` unquoted `;` broke `source .env` in the
    backup lib (truncated value + "command not found" noise). Fixed: quoted.
