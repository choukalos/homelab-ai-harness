---
name: git-flow
description: Git discipline for task branches in the homelab — branch naming (task/<id>), the repo's commit message convention (<area> + imperative subject, evidence in the body), when to push (the deploy stage pushes, not mid-task), the hard rule that main is only touched through the project's explicit deploy gate, and a clean working tree at task end. Use when starting or working a task branch, writing commits for task work, resolving a git conflict or rebase, or pushing or merging anything in a homelab repo.
---

# Git Flow

Git discipline for task branches. Internal convention — codified from the repo's
commit history, the kanban runner's branch handling, and the kanban project
`constraints` (no external research). Used by the Coding Team (code stories →
publish/push to production).

## Branch discipline

- **Task branches are `task/<id>`.** For kanban tasks the runner creates the
  branch in the task workspace (`/workspace/task-<id>`) and the mission brief
  names it. For standalone work (a family pi session), match the repo's
  existing convention — check `git branch -a` first; if there's no convention,
  `task/<short-slug>`.
- **One task = one branch.** Don't work a second task on the same branch.
- **Never merge/push to `main` without the project's explicit gate.** Per-project
  gates live in the kanban project's `constraints` — **read them before any
  deploy-path work** (kanban-board skill). The patterns in the current projects:
  - **Bluebovine** (Cloudflare Pages) — push to main auto-publishes; task
    branches are NOT deployed. Don't push to main mid-task.
  - **Invest Hub** — human-gated production: the runner auto-deploys on push to
    main, so NEVER merge/push to main unless the user explicitly says to push
    to production. The deploy stage pushes the task branch for reference only;
    "push to production" = merge the task branch into main.
  - **Homelab Blog** — two-branch: `main` = Hugo source, `deploy` = built site.
    Publish = push source to main + `./deploy.sh`. Never push built output to
    main or source to deploy.
  - **Media** — archive to the NAS before the task ends (mandatory); public
    publish only when explicitly asked.
  - If a project's constraints are missing or vague, **ask — don't infer a
    gate.**
- **No force-push to shared branches.** Don't delete branches you don't own or
  that the runner tracks (resume re-checks out `last_commit` from them).
- **Conflict/rebase: stop and report, don't force.** Show the conflict, the
  branches, and what you tried. Mechanical conflicts (import order, whitespace)
  may be resolved with a note in the commit body; semantic conflicts go to the
  user. No `--force`, no rebase-then-retry-forever.

## Commits

- **Message style (the repo convention, from the commit history):**
  `<area>: <imperative subject>` — the area is the component (`skills`,
  `kanban deploy`, `portal`, `grafana`, `proposals`, `data-hub` …), the subject
  is imperative ("fix unclickable /files/ links", "add idempotent Skill Hub
  registration script"), with an optional em-dash detail ("— count applied, not
  accepted").
- **Body: what changed + evidence** (what was verified, how, when) for
  significant work. Keep each commit limited to one logical change.
- **Commit at natural checkpoints during the task.** The runner resumes from
  `last_commit` (fresh clone + checkout) — anything not committed on the task
  branch is not resumable, and the workspace is swept after 7 days.
- **Never commit secrets.** The repo has real keys in `.env` — never copy one
  into code, docs, or commits. The pre-commit hook (`.githooks/pre-commit`)
  blocks secret material and validates skill YAML; if it blocks, fix the
  commit — don't bypass (`--no-verify` only if you are SURE).
- **No generated/scratch artifacts in commits** — check `.gitignore` before
  adding; workspace scratch stays in the workspace.

## When to push

- **The deploy stage pushes — don't push mid-task** unless the project says so.
  For kanban code tasks the deploy step pushes the task branch after the QA
  pass (reference push; "push to production" is the project's gate).
- **Standalone (non-kanban) work:** push the task branch once the work is
  verified (qa-verify) — still subject to the project's `main` gate.
- **At task end:** clean working tree, all intended work committed on the task
  branch, branch pushed (or the deploy stage will), and durable results outside
  the transitory workspace.

## Task-end checklist

1. Working tree clean (`git status`) — or deliberately dirty and reported.
2. All intended work committed on the task branch.
3. Branch pushed (or the deploy stage will).
4. `main` / `deploy` branches untouched unless the project's gate was
   explicitly invoked.
5. No secrets, no scratch artifacts in the commits.

## Gotchas

- **The 7-day sweep is real** — uncommitted workspace work is gone in a week;
  commit on the task branch at checkpoints.
- **Resume is `last_commit`** — a fresh clone + checkout; the commit history on
  the task branch *is* the resumable state.
- **Deploy failure ≠ git failure** — `retry_deploy` re-runs only the deploy
  step (kanban-board skill); don't "fix" it by re-pushing from the task
  session.
- **The pre-commit hook is optional but real** — activated per clone with
  `git config core.hooksPath .githooks`; run `python3 tests/test_skills_yaml.py`
  manually when committing skill files on a clone without the hook.

## References

- `kanban-board` — deploy gates + project `constraints` (read before any push
  to main) + the deploy stage's push semantics.
- `qa-verify` — verify before push.
- `docs-housekeeping` — the durable state (proposal/todo notes) that ships
  with the work.
