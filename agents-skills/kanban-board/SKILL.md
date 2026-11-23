---
name: kanban-board
description: Operate the homelab kanban board via the mcp_kanban MCP tools — triage board_status, groom ideas interactively to a spec, move icebox items to the backlog, start or monitor tasks, resolve needs-attention tasks, manage projects. Use when asked to check the board, groom or spec an idea, start or monitor a kanban task, fix a stuck task, or create or update a project.
---

# Kanban Board

Playbook for operating the homelab kanban board (`mcp_kanban`, 25 tools exposed as
`mcp_kanban-<tool>` — in pi sessions via the LiteLLM gateway as
`mcp__litellm__mcp_kanban_<tool>`). Internal system — codified from
`mcp/servers/kanban/README.md` + the 2026-11-21/22/23 kanban proposals (no external
research). Used by all roles: board ops for everyone, grooming = the PRD process for
PM, task lifecycle + deploy gates for the Coding Team, board state as a data source
for the BA.

## Mental model

One shared board. Ideas are per-project; the board is global.

```
per project:  idea ──grooming──▶ icebox ──move_to_backlog──▶ backlog
global board: backlog ─▶ running ─▶ QA ─▶ deploy ─▶ done
                              │
                              └──▶ needs attention (watchdog / QA exhausted / deploy failed)
```

- **Grooming** turns a raw idea into a structured spec (goal / steps / acceptance /
  kind / publish_targets / notes) plus LLM-identified `depends_on` among the
  project's icebox items. It is **interactive by design** — the grooming LLM
  researches (web/KB/memory via its session tools), states assumptions, asks
  questions; the user steers. There is no one-shot path (decided 2026-11-21).
- **The orchestrator** picks backlog tasks up on a timer, gated by dependencies and
  the `CONCURRENT_TASKS` slot. `start_task` bypasses the pickup timer only — the
  gates still apply.
- **QA** is a separate (xhigh) session after the task session completes. **Deploy**
  is automated after a QA pass, routed by task `kind` (code → GitHub push; blog →
  blog repo path; media → the project's public file directories; other → no-op).
  Deploy failure → needs attention (retryable via `retry_deploy`).
- **MCP is the only mutation interface.** The web GUI (`thor.local:3000`) is a
  read-only status view. Every mutation is authenticated (LiteLLM key) and stamped
  with the caller's owner.
- **The workspace is transitory** (`/workspace/task-<id>`, 7-day sweep). Durable
  results live in pushed branches / published locations — never in the workspace.

## Triage (start here)

1. `board_status` — task counts per state, `ideaCounts` (idea pipeline),
   needs-attention summaries (title, project, owner, failure reason, last activity,
   accepted resolution), running tasks (paused, cost).
2. **Needs-attention first**, one task at a time (see "Needs-attention resolution").
3. Running tasks — don't touch unless asked; `board_status` shows pause + cost,
   `task_status` shows detail.
4. Backlog — the orchestrator starts it on a timer; `start_task` only when the user
   explicitly asks to start now.
5. Ideas — the user (or a role agent) decides what to groom next; don't groom
   unprompted.

Signal → meaning:

- `needsAttention` non-empty → something is stuck; this is the board's top priority.
- `running` with `paused: true` → stopped/paused work; resume only on request.
- `ideaCounts` growing → ideas accumulating; a grooming session is due (ask which).
- Deploy failures surface as needs-attention — `retry_deploy` may fix them without
  re-running QA.

## Grooming (idea → spec)

The loop, exactly:

1. `start_grooming(idea_id)` — runs the seed turn. Returns the seed message —
   **relay it to the user**; don't answer the assistant's own questions.
2. `groom_message(idea_id, text)` — one blocking turn (may take minutes at xhigh).
   Relay the reply; iterate until the idea is well-specified.
3. `groom_accept(idea_id)` — the finalize turn runs **in the background** (xhigh,
   several minutes) and produces the structured spec + `depends_on`. Poll
   `groom_status(idea_id)` until `state=icebox` (spec present).
4. Icebox → `move_to_backlog(idea_ids)` when the user wants it worked. The
   orchestrator starts a task only when its `depends_on` ideas have done tasks.

Grooming etiquette:

- **Ask good questions** — scope, success criteria, deploy path, dependencies on
  other icebox items, file inputs (remote clients: reference durable paths — see
  gotchas). State assumptions explicitly; the user corrects them.
- **A good spec is testable, scoped, and names the deploy path** — what "done"
  means (acceptance criteria the QA session can check), what's out of scope, and
  where the result lands (branch, blog path, media target).
- **Re-groom** (`groom_re_groom`) when the conversation went off the rails — fresh
  session, re-seeded. **Cancel** (`groom_cancel`) to keep the idea and discard the
  chat. **Discard** (`discard_idea`) for idea/grooming state only (soft delete,
  audit trail kept; icebox items can't be discarded — move them to the backlog
  instead).
- A failed finalize leaves the idea in `grooming` — keep chatting or re-accept.
- `edit_idea` works only in `idea` state (typos/scope tweaks before grooming).

## Task lifecycle

- `start_task(task_id)` — start a backlog task now (bypasses the pickup timer;
  dependency + slot gates still apply).
- `task_status(task_id)` — state, log tail, usage (total + by role), failure reason,
  accepted resolution plan. The monitoring tool; poll it, don't guess.
- `pause_task` / `stop_task` — abort the session, keep `running` + the paused flag
  (orthogonal to the state machine). `resume_task` — one-click, re-runs from
  `last_commit` (mission brief + progress summary re-injected).
- **Watchdog**: 10 minutes of silence → needs-attention (`watchdog: no activity
  for …`). A quiet task is not necessarily a dead one — check `task_status` before
  acting.

### Needs-attention resolution

One task at a time:

1. `task_status(task_id)` — full failure context + log tail.
2. Diagnose; dialog with the user when the fix is a decision (not a mechanical
   retry).
3. `restart_task(task_id, resolution_note)` — back to backlog (resume from last
   commit, QA rounds reset); the note becomes the accepted plan injected into the
   mission brief.
4. Deploy failures only: `retry_deploy(task_id)` re-runs ONLY the deploy step
   (task stuck in deploy, or needs-attention from a deploy failure). QA-exhausted
   tasks must go through `restart_task` first.

## Project ops

- `create_project` / `update_project` — name required/unique; only provided fields
  change on update. `constraints` is where the project's deploy-gate rules live —
  read it before any deploy-path work.
- `delete_project` (admin) — cascades ideas/tasks/usage; removes the project's
  workspace scratch dirs immediately. **Refused (409) while any task of THAT
  project is running/deploy — pause/stop it first.** The 409 is per-project: a
  running task in another project does not block the delete (verified 2026-11-23).
- **Owner attribution**: projects/ideas stamp the caller's owner at creation; tasks
  inherit the idea's owner. Work runs under the caller's key and spend bills to it —
  don't assume the service key's identity.

## Deploy gates

The deploy stage is automated after QA pass, routed by task `kind`. Per-project
rules live in the project's `constraints` — **always `get_project` (or
`project_status`) and read `constraints` before any deploy-path work.** The
patterns in the current projects:

- **Auto-deploy on push** (Bluebovine — Cloudflare Pages): push to main publishes;
  task branches are NOT deployed. Repo landmines live in the constraints (e.g. don't
  break the D1 `leads` DB).
- **Human-gated production** (Invest Hub): the runner auto-deploys on push to main,
  so NEVER merge/push to main unless the user explicitly says to push to
  production. The deploy stage pushes the task branch for reference only; "push to
  production" = merge the task branch into main.
- **Two-branch publish** (Homelab Blog): `main` = Hugo source, `deploy` = built
  site (portal git-sync serves it live at choukalos.com). Publish = push source to
  main + `./deploy.sh` (builds and pushes to the deploy branch). Never push built
  output to main or source to deploy. Files under the public drop
  (`/home/chuck/data/media/public` → choukalos.com/files/) need no Hugo build.
- **Two-tier media** (Media): archive to the NAS (`/media-store`) before the task
  ends — mandatory, the workspace is transitory. Public publish (`/publish` →
  choukalos.com/files/) only when explicitly asked; never by default.

If a project's constraints are missing or vague, ask the user before deploying —
don't infer a gate.

## Gotchas (this system)

- **Remote clients can't share local paths.** The executor runs in the mcp_kanban
  container on thor. Specs from off-LAN clients must reference durable paths the
  container can see (NAS `/media-store`, the public drop, repo contents) — not
  `~/Code/...`. A durable per-project file store + intake tool is proposed
  (`proposals/2026-11-23-tier2-kanban-remote-client-file-intake.md`) but not built
  yet — check its status before relying on it.
- **The 7-day sweep is real.** Anything not pushed/published by the deploy stage is
  gone in a week. "It's in the workspace" is not a durable result.
- **Grooming turns are slow and blocking** (xhigh thinking) — relay them, don't
  poll aggressively; `groom_status` shows whether a turn is in flight.
- **`groom_accept` returns before the spec exists** — finalize is background; poll
  `groom_status` until `state=icebox`.
- **Dependencies gate silently.** `move_to_backlog` succeeds even when the task
  won't start yet (depends_on not done). Check the project's icebox `depends_on`
  before expecting movement.
- **No cost guardrails** (decided 2026-11-21) — `board_status` surfaces running
  cost; report it, don't enforce.
- **Scratch-project smoke tests are safe** — `create_project` → `delete_project` on
  a task-less scratch project is a clean cycle (verified 2026-11-22/23).
- **Tool count drift** — the kanban README's "Tools (23)" header is stale; the
  table (and the live gateway) have 25.

## References

- `mcp/servers/kanban/README.md` — architecture, config, identity/keys, deploy.
- `proposals/archive/2026-11-21-tier2-mcp-kanban*.md` — the MCP-first + improvements
  decisions (interactive grooming, read-only UI, owner attribution, 7-day sweep,
  `delete_project` semantics).
- `proposals/2026-11-23-tier2-kanban-remote-client-file-intake.md` — open: durable
  file store + `stage_file` + spec-path preflight for remote clients.
