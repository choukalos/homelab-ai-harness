# Homelab repo conventions for skills

Repo-specific rules for adding, registering, and verifying a skill in this
repository. The general authoring conventions live in
`authoring-best-practices.md`; this file is the "how it works *here*" layer.

## Location and structure

- One directory per skill: `agents-skills/<name>/` (hyphenated, lowercase).
- `SKILL.md` (required) + optional `references/` (docs loaded on demand),
  `templates/`, `tools/` (helper scripts — the repo convention; the open spec calls
  this `scripts/`, either works, pick one and be consistent within the skill).
- `name` in the frontmatter **must match the directory name**.
- Distinct from skill-runner one-shot jobs in `skills/` (a `skill.yml` + `skill.py`
  job that runs server-side). A SKILL.md wrapper can *wrap* such a job (the wrapper
  tells the agent to call `mcp_skills run_skill`); a pi-native skill is pure
  workflow guidance the agent follows itself.

## Frontmatter

```yaml
---
name: skill-authoring
description: <what it does + when to use it>
---
```

- Strict YAML — clients parse it with a strict parser. An unquoted `: ` (colon +
  space) inside `description` makes the file invalid and the client fails to load the
  skill. Reword with an em dash (repo convention) or quote the value.
- `description`: what it does + when to use it, specific key terms, third person, a
  little pushy (see `authoring-best-practices.md`, "The description"). Hard limit
  1024 characters.
- If the skill wraps a skill-runner job, keep the SKILL.md description **identical**
  to `skills/<name>/skill.yml` (source of truth) — `tests/test_skills_yaml.py`
  enforces parity.

## Guardrails (automated)

- `tests/test_skills_yaml.py` — 7 checks: strict YAML parse, name/dir match,
  skill.yml validity, wrapper/skill.yml description parity, regression cases. Wired
  into the pre-commit hook (`.githooks/pre-commit`; activate with
  `git config core.hooksPath .githooks`).
- The open-spec validator (`skills-ref validate <skill-dir>`) can be used as an extra
  check (see `authoring-best-practices.md`, "Ecosystem and tooling").

## Skill Hub registration (required)

Adding a skill to `agents-skills/` is **not enough** — it must be registered +
enabled in the LiteLLM Skill Hub or it won't appear in `marketplace.json` / clients'
system prompts.

- `scripts/skill-hub-register.sh` registers + enables **every**
  `agents-skills/<name>/` wrapper idempotently (skips already-registered;
  `--list` for hub state). Run on thor after any `git pull` that adds skills.
- Requires `LITELLM_MASTER_KEY` (from `.env` on thor). `LITELLM_BASE_URL`
  defaults to `http://localhost:4000`; on thor the port is published on the LAN IP
  (192.168.4.54), not 127.0.0.1 — the script auto-falls back to the LAN IP when
  localhost is unreachable.
- Note: the `litellm_skill_create` MCP tool 401s on create; the script's direct
  `POST /claude-code/plugins` path is the working one.
- Effect: pi (any machine) picks the skill up via `marketplace.json` on next
  session; kanban workers pick it up on next container start.

## Smoke test (definition of done)

A skill is done when:

1. `agents-skills/<name>/SKILL.md` (+ references/templates/tools as needed) exists.
2. Description written as "when to use this" (what + when + key terms).
3. Research findings (if any) cited in the skill header or a `references/` note.
4. Committed + pushed; registered + enabled in the Skill Hub
   (`scripts/skill-hub-register.sh`).
5. **Smoke test**: a real board item or a real pi session actually follows the
   playbook — not a hypothetical walkthrough. For role skills, the smoke test is the
   role running its workflow end-to-end on a real item and producing the handoff
   artifact.

## Commit conventions

- Commit message: `<area>: <what>` (e.g. `skills: add skill-authoring meta-skill from
  R1 research`).
- Durable state: significant work gets a short "applied + verified" note in the
  relevant proposal/todo doc (what was verified, how, when) — see the `proposals/`
  lifecycle.
