---
name: skill-authoring
description: Authoring guide for the homelab agent-skill library — how to write, structure, register, and test an Agent Skill (SKILL.md). Use when creating a new skill in agents-skills/, revising or trimming an existing one, debugging a skill that won't trigger or triggers too often, deciding whether to split, merge, or fold a capability into an existing skill, or bundling helper scripts into a skill.
---

# Skill Authoring

How to write a skill for `agents-skills/` that agents discover, load, and follow
reliably. Skills are selected **probabilistically** — at startup the model reads only
the name + description of every skill, and loads the body only when it judges the
skill relevant to the task. Everything below serves that: the description decides
whether the skill fires; the body decides whether it helps once loaded.

## Workflow

1. **Decide the mechanism first.** A skill is for judgement-dependent procedure the
   model should find on its own. If a requirement must hold *every time* (a gate, a
   pre-commit check, a deploy guard), it belongs in the harness — a hook, a kanban
   gate, project `constraints` — not in skill prose: prose can be read, deferred, or
   skipped, however firmly worded. If it's short standing context that should be in
   view every turn, it belongs in a memory file (AGENTS.md / CLAUDE.md), not a skill.
   Full comparison: `references/authoring-best-practices.md`, "Choosing the mechanism".
2. **Ground it in real expertise.** Don't generate from general knowledge — the model
   already knows that. Extract from a hands-on task (the steps that worked, the
   corrections made, the I/O formats, the project-specific facts) or synthesize from
   project artifacts (runbooks, specs, review comments, git history, failure cases).
   Generic advice ("handle errors appropriately") has zero value in a skill.
3. **Check the split/merge question.** One skill = one coherent capability (like a
   function). Too narrow → several skills load for one task (overhead, conflicting
   instructions); too broad → the description can't trigger precisely. If the agent
   already handles the whole task well without the skill, the skill isn't adding value
   — don't build it. Rules: `references/authoring-best-practices.md`, "Split vs merge".
4. **Write the description (the trigger).** Highest-leverage part of the skill. What it
   does + when to use it + the concrete terms a real task would contain; third person;
   a little pushy (models under-trigger). Details:
   `references/authoring-best-practices.md`, "The description".
5. **Write the body.** Under 500 lines. Assume the model is smart — add only what it
   wouldn't know: project conventions, non-obvious procedures, gotchas, specific
   tools/paths, rules that must hold. Calibrate freedom per section — fragile steps get
   exact commands, judgement steps get principles + the why. Patterns (gotchas section,
   output templates, checklists, validation loops, plan-validate-execute):
   `references/authoring-best-practices.md`, "Patterns".
6. **Structure with progressive disclosure.** SKILL.md is the table of contents.
   Details go to `references/` — one level deep, no reference chains — with an
   explicit *when to read* pointer ("Read references/X if Y", not "see references/
   for details"). Any reference file over ~100 lines gets a table of contents.
   Deterministic or repeatedly-reinvented logic becomes a tested script in `scripts/`,
   designed for non-interactive agent use (flags, not prompts; `--help`; structured
   stdout; useful errors). Details: `references/authoring-best-practices.md`,
   "Bundling scripts".
7. **Register it.** Repo conventions + Skill Hub registration:
   `references/repo-conventions.md`.
8. **Test it before calling it done.** (a) *Trigger eval* — does it fire on the right
   prompts and not the wrong ones: `references/trigger-eval.md`. (b) *Output eval* —
   run 2–3 real tasks with and without the skill, grade against assertions, read the
   execution traces (not just final outputs). Iterate on observed behaviour, not
   assumptions. In this repo the smoke test is a real board item or a real pi session
   actually following the playbook.

## Gotchas (this repo)

- Frontmatter is parsed by **strict YAML** — an unquoted `: ` (colon + space) in the
  description breaks the client's skill loading. Reword with an em dash or quote the
  value. `tests/test_skills_yaml.py` guards this via the pre-commit hook.
- Adding a skill to `agents-skills/` is **not enough** — it must be registered +
  enabled in the LiteLLM Skill Hub (`scripts/skill-hub-register.sh`) or it won't
  appear in clients' system prompts.
- Description parity: if the skill wraps a skill-runner job, keep the SKILL.md
  description identical to `skills/<name>/skill.yml` (the test enforces it).
- When a skill fails to trigger, fix the **description first** — it's the only thing
  the model sees before deciding to load the skill.
- The description is injected into the system prompt of *every* session with the
  skill available — it costs tokens even when the skill never fires. Keep it to a few
  sentences.

## References

- `references/authoring-best-practices.md` — the full authoring conventions (R1
  research digest, verified against primary sources: Anthropic's official
  best-practices doc, the Agent Skills open spec, the agentskills.io skill-creation
  guides, the arXiv software-engineering treatment, the anthropics/skills repo).
  Read when writing or revising any skill.
- `references/repo-conventions.md` — homelab-specific: location, frontmatter rules,
  Skill Hub registration, smoke test, definition of done. Read when adding or
  registering a skill in this repo.
- `references/trigger-eval.md` — the description-triggering test protocol (query set,
  near-miss negatives, runs, train/validation split). Read when a skill's triggering
  is in question or when optimizing a description.
