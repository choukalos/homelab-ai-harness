---
name: docs-housekeeping
description: Keep the homelab repo's durable state clean — the proposal lifecycle (open, accepted, applied/dismissed; two-place state, markdown file + MySQL row, both must agree; closed files move to proposals/archive/), refreshing Current-state sections when work lands, retiring completed todo files, recording applied+verified notes, and the ship-docs checklist for features that change user-facing docs. Use when applying or dismissing a proposal, after significant work lands, when a todo file is done, when asked to clean up docs, or when shipping a feature that changes user-facing docs.
---

# Docs Housekeeping

Keep the repo's durable state clean. Codifies the 2026-11-22 proposal cleanup
(archive the applied mcp-kanban series + refresh Current state, commit
`dc83c4f`) and the standing spec in `proposals/README.md` (internal convention,
no external research). Used by the Coding Team (the update-documentation step)
and all roles (durable state — strategy docs, PRDs, and reports live here too).

## Proposal lifecycle

- **States:** `open → accepted → applied` / `dismissed` (terminal).
- **Two-place state, keyed by slug (canonical):** the markdown file in
  `proposals/` (`YYYY-MM-DD-tierN-<slug>.md`) **and** a row in the `proposals`
  MySQL table. **Both must agree** — a file without a row, or a row without a
  file, is drift; fix both.
- **Transitions via the CLI** (admin key, talks to skill-runner
  `/api/proposals/*`):

  ```
  cli/proposals.sh list [status] [--limit N]
  cli/proposals.sh show <slug>
  cli/proposals.sh accept <slug>
  cli/proposals.sh dismiss <slug>
  cli/proposals.sh mark-applied <slug>
  ```

- **Applying is a human decision** (chuck). This skill documents, verifies, and
  records — it doesn't decide.
- **Applied/dismissed files move to `proposals/archive/`** (keep the filename;
  the slug in the file metadata + DB row is canonical — legacy files may have a
  slug that doesn't match the filename).
- **Verification record:** significant work gets a short "applied + verified"
  note in the proposal — the `applied:` metadata line (or a section): what was
  verified, how, when, by whom. Pattern (from the housekeeping proposal):
  "H1: pinned the three remaining `:latest` images … digests read from
  `docker image inspect` and verified to resolve to each running container's
  image ID; config-only, no restart."

## Refresh "Current state"

When work lands, refresh the **Current state** sections that mention it — the
`proposals/` README, skill docs, ops docs. A stale reference gets **fixed or
deliberately marked historical** (with a date), never left silently stale.
Pattern: the archive + the Current-state refresh land in the **same change**
(the 2026-11-22 cleanup did both in one commit).

## Retire completed todo files

When a todo/plan file is done:

1. **Durable content moves first** — decisions → the relevant proposal or doc;
   status/outcomes → the doc's header (the `todo_agent_skills.md` status lines
   are the pattern: "built 2026-11-23 (…)").
2. **Then retire the file** (archive or delete) — the `todo_mcp_kanban.md`
   retirement is the reference case.
3. Never delete durable content; never leave a completed todo file looking open.

## Ship-docs checklist (gap G6)

When a feature ships, the docs that must change — check each, update it, or
record why it doesn't need to:

1. **README** (repo or project) — if the feature changes what the project is or
   how it's used.
2. **API/ops docs** — new endpoints, config, env vars (`docs/operations/`,
   project READMEs).
3. **User-facing docs** — the surface users see (portal, blog, sites).
4. **Project `constraints`** (kanban) — if the deploy gate or behavior changed.
5. **Current-state sections** that mention the changed area.

Rule: a change that alters behavior and leaves the docs it made stale unupdated
is **incomplete** — either update them or record why not (task report /
proposal note).

## Housekeeping pass (when asked to "clean up docs")

1. **Proposals:** every file's status matches its DB row
   (`cli/proposals.sh list`); applied/dismissed files are in `archive/`; the
   Current state section is current (date it).
2. **Todo files:** any that are done → retire per the rules above.
3. **Stale references:** grep for the changed thing (a retired service, a moved
   path, an old port) and fix or mark historical.
4. **Verification record:** the significant work from this session gets its
   applied+verified note.

## Gotchas

- **Two-place drift is the #1 failure** — always check the DB row, not just the
  file (or vice versa); the slug is the join key.
- **The slug is canonical** — legacy files may have a slug that doesn't match
  the filename (file metadata + DB row win).
- **"Current state" sections rot fastest** — date them, and refresh them in the
  same change that makes them stale.
- **Archive ≠ delete** — closed proposals stay in `archive/` for history.

## References

- `proposals/README.md` — the spec (lifecycle, layout, tiers, Current state).
- `cli/proposals.sh` — the lifecycle CLI (list/show/accept/dismiss/mark-applied).
- `skills/runner/proposals.py` — the DB table (schema; idempotent insert by
  slug).
- `git-flow` — the commits that ship the housekeeping (one logical change per
  commit; the archive + refresh land together).
