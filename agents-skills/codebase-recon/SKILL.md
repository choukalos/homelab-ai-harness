---
name: codebase-recon
description: Orient in an unfamiliar codebase before touching code — a bounded recon pass that produces a short recon note (what it is, build/test commands, deploy path, conventions, gotchas) that later steps and resumed sessions build on instead of re-deriving. Use when starting a task in a repo you have not worked in (Bluebovine, Invest Hub, any new project), when a task session resumes and the recon note is missing or stale, or when asked to map or understand an unfamiliar codebase.
---

# Codebase Recon

Systematic orientation in an unfamiliar repo at task start. Recon is a **bounded
orientation pass, not a deep read** — the goal is "enough to work safely", not
exhaustive. The artifact is the **recon note**, not the exploration: later steps
(architecture, story breakdown, implementation, QA) and resumed sessions consume
the note instead of re-deriving it.

Grounding: `docs/research/R2-swe-agent-recon.md` (how production SWE agents
orient in unfamiliar repos — repo-map patterns, recon artifacts, time-boxing;
all sources fetched + verified 2026-11-23). Used by the Coding Team (every new
repo; also grounds architecture and story-breakdown).

## The six questions

Recon ends when all six are answered — or each gap is explicitly declared in the
note's `## Could not verify` section:

1. What is it? (one paragraph, stateable)
2. How do I build it? (install + build commands, verified where cheap)
3. How do I test it? (suite command + single-test command; one fast test actually run)
4. How does it deploy? (script/CI step + the gate, if any)
5. Where's the code for *this task*? (entry points + the files the task will touch)
6. What's misleading or non-obvious? (gotchas a new session would trip on)

## Procedure

Each step has a done-criterion; stop at the first stop rule (below).

0. **Consume existing recon first.** AGENTS.md / CLAUDE.md, a prior recon note in
   the workspace, the repo's docs index. Update only what's stale — never
   re-derive what's already written. Done when existing artifacts answer ≥ half
   of the six questions.
1. **What is it.** README → `docs/` (list the tree; don't cat large files).
2. **Cheap whole-repo view.** Directory tree + file types (`git ls-files`,
   `find` — not `cat`); a symbol scan (grep for definitions in the likely
   modules) capped at ~1k tokens of map. The map is a **menu, not the work** —
   its job is to let you pick the 3–5 files to actually read.
3. **Build/install commands.** From `package.json` / `pyproject` / `Makefile` /
   compose files. Dry-run-verify where cheap.
4. **Test command.** Find the framework + the *single-test* command; run one
   fast test to verify the recorded command works. "No tests" is a finding —
   record it explicitly (QA needs to know).
5. **Deploy path.** CI workflows, deploy scripts, project constraints. For
   kanban tasks, read the project's `constraints` (kanban-board skill) — the
   deploy gate is part of the recon.
6. **Entry points.** Main/app files, route handlers, CLI entry — for the
   subsystem this task touches.
7. **Targeted reads.** Read the files the task will touch. Any noisy broad
   search goes to a subagent that returns a ≤1–2k-token summary — raw search
   results stay out of the main context.
8. **Write the recon note** (template below).

## Recon note

```markdown
# Recon: <repo> — <date> — <task>
## What it is
<1–3 lines>
## Commands            <!-- concrete, verified by running where cheap -->
- Install: ...
- Build: ...
- Test (all / one): ...
- Lint/typecheck: ...
## Layout              <!-- top-level map only, 5–10 lines -->
## Entry points        <!-- for the subsystem this task touches -->
## Conventions         <!-- ONLY non-obvious — "use X, never Y" -->
## Gotchas             <!-- misleading code, env vars, live-but-dead-looking dirs, deploy gates -->
## Deploy path         <!-- script/CI + the gate -->
## Could not verify    <!-- honest gaps — what, why, what would be needed -->
```

Artifact rules:

- **<200 lines**, headers + bullets, no dense prose.
- **Concrete, verifiable commands, not adjectives** — "Run `npm test` before
  committing", not "test your changes".
- **Only what fails the two-question test** — "Could it find this by reading the
  code? Would it actually go and look?" Both yes → cut it. Don't write
  architecture or file layout the agent can re-read; only what isn't in the repo.
- **`## Could not verify` is always present** — the same honesty discipline the
  QA report uses; declared gaps beat silent assumptions.

## Stop rules (priority order)

1. Six questions answered (or gaps declared) → stop.
2. The task plan is stateable without more reads → stop. Don't start editing
   before the plan gate — under-recon is the more expensive failure (confident
   wrong edits).
3. Broad/noisy search needed → subagent with a summary budget, not main-context
   reads.
4. Budget exhausted with gaps remaining → write the note with explicit gaps and
   proceed. Declared under-recon beats unbounded over-recon.
5. Same fact corrected twice across sessions → fold it into the durable artifact
   (AGENTS.md / recon note) and start fresh; don't keep re-deriving it.

**Budget:** ~10–15 minutes / ≤ ~30 tool calls for homelab-sized repos; note ≤
200 lines; symbol map ≤ ~1k tokens. (Starting hypothesis — tune on the first
real Bluebovine / Invest Hub tasks.)

## What recon is not (anti-patterns)

- **Not an architecture doc** — no file-layout descriptions the agent can
  re-read from the repo.
- **Not exhaustive** — over-recon spends the context budget before the work
  starts; recall degrades as context grows.
- **Not a reason to skip the plan gate** — jumping straight to code without
  orientation is the documented failure mode.
- **Not raw context** — never dump search results or whole files into the main
  session; subagent summaries only.

## Kanban tasks (explicit section)

- The task workspace (`/workspace/task-<id>`) is **transitory** (7-day sweep).
  Write the recon note in the workspace (e.g. `recon.md`) for the life of the
  task; durable recon facts that recur across tasks go to the project's
  AGENTS.md / README via docs-housekeeping — never only in the workspace.
- On resume (the runner re-runs from `last_commit`), step 0 reads the existing
  recon note before anything else.
- The recon note must record the project's **deploy gate** (read the project's
  `constraints` — kanban-board skill); git-flow enforces it.

## Gotchas (this repo)

- **Tree, not cat** — `find` / `git ls-files` + `head`; cat'ing large files
  burns the whole budget in one call.
- **Verify commands by running** (one fast one), not by reading the config.
- **Homelab repos** — check `compose/`, deploy scripts, and project constraints,
  not just the code; the deploy path is often outside the repo (Caddy, the
  kanban deploy stage, `deploy.sh`).
- **No embedding indexes** — at homelab scale, grep + just-in-time reads beat a
  stale index (R2: the verified production trend).

## References

- `docs/research/R2-swe-agent-recon.md` — the research grounding (repo-map
  patterns, recon artifact format, time-boxing, failure modes).
- `kanban-board` — deploy gates + workspace transience (read when the recon is
  for a kanban task).
- `qa-verify` — the `## Could not verify` discipline carries into the QA report.
- `skill-authoring` (references/authoring-best-practices.md) — the recon note is
  a durable instruction artifact: <200 lines, concrete verifiable instructions.
